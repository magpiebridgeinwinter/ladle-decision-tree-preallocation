"""Stateful fixed-plan CP-SAT allocation with independently verified output."""

from __future__ import annotations

import copy
import time
from typing import Any

from .errors import BindingConflictError, ReplayError, SearchIncompleteError, SolverUnavailableError
from .policy import COUNTER_FIELDS, validate_policy
from .rules import (
    advance_state, evaluate_rules, heat_ready_at, initial_state, overlaps,
    parse_condition, preference_score, replay_plan, reservation_ready_at,
    static_rejections, steel_key,
)


def _load_solver() -> Any:
    try:
        from ortools.sat.python import cp_model
    except ImportError as exc:
        raise SolverUnavailableError("钢包优化依赖未安装，请安装项目 requirements") from exc
    return cp_model


def _objective_key(assignments: dict[str, str], replay: dict[str, Any]) -> tuple[int, int, int]:
    return (-len(assignments), len(set(assignments.values())), -replay["preference"])


def _initial_plan(request: dict[str, Any], policy: dict[str, Any], pools: dict[str, list[str]]) -> dict[str, str] | None:
    """Protect scarce candidates and confirmed intervals in a fast initial plan."""
    ladles = {l["ladle_id"]: l for l in request["ladles"]}
    states = {key: initial_state(l, request, policy) for key, l in ladles.items()}
    fixed = request.get("confirmed_bindings", {})
    heat_by_id = {h["heat_id"]: h for h in request["heats"]}
    occupied = {key: [(r["use_start_at"], reservation_ready_at(r, request))
                      for r in l.get("reservations", [])] for key, l in ladles.items()}
    bound_intervals = {key: [(heat_by_id[h]["use_start_at"], heat_ready_at(heat_by_id[h], request), h)
                             for h, chosen in fixed.items() if chosen == key] for key in ladles}
    future_fixed = {key: sorted([r for r in l.get("reservations", []) if r["use_start_at"] >= request["snapshot_at"]],
                               key=lambda r: r["use_start_at"]) for key, l in ladles.items()}
    positions = dict.fromkeys(ladles, 0)
    unique_future = {key: [h for h in request["heats"] if pools[h["heat_id"]] == [key]] for key in ladles}
    heats = sorted(request["heats"], key=lambda h: (h["use_start_at"], len(pools[h["heat_id"]]), h["heat_id"]))
    assignments: dict[str, str] = {}
    for heat in heats:
        for key, events in future_fixed.items():
            while positions[key] < len(events) and events[positions[key]]["use_start_at"] <= heat["use_start_at"]:
                states[key] = advance_state(states[key], events[positions[key]], ladles[key], request)
                positions[key] += 1
        candidates = [fixed[heat["heat_id"]]] if heat["heat_id"] in fixed else pools[heat["heat_id"]]
        options = []
        for key in candidates:
            if key not in ladles or evaluate_rules(heat, ladles[key], states[key], request, policy, occupied=occupied[key]):
                continue
            start, end = heat["use_start_at"], heat_ready_at(heat, request)
            if any(h != heat["heat_id"] and overlaps(start, end, s, e) for s, e, h in bound_intervals[key]):
                continue
            pressure = sum(h["heat_id"] != heat["heat_id"] and h["use_start_at"] >= start
                           and overlaps(start, end, h["use_start_at"], heat_ready_at(h, request)) for h in unique_future[key])
            options.append((pressure, key not in assignments.values(), -preference_score(heat, ladles[key], states[key], policy), key))
        if options:
            key = min(options)[-1]
            assignments[heat["heat_id"]] = key
            occupied[key].append((heat["use_start_at"], heat_ready_at(heat, request)))
            states[key] = advance_state(states[key], heat, ladles[key], request)
    try:
        replay_plan(request, policy, assignments, include_rejections=False)
    except ReplayError:
        return None
    return assignments


def _build_model(request: dict[str, Any], policy: dict[str, Any], cp: Any, pools: dict[str, list[str]]) -> tuple[Any, dict[tuple[str, str], Any], Any, Any, Any]:
    """Model each candidate's selected services as a chronological state chain.

    Unlike a static matching model, each optional event carries counters,
    immediate previous steel, thermal clock, repair stage, and exact ready time.
    """
    model = cp.CpModel()
    variables: dict[tuple[str, str], Any] = {}
    for heat in request["heats"]:
        for ladle_id in pools[heat["heat_id"]]:
            variables[(heat["heat_id"], ladle_id)] = model.new_bool_var(f"assign_{heat['heat_id']}_{ladle_id}")
        model.add(sum(variables[(heat["heat_id"], l)] for l in pools[heat["heat_id"]]) <= 1)
    for heat_id, ladle_id in request.get("confirmed_bindings", {}).items():
        variable = variables.get((heat_id, ladle_id))
        model.add(variable == 1 if variable is not None else False)
    grade_keys = set(policy["profiles"])
    grade_keys.update(steel_key(h["grade"]) for h in request["heats"])
    for ladle in request["ladles"]:
        last = ladle.get("last_use") or {}
        if last.get("grade") is not None:
            grade_keys.add(steel_key(last["grade"]))
        grade_keys.update(steel_key(r["grade"]) for r in ladle.get("reservations", []) if r.get("grade") is not None)
    grade_keys.update(key for profile in policy["profiles"].values() for key in (profile["allowed_previous_grades"] or []))
    grade_index = {key: index + 2 for index, key in enumerate(sorted(grade_keys))}
    # 0 is unknown history; 1 is explicitly assumed clean history.
    used_vars, scores = [], []
    all_times = [request["snapshot_at"], request["plan_start_at"]]
    all_times.extend(h["cast_finish_at"] for h in request["heats"])
    all_times.extend(l["available_at"] for l in request["ladles"])
    all_times.extend(reservation_ready_at(r, request) for l in request["ladles"] for r in l.get("reservations", []))
    all_times.extend(r["cast_finish_at"] for l in request["ladles"] for r in l.get("reservations", []))
    all_times.extend((l.get("last_use") or {}).get("cast_finish_at", request["snapshot_at"]) or request["snapshot_at"] for l in request["ladles"])
    time_min = min(all_times) - policy["thermal_stop_after_seconds"] - 1
    time_max = max(all_times) + request["turnaround_seconds"] + 1
    for ladle in sorted(request["ladles"], key=lambda l: l["ladle_id"]):
        ladle_id = ladle["ladle_id"]
        candidate_heats = [h for h in request["heats"] if (h["heat_id"], ladle_id) in variables]
        selected_vars = [variables[(h["heat_id"], ladle_id)] for h in candidate_heats]
        used = model.new_bool_var(f"used_{ladle_id}")
        model.add_max_equality(used, selected_vars or [0])
        used_vars.append(used)
        if not candidate_heats:
            continue
        initial = initial_state(ladle, request, policy)
        intervals = []
        for heat in candidate_heats:
            x = variables[(heat["heat_id"], ladle_id)]
            start = heat["use_start_at"]
            end = heat_ready_at(heat, request)
            intervals.append(model.new_optional_interval_var(start, end - start, end, x, f"use_{heat['heat_id']}_{ladle_id}"))
        for number, reservation in enumerate(ladle.get("reservations", [])):
            start = reservation["use_start_at"]
            end = reservation_ready_at(reservation, request)
            intervals.append(model.new_interval_var(start, end - start, end, f"reservation_{ladle_id}_{number}"))
        model.add_no_overlap(intervals)
        events = [(h["use_start_at"], 1, h, variables[(h["heat_id"], ladle_id)]) for h in candidate_heats]
        events.extend((r["use_start_at"], 0, r, None) for r in ladle.get("reservations", []) if r["use_start_at"] >= request["snapshot_at"])
        events.sort(key=lambda e: (e[0], e[1], e[2].get("heat_id", "")))
        tracked_fields = tuple(dict.fromkeys((*policy["limits"], "usage_count", "nozzle_used_heats")))
        counts = {field: model.new_constant(min(initial.get(field) or 0, 1000) if field not in policy["limits"] else initial.get(field) or 0)
                  for field in tracked_fields}
        known = {field: initial.get(field) is not None for field in tracked_fields}
        initial_previous = (grade_index[steel_key(initial["previous_grade"])] if initial["previous_grade"] is not None
                            else 1 if initial["history_known"] else 0)
        previous = model.new_constant(initial_previous)
        thermal = model.new_constant(initial["thermal_cast_finish_at"] if initial["thermal_cast_finish_at"] is not None else time_min)
        has_thermal = model.new_constant(int(initial["thermal_cast_finish_at"] is not None))
        ready = model.new_constant(initial["ready_at"])
        repair = model.new_constant(initial["repair_stage"])
        initial_band, suffix = parse_condition(ladle["condition_code"])  # statically qualified
        for step, (_, kind, event, optional) in enumerate(events):
            presence = optional if kind else model.new_constant(1)
            tag = f"{ladle_id}_{step}"
            if kind:
                profile = policy["profiles"][steel_key(event["grade"])]
                model.add(ready <= event["use_start_at"]).only_enforce_if(presence)
                for field, maximum in policy["limits"].items():
                    model.add(counts[field] + 1 <= maximum).only_enforce_if(presence)
                elapsed = model.new_int_var(-time_max + time_min, time_max - time_min, f"thermal_elapsed_{tag}")
                model.add(elapsed == event["tap_finish_at"] - thermal)
                late = []
                for index, boundary in enumerate(policy["thermal_boundaries_seconds"]):
                    value = model.new_bool_var(f"late_{tag}_{index}")
                    model.add(elapsed > boundary).only_enforce_if(value)
                    model.add(elapsed <= boundary).only_enforce_if(value.Not())
                    late.append(value)
                thermal_band = model.new_int_var(0, 6, f"thermal_band_{tag}")
                model.add(thermal_band == sum(late))
                stage_flags = []
                for stage in range(3):
                    flag = model.new_bool_var(f"repair_is_{tag}_{stage}")
                    model.add(repair == stage).only_enforce_if(flag)
                    model.add(repair != stage).only_enforce_if(flag.Not())
                    stage_flags.append(flag)
                code = model.new_int_var(0, 9, f"condition_{tag}")
                model.add(code == initial_band).only_enforce_if(stage_flags[0])
                model.add(code == 7).only_enforce_if(stage_flags[1])
                model.add(code == initial_band).only_enforce_if([stage_flags[2], has_thermal.Not()])
                model.add(code == thermal_band).only_enforce_if([stage_flags[2], has_thermal])
                if policy["source"] == "confirmed":
                    model.add(has_thermal == 1).only_enforce_if([presence, stage_flags[2]])
                model.add(elapsed <= policy["thermal_stop_after_seconds"]).only_enforce_if([presence, stage_flags[2], has_thermal])
                model.add_allowed_assignments([code], [(band,) for band in profile["allowed_condition_bands"]]).only_enforce_if(presence)
                if not profile["allow_new_ladle"] or event.get("is_cast_first"):
                    model.add(counts["usage_count"] >= 1).only_enforce_if(presence)
                    model.add(repair >= 1).only_enforce_if(presence)
                if event.get("is_cast_first"):
                    first_bands = [int(c[1]) for c in policy["first_cast_allowed_condition_codes"] if c[2] == suffix]
                    if first_bands:
                        model.add_allowed_assignments([code], [(band,) for band in first_bands]).only_enforce_if(presence)
                    else:
                        model.add(presence == 0)
                allowed_previous = profile["allowed_previous_grades"]
                if allowed_previous is not None:
                    allowed = [1] + [grade_index[key] for key in allowed_previous]
                    model.add_allowed_assignments([previous], [(value,) for value in allowed]).only_enforce_if(presence)
                capped_usage = model.new_int_var(0, 1000, f"capped_usage_{tag}")
                capped_nozzle = model.new_int_var(0, 1000, f"capped_nozzle_{tag}")
                model.add_min_equality(capped_usage, [counts["usage_count"], 1000])
                model.add_min_equality(capped_nozzle, [counts["nozzle_used_heats"], 1000])
                temp = ladle.get("temperature_celsius")
                static_score = 10000 - policy["material_preference"].get(ladle.get("material_code"), 0) * 2000
                static_score += int(min(2000, max(0, temp))) if temp is not None else 0
                # An absent event scores zero; selected scores are the static
                # material/temperature term plus two independently capped
                # usage counters. Derive bounds rather than restricting
                # otherwise valid configurable material ranking weights.
                score = model.new_int_var(min(0, static_score - 1000), max(0, static_score + 1000), f"preference_{tag}")
                model.add(score == static_score + capped_usage - capped_nozzle).only_enforce_if(presence)
                model.add(score == 0).only_enforce_if(presence.Not())
                scores.append(score)
            after_counts = {}
            for field in tracked_fields:
                # Missing non-required attributes remain unknown in replay;
                # they must not accidentally acquire synthetic usage counts.
                initial_count = min(initial.get(field) or 0, 1000) if field not in policy["limits"] else initial.get(field) or 0
                after = model.new_int_var(0, initial_count + len(events), f"{field}_{tag}")
                model.add(after == counts[field] + (presence if known[field] else 0))
                after_counts[field] = after
            new_previous = model.new_int_var(0, len(grade_index) + 1, f"previous_{tag}")
            grade_value = grade_index[steel_key(event["grade"])] if event.get("grade") is not None else 0
            new_thermal = model.new_int_var(time_min, time_max, f"thermal_{tag}")
            new_ready = model.new_int_var(time_min, time_max, f"ready_{tag}")
            new_has = model.new_bool_var(f"has_thermal_{tag}")
            new_repair = model.new_int_var(0, 2, f"repair_{tag}")
            model.add(new_previous == grade_value).only_enforce_if(presence)
            model.add(new_previous == previous).only_enforce_if(presence.Not())
            model.add(new_thermal == event["cast_finish_at"]).only_enforce_if(presence)
            model.add(new_thermal == thermal).only_enforce_if(presence.Not())
            event_ready = heat_ready_at(event, request) if kind else reservation_ready_at(event, request)
            model.add(new_ready == event_ready).only_enforce_if(presence)
            model.add(new_ready == ready).only_enforce_if(presence.Not())
            model.add_max_equality(new_has, [has_thermal, presence])
            model.add_min_equality(new_repair, [repair + presence, 2])
            counts, previous, thermal, has_thermal, ready, repair = after_counts, new_previous, new_thermal, new_has, new_ready, new_repair
    assigned_expr = sum(variables.values())
    used_expr = sum(used_vars)
    preference_expr = sum(scores)
    return model, variables, assigned_expr, used_expr, preference_expr


def build_plan(request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Return a verified proposal and explicit lexicographic proof metadata."""
    policy = validate_policy(policy)
    cp = _load_solver()
    started = time.perf_counter()
    pools = {h["heat_id"]: [l["ladle_id"] for l in sorted(request["ladles"], key=lambda l: l["ladle_id"])
                            if not static_rejections(h, l, request, policy)] for h in request["heats"]}
    seed = _initial_plan(request, policy, pools)
    best = seed
    best_replay = replay_plan(request, policy, seed, include_rejections=False) if seed is not None else None
    model, variables, assigned_expr, used_expr, preference_expr = _build_model(request, policy, cp, pools)
    validation_error = model.validate()
    if validation_error:
        raise ReplayError("钢包优化模型未通过内部校验")
    options = {**policy["solver_defaults"], **request.get("solver_options", {})}
    deterministic_used = 0.0
    phases = []
    preceding_proven = True
    for phase, expression, maximize in (("assigned_heats", assigned_expr, True), ("distinct_ladles", used_expr, False), ("preference", preference_expr, True)):
        remaining = options["time_limit_seconds"] - (time.perf_counter() - started)
        deterministic_remaining = options["max_deterministic_time"] - deterministic_used
        if remaining <= 0 or deterministic_remaining <= 0:
            phases.append({"objective": phase, "status": "NOT_RUN", "proven": False, "value": None, "best_bound": None})
            preceding_proven = False
            continue
        if phase != "assigned_heats" and best is None:
            phases.append({"objective": phase, "status": "NOT_RUN", "proven": False, "value": None, "best_bound": None})
            preceding_proven = False
            continue
        if phase == "distinct_ladles":
            model.add(assigned_expr == len(best))
        elif phase == "preference":
            model.add(used_expr == len(set(best.values())))
        model.clear_hints()
        if best is not None:
            for (heat_id, ladle_id), variable in variables.items():
                model.add_hint(variable, int(best.get(heat_id) == ladle_id))
        model.maximize(expression) if maximize else model.minimize(expression)
        solver = cp.CpSolver()
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        solver.parameters.max_time_in_seconds = max(.000001, remaining)
        solver.parameters.max_deterministic_time = max(.000001, deterministic_remaining)
        status = solver.solve(model)
        status_name = solver.status_name(status)
        deterministic_used += solver.response_proto.deterministic_time
        if status == cp.MODEL_INVALID:
            raise ReplayError("钢包优化模型求解失败")
        if status == cp.INFEASIBLE:
            if best is not None:
                raise ReplayError("优化模型与独立可行方案不一致")
            if request.get("confirmed_bindings"):
                raise BindingConflictError("确认绑定与工艺、占用或状态约束冲突")
            raise ReplayError("钢包优化模型意外不可行")
        found = status in {cp.OPTIMAL, cp.FEASIBLE}
        phase_proven = status == cp.OPTIMAL and preceding_proven
        value = None
        bound = None
        if found:
            candidate = {heat_id: ladle_id for (heat_id, ladle_id), variable in variables.items() if solver.value(variable)}
            candidate_replay = replay_plan(request, policy, candidate, include_rejections=False)
            if best is None or _objective_key(candidate, candidate_replay) <= _objective_key(best, best_replay):
                best, best_replay = candidate, candidate_replay
            elif status == cp.OPTIMAL:
                # An independently feasible better plan would expose a model
                # encoding bug; never hide it by returning an incorrect proof.
                if phase == "assigned_heats" and len(best) > len(candidate):
                    raise ReplayError("优化炉次数证明与独立复核不一致")
                if phase == "distinct_ladles" and len(set(best.values())) < len(set(candidate.values())):
                    raise ReplayError("优化钢包数证明与独立复核不一致")
                if phase == "preference" and best_replay["preference"] > candidate_replay["preference"]:
                    raise ReplayError("优化偏好证明与独立复核不一致")
            value = len(best) if phase == "assigned_heats" else len(set(best.values())) if phase == "distinct_ladles" else best_replay["preference"]
            bound = solver.best_objective_bound
        phases.append({"objective": phase, "status": status_name, "proven": phase_proven, "value": value, "best_bound": bound})
        preceding_proven = phase_proven
    if best is None:
        raise SearchIncompleteError("求解预算内未获得保留全部确认绑定的可验证方案，请增加求解预算")
    final = replay_plan(request, policy, best)
    assumptions = list(policy["assumptions"]) if policy["source"] == "assumed" else []
    for ladle in request["ladles"]:
        ladle_id = ladle["ladle_id"]
        if ladle.get("data_source", "provided") == "assumed":
            assumptions.append("candidate_attributes_assumed:" + ladle_id)
        state = initial_state(ladle, request, policy)
        if ladle.get("history_assumption") == "clean":
            assumptions.append("initial_history_assumed_clean:" + ladle_id)
        if state["thermal_source"] == "estimated_from_snapshot_condition":
            assumptions.append("initial_thermal_clock_estimated:" + ladle_id)
    assumptions.extend("casting_finish_estimated:" + h["heat_id"] for h in request["heats"] if h.get("cast_finish_source") == "estimated")
    all_proven = len(phases) == 3 and all(p["proven"] for p in phases)
    return {
        "assignments": dict(best), "transitions": final["transitions"], "rejections": final["rejections"],
        "objectives": {"assigned_heats": len(best), "distinct_ladles": len(set(best.values())), "preference": final["preference"]},
        "optimization_status": "optimal" if all_proven else "feasible",
        "solver": {"algorithm": "cp_sat", "phase_statuses": phases,
                   "fallback_used": not any(p["status"] in {"FEASIBLE", "OPTIMAL"} for p in phases),
                   "elapsed_seconds": round(time.perf_counter() - started, 6), "deterministic_time": deterministic_used,
                   "complete_allocation_proven_impossible": bool(phases and phases[0]["proven"] and len(best) < len(request["heats"]))},
        "assumptions": list(dict.fromkeys(assumptions)), "validation": final["validation"],
    }
