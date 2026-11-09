"""Process qualification and an independent chronological state replay.

The optimizer consumes these semantics, but replay reconstructs state from
the original snapshot rather than trusting solver variables or result traces.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .errors import ReplayError
from .policy import COUNTER_FIELDS

CONDITION_PATTERN = re.compile(r"^2([0-9])([A-F])$")


def steel_key(grade: Any) -> str:
    """Keep upstream values intact while looking up their configured code."""
    return str(grade)


def parse_condition(code: Any) -> tuple[int, str] | None:
    if not isinstance(code, str):
        return None
    match = CONDITION_PATTERN.fullmatch(code)
    return (int(match[1]), match[2]) if match else None


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open service intervals allow exact ready/start equality."""
    return a_start < b_end and b_start < a_end


def heat_ready_at(heat: dict[str, Any], request: dict[str, Any]) -> int:
    return heat.get("ready_at", heat["cast_finish_at"] + request["turnaround_seconds"])


def reservation_ready_at(reservation: dict[str, Any], request: dict[str, Any]) -> int:
    return reservation.get("ready_at", reservation["cast_finish_at"] + reservation.get("turnaround_seconds", request["turnaround_seconds"]))


def initial_state(ladle: dict[str, Any], request: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Snapshot counters include past-started services, including busy ones."""
    condition = parse_condition(ladle.get("condition_code"))
    band = condition[0] if condition else -1
    last_use = ladle.get("last_use") or {}
    allow_assumptions = policy is None or policy["source"] == "assumed"
    sources = request.get("candidate_provenance", {}).get(ladle["ladle_id"], {})
    clean = (allow_assumptions and not last_use and ladle.get("history_assumption", "unknown") == "clean"
             and (sources.get("history_assumption") == "assumed" or ladle.get("data_source", "provided") == "assumed"))
    state = {
        field: ladle.get(field) for field in COUNTER_FIELDS
    }
    state.update({
        "condition_code": ladle.get("condition_code"),
        "previous_grade": last_use.get("grade"),
        "last_cast_finish_at": last_use.get("cast_finish_at"),
        "ready_at": ladle["available_at"],
        "repair_stage": 0 if band in {8, 9} else 1 if band == 7 else 2,
        "history_known": clean or last_use.get("grade") is not None,
        "thermal_cast_finish_at": last_use.get("cast_finish_at"),
        "thermal_source": "provided_history" if last_use.get("cast_finish_at") is not None else "unknown",
    })
    if allow_assumptions and state["thermal_cast_finish_at"] is None and 0 <= band <= 6:
        # This clock is expressly an estimate of thermal age, not fabricated
        # previous-use history and not a replacement for execution readiness.
        boundaries = (0, *(policy["thermal_boundaries_seconds"] if policy else (3600, 5400, 7200, 9000, 10800, 14400)))
        midpoint = (boundaries[band] + boundaries[band + 1]) // 2 if band < 6 else boundaries[-1] + 1
        state["thermal_cast_finish_at"] = request["snapshot_at"] - midpoint
        state["thermal_source"] = "estimated_from_snapshot_condition"
    # Already-started reservations are included in snapshot counters. Their
    # latest known completion still establishes the immediate predecessor,
    # including services completed exactly at or before the snapshot.
    started = [r for r in ladle.get("reservations", []) if r["use_start_at"] < request["snapshot_at"]]
    latest = max(started, key=lambda r: r["cast_finish_at"]) if started else None
    if latest is not None and (
        last_use.get("cast_finish_at") is None or latest["cast_finish_at"] > last_use["cast_finish_at"]
    ):
        state["previous_grade"] = latest.get("grade")
        state["history_known"] = latest.get("grade") is not None
        state["last_cast_finish_at"] = latest["cast_finish_at"]
        state["thermal_cast_finish_at"] = latest["cast_finish_at"]
        state["thermal_source"] = "provided_history"
    ongoing = [r for r in started if request["snapshot_at"] < reservation_ready_at(r, request)]
    if ongoing:
        state["ready_at"] = max(state["ready_at"], *(reservation_ready_at(r, request) for r in ongoing))
    return state


def condition_at(heat: dict[str, Any], ladle: dict[str, Any], state: dict[str, Any], policy: dict[str, Any]) -> tuple[str | None, bool]:
    """Use the manual's next-tapping proxy separately from the ready deadline."""
    original = parse_condition(ladle.get("condition_code"))
    if original is None:
        return None, False
    band, suffix = original
    if state["repair_stage"] == 0:
        return f"2{band}{suffix}", False
    if state["repair_stage"] == 1:
        return f"27{suffix}", False
    previous_finish = state.get("thermal_cast_finish_at")
    if previous_finish is None:
        return f"2{band}{suffix}", False
    elapsed = heat["tap_finish_at"] - previous_finish
    thermal_band = sum(elapsed > boundary for boundary in policy["thermal_boundaries_seconds"])
    stopped = elapsed > policy["thermal_stop_after_seconds"]
    return f"2{thermal_band}{suffix}", stopped


def static_rejections(heat: dict[str, Any], ladle: dict[str, Any], request: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    """Only prune facts which later services cannot repair within this scope."""
    codes: list[str] = []
    profile = policy["profiles"].get(steel_key(heat["grade"]))
    if profile is None:
        return ["unknown_steel_grade"]
    if ladle.get("status") not in {"AVAILABLE", "BUSY"}:
        codes.append("ladle_unavailable")
    if ladle["available_at"] > heat["use_start_at"]:
        codes.append("not_ready")
    condition = parse_condition(ladle.get("condition_code"))
    if condition is None:
        codes.append("missing_condition" if ladle.get("condition_code") is None else "unsupported_condition")
    elif condition[1] not in profile["allowed_cold_steel_suffixes"]:
        codes.append("cold_steel_condition_mismatch")
    material = ladle.get("material_code")
    if material is None:
        codes.append("missing_material_code")
    elif material not in profile["allowed_materials"]:
        codes.append("material_mismatch")
    for field, maximum in policy["limits"].items():
        value = ladle.get(field)
        if value is None:
            codes.append("missing_" + field)
        elif value + 1 > maximum:
            codes.append("exhausted_" + field)
    if ladle.get("usage_count") is None:
        codes.append("missing_usage_count")
    requires_argon = any(operation["operation"] in policy["argon_operations"] for operation in heat["operations"])
    if requires_argon and ladle.get("argon_ready") is not True:
        codes.append("missing_argon_ready" if ladle.get("argon_ready") is None else "argon_unavailable")
    start, end = heat["use_start_at"], heat_ready_at(heat, request)
    if any(overlaps(start, end, r["use_start_at"], reservation_ready_at(r, request)) for r in ladle.get("reservations", [])):
        codes.append("reservation_overlap")
    return codes


def evaluate_rules(heat: dict[str, Any], ladle: dict[str, Any], state: dict[str, Any], request: dict[str, Any], policy: dict[str, Any], *, occupied: list[tuple[int, int]] | None = None) -> list[str]:
    """Return stable rejection codes for a proposed service at this state."""
    codes = static_rejections(heat, ladle, request, policy)
    profile = policy["profiles"].get(steel_key(heat["grade"]))
    if profile is None:
        return codes
    start, end = heat["use_start_at"], heat_ready_at(heat, request)
    ready = state["ready_at"]
    if start < ready and "not_ready" not in codes:
        codes.append("not_ready")
    if occupied and any(overlaps(start, end, s, e) for s, e in occupied):
        codes.append("assignment_overlap")
    condition_code, stopped = condition_at(heat, ladle, state, policy)
    parsed = parse_condition(condition_code)
    if policy["source"] == "confirmed" and parsed and state["repair_stage"] == 2 and state["thermal_cast_finish_at"] is None:
        codes.append("missing_thermal_history")
    if stopped:
        codes.append("thermal_condition_stopped")
    if parsed and (parsed[0] not in profile["allowed_condition_bands"] or parsed[1] not in profile["allowed_cold_steel_suffixes"]):
        codes.append("condition_mismatch")
    for field, maximum in policy["limits"].items():
        value = state.get(field)
        if value is not None and value + 1 > maximum:
            code = "exhausted_" + field
            if code not in codes:
                codes.append(code)
    usage = state.get("usage_count")
    is_new = usage == 0 or state["repair_stage"] == 0
    if is_new and not profile["allow_new_ladle"]:
        codes.append("new_ladle_forbidden")
    if heat.get("is_cast_first"):
        if condition_code not in policy["first_cast_allowed_condition_codes"]:
            codes.append("first_cast_condition_mismatch")
        if is_new:
            codes.append("first_cast_new_ladle_forbidden")
    allowed_previous = profile["allowed_previous_grades"]
    if allowed_previous is not None:
        if not state.get("history_known"):
            codes.append("missing_previous_steel")
        elif state.get("previous_grade") is not None and steel_key(state["previous_grade"]) not in allowed_previous:
            codes.append("previous_steel_mismatch")
    return list(dict.fromkeys(codes))


def advance_state(state: dict[str, Any], event: dict[str, Any], ladle: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(state)
    for field in COUNTER_FIELDS:
        if result[field] is not None:
            result[field] += 1
    result["repair_stage"] = min(2, result["repair_stage"] + 1)
    parsed = parse_condition(ladle.get("condition_code"))
    suffix = parsed[1] if parsed else "A"
    result["condition_code"] = f"27{suffix}" if result["repair_stage"] == 1 else f"20{suffix}"
    result["previous_grade"] = event.get("grade")
    result["history_known"] = event.get("grade") is not None
    result["last_cast_finish_at"] = event["cast_finish_at"]
    result["thermal_cast_finish_at"] = event["cast_finish_at"]
    result["thermal_source"] = "planned_cast_finish"
    result["ready_at"] = event.get("ready_at", event["cast_finish_at"] + event.get("turnaround_seconds", request["turnaround_seconds"]))
    return result


def preference_score(heat: dict[str, Any], ladle: dict[str, Any], state: dict[str, Any], policy: dict[str, Any]) -> int:
    """A disclosed demo preference, used only after assignment/count goals."""
    material_rank = policy["material_preference"].get(ladle.get("material_code"), 0)
    # Static snapshot temperature is deliberately not a simulated measurement.
    temperature = ladle.get("temperature_celsius")
    temperature_part = int(min(2000, max(0, temperature))) if temperature is not None else 0
    usage = state.get("usage_count") or 0
    nozzle = state.get("nozzle_used_heats") or 0
    return 10000 - material_rank * 2000 + temperature_part + min(usage, 1000) - min(nozzle, 1000)


def replay_plan(request: dict[str, Any], policy: dict[str, Any], assignments: dict[str, str], *, include_rejections: bool = True) -> dict[str, Any]:
    """Check all assignments and reconstruct selected-service state traces."""
    heats = {h["heat_id"]: h for h in request["heats"]}
    ladles = {l["ladle_id"]: l for l in request["ladles"]}
    if any(h not in heats or l not in ladles for h, l in assignments.items()):
        raise ReplayError("配包方案包含无效炉次或钢包")
    if any(assignments.get(h) != l for h, l in request.get("confirmed_bindings", {}).items()):
        raise ReplayError("配包方案未保留确认绑定")
    transitions: dict[str, Any] = {}
    preference = 0
    for ladle_id, ladle in ladles.items():
        chosen = [heats[h] for h, l in assignments.items() if l == ladle_id]
        fixed = list(ladle.get("reservations", []))
        intervals = [(h["use_start_at"], heat_ready_at(h, request)) for h in chosen]
        intervals.extend((r["use_start_at"], reservation_ready_at(r, request)) for r in fixed)
        intervals.sort()
        if any(overlaps(s1, e1, s2, e2) for (s1, e1), (s2, e2) in zip(intervals, intervals[1:])):
            raise ReplayError("配包方案钢包占用冲突")
        state = initial_state(ladle, request, policy)
        events = [(h["use_start_at"], 1, h) for h in chosen]
        events.extend((r["use_start_at"], 0, r) for r in fixed if r["use_start_at"] >= request["snapshot_at"])
        events.sort(key=lambda e: (e[0], e[1], e[2].get("heat_id", "")))
        for _, kind, event in events:
            if kind == 1:
                before = copy.deepcopy(state)
                before["condition_code"] = condition_at(event, ladle, state, policy)[0]
                failures = evaluate_rules(event, ladle, state, request, policy)
                if failures:
                    raise ReplayError("配包方案未通过工艺或状态复核")
                preference += preference_score(event, ladle, state, policy)
                after = advance_state(state, event, ladle, request)
                transitions[event["heat_id"]] = {
                    "before": before, "after": copy.deepcopy(after),
                    "rule_outcomes": [{"code": name, "passed": True, "applicable": (
                        any(o["operation"] in policy["argon_operations"] for o in event["operations"]) if name == "route"
                        else not policy["profiles"][steel_key(event["grade"])]["allow_new_ladle"] if name == "new_ladle"
                        else bool(event.get("is_cast_first")) if name == "first_cast"
                        else policy["profiles"][steel_key(event["grade"])]["allowed_previous_grades"] is not None if name == "previous_steel"
                        else True
                    )} for name in (
                        "availability", "steel_profile", "material", "condition", "lifetimes",
                        "route", "new_ladle", "first_cast", "previous_steel", "occupation",
                    )],
                    "selection_reasons": ["qualified_internal_rules", "nonoverlapping_turnaround_calendar"],
                }
                state = after
            else:
                state = advance_state(state, event, ladle, request)
    rejections: dict[str, Any] = {}
    if include_rejections:
        for heat in request["heats"]:
            rejected = []
            for ladle_id, ladle in ladles.items():
                state = initial_state(ladle, request, policy)
                earlier = [heats[h] for h, l in assignments.items()
                           if l == ladle_id and h != heat["heat_id"] and heats[h]["use_start_at"] < heat["use_start_at"]]
                prior_fixed = [r for r in ladle.get("reservations", [])
                               if request["snapshot_at"] <= r["use_start_at"] < heat["use_start_at"]]
                events = earlier + prior_fixed
                events.sort(key=lambda e: e["use_start_at"])
                for event in events:
                    state = advance_state(state, event, ladle, request)
                occupied = [(heats[h]["use_start_at"], heat_ready_at(heats[h], request))
                            for h, l in assignments.items() if l == ladle_id and h != heat["heat_id"]]
                codes = evaluate_rules(heat, ladle, state, request, policy, occupied=occupied)
                if codes:
                    rejected.append({"ladle_id": ladle_id, "codes": codes})
            rejections[heat["heat_id"]] = rejected
    return {
        "transitions": transitions, "rejections": rejections, "preference": preference,
        "validation": {"passed": True, "checks": ["candidate_identity", "confirmed_bindings", "occupation", "process_rules", "state_transitions"], "assigned_heats": len(assignments)},
    }
