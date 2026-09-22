"""Build deterministic decision-tree and Codex fallback records from real data."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from ladle_preallocation.decision_tree.constraints import expected_arrival
from ladle_preallocation.disturbance.catalog import (
    ARGON_STATION_UNAVAILABLE,
    CASTER_DELAY,
    COMPOUND_DISTURBANCE,
    CONVERTER_DELAY,
    CRANE_OFFLINE,
    CRANE_LOAD_RESTRICTED,
    CRANE_RANGE_RESTRICTED,
    CRANE_SPEED_DEGRADED,
    CRANE_TELEMETRY_STALE,
    DISTURBANCE_CATALOG,
    FACILITY_UNAVAILABLE,
    LADLE_DAMAGE,
    LADLE_GRADE_CONFLICT,
    LADLE_LINING_ALARM,
    LADLE_OVER_AGE,
    LADLE_UNAVAILABLE,
    PRIORITY_ESCALATION,
    REFINING_ROUTE_CHANGE,
    SCHEDULE_DEVIATION,
    TRANSPORT_CORRIDOR_BLOCKED,
    URGENT_HEAT_INSERTED,
    catalog_rows,
)
from ladle_preallocation.disturbance.injector import SAFETY_BUFFER_SECONDS, DisturbanceSpec, DisturbedScenario, inject_disturbance
from ladle_preallocation.offline_scenarios.validation import ScenarioValidationPolicy, ScenarioValidator
from ladle_preallocation.response import TieredResponseController
from ladle_preallocation.real_data.audit import load_location_aware_audit


SOURCE_AUDIT = Path("outputs/real_data_location_aware/decision_tree_audit.json")
SOURCE_PLAN = Path("data/PLAN(1)_预配包输入.xlsx")
SOURCE_CRANE = Path("data/CRANE.xlsx")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLEX_HEAT_ID = "AQ0640E1-300703"
TIGHT_HEAT_ID = "DU3851D1-300667"
SOURCE_LADLE_ID = "ST08"
FLEX_LADLE_ID = "ST07"
TIGHT_LADLE_ID = "ST38"
SOURCE_CRANE_ID = "1520"
NEAR_CRANE_ID = "2500"
FAR_CRANE_ID = "3170"
COMPRESSED_WINDOW_SECONDS = 10.0


def _offline_clock() -> float:
    """Stable clock for evidence builds; host runtime must not affect JSON."""
    return 0.0


def _indexes(source: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    inputs = source["scheduling_inputs"]
    routes: dict[str, dict[str, Any]] = {}
    for heat in inputs["heats"]:
        route = str(heat.get("refining_route") or "").strip()
        if route and route not in routes:
            routes[route] = deepcopy(heat)
    return {
        "heat": {str(item["heat_id"]): deepcopy(item) for item in inputs["heats"]},
        "ladle": {str(item["ladle_id"]): deepcopy(item) for item in inputs["ladles"]},
        "crane": {str(item["crane_id"]): deepcopy(item) for item in inputs["cranes"]},
        "assignment": {str(item["heat_id"]): deepcopy(item) for item in source["assignments"]},
        "route": routes,
    }


def _require(indexes: dict[str, dict[str, dict[str, Any]]]) -> None:
    required = {
        "heat": (FLEX_HEAT_ID, TIGHT_HEAT_ID),
        "ladle": (SOURCE_LADLE_ID, FLEX_LADLE_ID, TIGHT_LADLE_ID),
        "crane": (SOURCE_CRANE_ID, NEAR_CRANE_ID, FAR_CRANE_ID),
        "assignment": (FLEX_HEAT_ID, TIGHT_HEAT_ID),
        "route": ("A1", "A2", "R0", "R1"),
    }
    missing = [f"{kind}:{identifier}" for kind, identifiers in required.items() for identifier in identifiers if identifier not in indexes[kind]]
    if missing:
        raise RuntimeError("source audit is missing required real records: " + ", ".join(missing))


def _result_payload(result: Any, modeled_elapsed_seconds: float, modeled_remaining_budget_seconds: float | None = None) -> dict[str, Any]:
    metrics = deepcopy(result.metrics)
    if "decision_seconds" in metrics:
        metrics["decision_seconds"] = modeled_elapsed_seconds
    return {
        "path": result.path.value,
        "success": bool(result.success),
        "num_assigned": result.num_assigned,
        # Persist the deterministic demo clock, not host-dependent wall time.
        "elapsed_seconds": modeled_elapsed_seconds,
        "remaining_budget_seconds": modeled_remaining_budget_seconds,
        "reason": result.reason,
        "assignments": [dict(item) for item in result.assignments],
        "validation_feedback": deepcopy(result.validation_feedback),
        "metrics": metrics,
    }


class SavedCodexProposalAdapter:
    """Execute a reviewed Codex proposal without claiming an external API call."""

    def __init__(self, proposal: list[dict[str, Any]]) -> None:
        self.proposal = deepcopy(proposal)
        self.called = False
        self.failure_context: dict[str, Any] = {}
        self.remaining_budget_seconds: float | None = None

    def __call__(self, _heats: list[dict[str, Any]], _ladles: list[dict[str, Any]], _cranes: list[dict[str, Any]], **kwargs: Any) -> tuple[bool, list[dict[str, Any]]]:
        self.called = True
        self.failure_context = deepcopy(kwargs.get("failure_context") or {})
        self.remaining_budget_seconds = kwargs.get("remaining_budget_seconds")
        return True, deepcopy(self.proposal)


def _source_assets(indexes: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    assets = []
    for identifier, role in ((FLEX_HEAT_ID, "affected_heat"), (TIGHT_HEAT_ID, "affected_heat")):
        assets.append({"asset_type": "heat", "asset_id": identifier, "role": role, "source_record": indexes["heat"][identifier]})
    for identifier, role in ((SOURCE_LADLE_ID, "disturbed_original"), (FLEX_LADLE_ID, "replacement_candidate"), (TIGHT_LADLE_ID, "replacement_candidate")):
        assets.append({"asset_type": "ladle", "asset_id": identifier, "role": role, "source_record": indexes["ladle"][identifier]})
    for identifier, role in ((SOURCE_CRANE_ID, "disturbed_original"), (NEAR_CRANE_ID, "replacement_candidate"), (FAR_CRANE_ID, "replacement_candidate")):
        assets.append({"asset_type": "crane", "asset_id": identifier, "role": role, "source_record": indexes["crane"][identifier]})
    for identifier, role in (("A2", "baseline_route"), ("R0", "baseline_route"), ("A1", "audited_alternate_route"), ("R1", "audited_alternate_route")):
        assets.append({"asset_type": "route", "asset_id": identifier, "role": role, "source_record": indexes["route"][identifier]})
    return assets


def _portable_source_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _source_references(source_audit: str) -> dict[str, str]:
    return {
        "plan": SOURCE_PLAN.as_posix(),
        "crane": SOURCE_CRANE.as_posix(),
        "audit": source_audit,
        "location": source_audit,
    }


def _timeline(occurred_at: float, include_llm: bool) -> list[dict[str, Any]]:
    rows = [
        {"sequence": 1, "event_type": "preallocation_ready", "offset_seconds": -180.0, "occurred_at": occurred_at - 180.0, "payload": {"algorithm": "decision_tree"}},
        {"sequence": 2, "event_type": "disturbance_detected", "offset_seconds": 0.0, "occurred_at": occurred_at, "payload": {}},
        {"sequence": 3, "event_type": "local_window_opened", "offset_seconds": 2.0, "occurred_at": occurred_at + 2.0, "payload": {"window_minutes": 20}},
        {"sequence": 4, "event_type": "decision_tree_completed", "offset_seconds": 8.0, "occurred_at": occurred_at + 8.0, "payload": {}},
    ]
    if include_llm:
        rows.extend([
            {"sequence": 5, "event_type": "llm_context_built", "offset_seconds": 14.0, "occurred_at": occurred_at + 14.0, "payload": {}},
            {"sequence": 6, "event_type": "codex_proposal_loaded", "offset_seconds": 31.0, "occurred_at": occurred_at + 31.0, "payload": {"external_api_called": False}},
            {"sequence": 7, "event_type": "hard_constraints_validated", "offset_seconds": 43.0, "occurred_at": occurred_at + 43.0, "payload": {}},
            {"sequence": 8, "event_type": "dispatch_released", "offset_seconds": 49.0, "occurred_at": occurred_at + 49.0, "payload": {}},
        ])
    else:
        rows.append({"sequence": 5, "event_type": "dispatch_released", "offset_seconds": 12.0, "occurred_at": occurred_at + 12.0, "payload": {}})
    return rows


def _ordinary_control(source: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]], source_audit: str) -> dict[str, Any]:
    heats = [deepcopy(indexes["heat"][FLEX_HEAT_ID]), deepcopy(indexes["heat"][TIGHT_HEAT_ID])]
    ladles = [deepcopy(item) for item in source["scheduling_inputs"]["ladles"]]
    cranes = [deepcopy(item) for item in source["scheduling_inputs"]["cranes"]]
    baseline = [deepcopy(indexes["assignment"][FLEX_HEAT_ID]), deepcopy(indexes["assignment"][TIGHT_HEAT_ID])]
    occurred_at = min(float(item["pour_at"]) for item in heats) - 500.0
    scenario = inject_disturbance(
        DisturbanceSpec("crane_offline", SOURCE_CRANE_ID, "普通行车离线局部重排", occurred_at, {"affected_heat_ids": [FLEX_HEAT_ID, TIGHT_HEAT_ID], "window_minutes": 20}),
        heats,
        ladles,
        cranes,
        baseline,
    )
    comparison = TieredResponseController(clock=_offline_clock).run_three_way(scenario, "decision_tree_control_001")
    if not comparison.decision_tree.success or comparison.llm_react is not None:
        raise RuntimeError("ordinary control must finish with decision tree only")
    dt = _result_payload(comparison.decision_tree, 6.0)
    return {
        "scenario_id": "decision_tree_control_001",
        "category": "decision_tree_control",
        "disturbance_kind": "crane_offline",
        "disturbance_group": "equipment",
        "title": "普通扰动：决策树完成局部重排",
        "description": "原行车 1520 离线后，仅重排真实炉次 AQ0640E1-300703 与 DU3851D1-300667；剩余真实资源足够，未调用 LLM。",
        "evidence_type": "controlled_real_snapshot_decision_tree",
        "event_time": occurred_at,
        "window_start": occurred_at,
        "window_end": occurred_at + 1200.0,
        "seed": 1001,
        "source": _source_references(source_audit),
        "event": scenario.audit["event"],
        "events": _timeline(occurred_at, False),
        "assets": _source_assets(indexes),
        "inputs": {"heats": scenario.heats_needing_reallocation, "ladles": scenario.remaining_ladles, "cranes": scenario.remaining_cranes, "baseline_assignments": baseline},
        "responses": {"decision_tree": dt, "llm": None},
        "validations": {
            "decision_tree": [
                {"check_code": "decision_tree_attempted_first", "passed": True, "details": {}},
                {"check_code": "complete_assignment_set", "passed": dt["num_assigned"] == len(heats), "details": {"assigned": dt["num_assigned"], "total": len(heats)}},
                {"check_code": "llm_not_attempted", "passed": True, "details": {}},
            ]
        },
        "audit": {
            "evidence_boundary": "真实资产和快照来自 PLAN(1)/CRANE；行车离线为受控注入，不是现场事故日志。",
            "llm_attempted": False,
            "external_api_called": False,
            "timing_model": "deterministic_demo_timeline_not_wall_clock",
            "location_baseline": {
                "audit_path": source_audit,
                "location_dictionary": source["location"]["path"],
                "mapping": deepcopy(source["location"]["mapping"]),
                "algorithm_version": source["tree_version"],
            },
            "impact_scope": scenario.audit.get("impact_scope", {}),
            "event_state_deltas": scenario.audit.get("event_state_deltas", []),
            "earliest_pour_at": scenario.earliest_pour_at,
            "remaining_budget_seconds": scenario.remaining_budget_seconds,
        },
    }


def _route_policy(kind: str) -> ScenarioValidationPolicy:
    if kind == FACILITY_UNAVAILABLE:
        return ScenarioValidationPolicy({FLEX_HEAT_ID: ("A1",), TIGHT_HEAT_ID: ("R0",)}, ("A2",), True, True)
    if kind == ARGON_STATION_UNAVAILABLE:
        return ScenarioValidationPolicy({FLEX_HEAT_ID: ("A2",), TIGHT_HEAT_ID: ("R1",)}, ("R0",), True, True)
    if kind in {REFINING_ROUTE_CHANGE, COMPOUND_DISTURBANCE}:
        return ScenarioValidationPolicy({FLEX_HEAT_ID: ("A1",), TIGHT_HEAT_ID: ("R1",)}, ("A2", "R0"), True, True)
    return ScenarioValidationPolicy(distinct_cranes=True, distinct_ladles=True)


def _apply_event_state(
    kind: str,
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    indexes: dict[str, dict[str, dict[str, Any]]],
    policy: ScenarioValidationPolicy,
) -> list[dict[str, Any]]:
    """Apply the event to scheduler inputs and return an auditable state delta."""
    deltas: list[dict[str, Any]] = []
    if kind in {CRANE_OFFLINE, CRANE_TELEMETRY_STALE, COMPOUND_DISTURBANCE}:
        before = deepcopy(indexes["crane"][SOURCE_CRANE_ID])
        after = {
            **deepcopy(before),
            "candidate_status": "excluded",
            "controlled_reason": "telemetry_stale" if kind == CRANE_TELEMETRY_STALE else "crane_offline",
        }
        deltas.append({"asset_type": "crane", "asset_id": SOURCE_CRANE_ID, "before": before, "after": after})
    if kind in {CRANE_SPEED_DEGRADED, CRANE_LOAD_RESTRICTED, CRANE_RANGE_RESTRICTED, TRANSPORT_CORRIDOR_BLOCKED}:
        crane = deepcopy(indexes["crane"][SOURCE_CRANE_ID])
        before = deepcopy(crane)
        if kind == CRANE_SPEED_DEGRADED:
            crane["speed_mps"] = 20.0
        elif kind == CRANE_LOAD_RESTRICTED:
            crane["max_load_tonnes"] = 120.0
        elif kind == CRANE_RANGE_RESTRICTED:
            crane["limit_0_m"], crane["limit_1_m"] = 10_000.0, 20_000.0
        else:
            crane["active_positions"] = [0.0, 40_445.0]
            crane["safe_distance_m"] = 1_000.0
        cranes.append(crane)
        deltas.append({"asset_type": "crane", "asset_id": SOURCE_CRANE_ID, "before": before, "after": crane})
    if kind in {LADLE_UNAVAILABLE, LADLE_DAMAGE, LADLE_LINING_ALARM, LADLE_OVER_AGE, LADLE_GRADE_CONFLICT, COMPOUND_DISTURBANCE}:
        ladle = deepcopy(indexes["ladle"][SOURCE_LADLE_ID])
        before = deepcopy(ladle)
        if kind == LADLE_UNAVAILABLE:
            ladle["state"] = "unavailable"
        elif kind == LADLE_DAMAGE or kind == COMPOUND_DISTURBANCE:
            ladle["state"] = "scrapped"
        elif kind == LADLE_LINING_ALARM:
            ladle["state"] = "maintenance"
            ladle["lining_alarm"] = True
        elif kind == LADLE_OVER_AGE:
            ladle["age_seconds"], ladle["max_age_seconds"] = 7_200.0, 3_600.0
            for heat in heats:
                heat["enforce_ladle_age"] = True
        else:
            ladle["grade"] = "CONTROLLED_CONFLICT"
        ladles.append(ladle)
        deltas.append({"asset_type": "ladle", "asset_id": SOURCE_LADLE_ID, "before": before, "after": ladle})
    if kind == SCHEDULE_DEVIATION:
        for heat in heats:
            before = {key: heat.get(key) for key in ("window_start", "window_end", "pour_at", "blow_at")}
            for key in before:
                if heat.get(key) is not None:
                    heat[key] = float(heat[key]) + 120.0
            deltas.append({"asset_type": "heat", "asset_id": heat["heat_id"], "before": before, "after": {key: heat.get(key) for key in before}})
    elif kind == CONVERTER_DELAY:
        heat = next(item for item in heats if item["heat_id"] == TIGHT_HEAT_ID)
        before = {key: heat.get(key) for key in ("window_start", "window_end", "pour_at", "blow_at")}
        for key in before:
            if heat.get(key) is not None:
                heat[key] = float(heat[key]) + 240.0
        deltas.append({"asset_type": "heat", "asset_id": TIGHT_HEAT_ID, "before": before, "after": {key: heat.get(key) for key in before}})
    elif kind == CASTER_DELAY:
        heat = next(item for item in heats if item["heat_id"] == FLEX_HEAT_ID)
        before = {"pour_at": heat.get("pour_at"), "window_end": heat.get("window_end")}
        heat["pour_at"] = float(heat["pour_at"]) + 180.0
        heat["window_end"] = float(heat["window_end"]) + 180.0
        deltas.append({"asset_type": "heat", "asset_id": FLEX_HEAT_ID, "before": before, "after": {"pour_at": heat["pour_at"], "window_end": heat["window_end"]}})
    elif kind == URGENT_HEAT_INSERTED:
        heat = next(item for item in heats if item["heat_id"] == FLEX_HEAT_ID)
        before = {"priority": heat.get("priority"), "urgent_inserted": heat.get("urgent_inserted")}
        heat["priority"], heat["urgent_inserted"] = 100.0, True
        deltas.append({"asset_type": "heat", "asset_id": FLEX_HEAT_ID, "before": before, "after": {"priority": 100.0, "urgent_inserted": True}})
    elif kind == PRIORITY_ESCALATION:
        heat = next(item for item in heats if item["heat_id"] == FLEX_HEAT_ID)
        before = {"priority": heat.get("priority")}
        heat["priority"] = 50.0
        deltas.append({"asset_type": "heat", "asset_id": FLEX_HEAT_ID, "before": before, "after": {"priority": 50.0}})
    if kind in {FACILITY_UNAVAILABLE, ARGON_STATION_UNAVAILABLE, REFINING_ROUTE_CHANGE, COMPOUND_DISTURBANCE}:
        for heat_id, allowed_routes in sorted(policy.allowed_routes_by_heat.items()):
            heat = next(item for item in heats if str(item["heat_id"]) == heat_id)
            original_route = str(heat.get("refining_route") or "").strip()
            deltas.append({
                "asset_type": "route_policy",
                "asset_id": heat_id,
                "before": {"refining_route": original_route, "allowed_routes": [original_route]},
                "after": {"refining_route": original_route, "allowed_routes": list(allowed_routes), "blocked_route_tokens": list(policy.blocked_route_tokens)},
            })
    return deltas


def _stress_record(
    kind: str,
    ordinal: int,
    indexes: dict[str, dict[str, dict[str, Any]]],
    source_audit: str,
    location_metadata: dict[str, Any],
) -> dict[str, Any]:
    definition = DISTURBANCE_CATALOG[kind]
    source_heats = [deepcopy(indexes["heat"][FLEX_HEAT_ID]), deepcopy(indexes["heat"][TIGHT_HEAT_ID])]
    heats = deepcopy(source_heats)
    flex, tight = heats
    flex["priority"] = 10.0
    flex["enforce_grade"] = True
    tight["enforce_grade"] = True
    tight["window_end"] = float(tight["window_start"]) + COMPRESSED_WINDOW_SECONDS

    ladles = [deepcopy(indexes["ladle"][FLEX_LADLE_ID]), deepcopy(indexes["ladle"][TIGHT_LADLE_ID])]
    cranes = [deepcopy(indexes["crane"][NEAR_CRANE_ID]), deepcopy(indexes["crane"][FAR_CRANE_ID])]
    by_crane = {str(item["crane_id"]): item for item in cranes}
    by_ladle = {str(item["ladle_id"]): item for item in ladles}
    by_ladle[FLEX_LADLE_ID]["position_m"] = float(by_crane[FAR_CRANE_ID]["position_m"])
    by_ladle[TIGHT_LADLE_ID]["position_m"] = float(by_crane[NEAR_CRANE_ID]["position_m"])

    policy = _route_policy(kind)
    event_state_deltas = _apply_event_state(kind, heats, ladles, cranes, indexes, policy)
    by_crane = {str(item["crane_id"]): item for item in cranes}
    by_ladle = {str(item["ladle_id"]): item for item in ladles}
    routes = {
        FLEX_HEAT_ID: "A1" if kind in {FACILITY_UNAVAILABLE, REFINING_ROUTE_CHANGE, COMPOUND_DISTURBANCE} else str(flex.get("refining_route") or "").strip(),
        TIGHT_HEAT_ID: "R1" if kind in {ARGON_STATION_UNAVAILABLE, REFINING_ROUTE_CHANGE, COMPOUND_DISTURBANCE} else str(tight.get("refining_route") or "").strip(),
    }
    proposal = [
        {"heat_id": FLEX_HEAT_ID, "ladle_id": FLEX_LADLE_ID, "crane_id": FAR_CRANE_ID, "refining_route": routes[FLEX_HEAT_ID], "expected_arrival_seconds": expected_arrival(flex, by_ladle[FLEX_LADLE_ID], by_crane[FAR_CRANE_ID]), "reason": "Codex 全局方案：远端同等级钢包交给原位行车 3170，保留近端资源给紧窗口炉次。"},
        {"heat_id": TIGHT_HEAT_ID, "ladle_id": TIGHT_LADLE_ID, "crane_id": NEAR_CRANE_ID, "refining_route": routes[TIGHT_HEAT_ID], "expected_arrival_seconds": expected_arrival(tight, by_ladle[TIGHT_LADLE_ID], by_crane[NEAR_CRANE_ID]), "reason": "Codex 全局方案：近端替代钢包 ST38 与行车 2500 组合，满足压缩后的十秒运输窗口。"},
    ]
    earliest = min(float(item["pour_at"]) for item in heats)
    occurred_at = earliest - 500.0
    budget = earliest - occurred_at - SAFETY_BUFFER_SECONDS
    resource_id = SOURCE_CRANE_ID if definition.group in {"equipment", "logistics_safety", "data_control"} else SOURCE_LADLE_ID if definition.group == "ladle" else str(source_heats[0].get("refining_route") or "").strip() if definition.group == "process_facility" else FLEX_HEAT_ID
    if kind == COMPOUND_DISTURBANCE:
        resource_id = f"{SOURCE_CRANE_ID}+{SOURCE_LADLE_ID}+A2"
    generic_event = inject_disturbance(
        DisturbanceSpec(
            kind,
            resource_id,
            definition.description,
            occurred_at,
            {"affected_heat_ids": [FLEX_HEAT_ID, TIGHT_HEAT_ID], "window_minutes": 20},
        ),
        source_heats,
        [deepcopy(item) for item in indexes["ladle"].values()],
        [deepcopy(item) for item in indexes["crane"].values()],
        [deepcopy(indexes["assignment"][FLEX_HEAT_ID]), deepcopy(indexes["assignment"][TIGHT_HEAT_ID])],
    )
    controlled_overrides = {
        "state_change": definition.state_change,
        "affected_heat_ids": [FLEX_HEAT_ID, TIGHT_HEAT_ID],
        "original_crane_id": SOURCE_CRANE_ID,
        "original_ladle_id": SOURCE_LADLE_ID,
        "candidate_crane_ids": [NEAR_CRANE_ID, FAR_CRANE_ID],
        "candidate_ladle_ids": [FLEX_LADLE_ID, TIGHT_LADLE_ID],
        "temporary_ladle_positions_from_real_cranes": {FLEX_LADLE_ID: FAR_CRANE_ID, TIGHT_LADLE_ID: NEAR_CRANE_ID},
        "compressed_window": {"heat_id": TIGHT_HEAT_ID, "seconds": COMPRESSED_WINDOW_SECONDS},
        "route_policy": {"allowed_routes_by_heat": policy.allowed_routes_by_heat, "blocked_route_tokens": policy.blocked_route_tokens},
        "event_state_deltas": event_state_deltas,
        "injector_applied": True,
        "injector_impact_scope": generic_event.audit["impact_scope"],
        "injector_event_state_deltas": generic_event.audit["event_state_deltas"],
    }
    spec = DisturbanceSpec(kind, resource_id, definition.description, occurred_at, controlled_overrides)
    scenario = DisturbedScenario(
        spec=spec,
        baseline_heats=source_heats,
        baseline_ladles=[deepcopy(indexes["ladle"][SOURCE_LADLE_ID]), *deepcopy(ladles)],
        baseline_cranes=[deepcopy(indexes["crane"][SOURCE_CRANE_ID]), *deepcopy(cranes)],
        baseline_assignments=[deepcopy(indexes["assignment"][FLEX_HEAT_ID]), deepcopy(indexes["assignment"][TIGHT_HEAT_ID])],
        affected_heat_ids=[FLEX_HEAT_ID, TIGHT_HEAT_ID],
        remaining_ladles=ladles,
        remaining_cranes=cranes,
        frozen_assignments={},
        heats_needing_reallocation=heats,
        earliest_casting_seconds=earliest,
        is_emergency=False,
        earliest_pour_at=earliest,
        remaining_budget_seconds=budget,
        audit={"event": {"kind": kind, "resource_id": resource_id, "occurred_at": occurred_at, "description": definition.description, "metadata": controlled_overrides}},
    )
    validator = ScenarioValidator(policy)
    adapter = SavedCodexProposalAdapter(proposal)
    comparison = TieredResponseController(adapter, clock=_offline_clock, validator=validator).run_three_way(scenario, f"llm_fallback_{ordinal:03d}_{kind}")
    if comparison.decision_tree.success or comparison.decision_tree.num_assigned >= len(heats):
        raise RuntimeError(f"stress scenario did not force decision-tree failure: {kind}")
    if not adapter.called or comparison.llm_react is None or not comparison.llm_react.success:
        raise RuntimeError(f"saved Codex proposal did not complete scenario: {kind}")
    dt_rows, dt_checks = validator.audit(heats, ladles, cranes, comparison.decision_tree.assignments)
    llm_rows, llm_checks = validator.audit(heats, ladles, cranes, comparison.llm_react.assignments)
    if not all(item["passed"] for item in llm_checks):
        raise RuntimeError(f"saved Codex proposal failed final validation: {kind}")
    scenario_id = f"llm_fallback_{ordinal:03d}_{kind}"
    return {
        "scenario_id": scenario_id,
        "category": "llm_fallback_stress",
        "disturbance_kind": kind,
        "disturbance_group": definition.group,
        "title": definition.title,
        "description": definition.description,
        "visual_cue": definition.visual_cue,
        "evidence_type": "controlled_real_snapshot_llm_stress",
        "event_time": occurred_at,
        "window_start": occurred_at,
        "window_end": occurred_at + 1200.0,
        "seed": 2000 + ordinal,
        "source": _source_references(source_audit),
        "event": scenario.audit["event"],
        "events": _timeline(occurred_at, True),
        "assets": _source_assets(indexes),
        "inputs": {"heats": heats, "ladles": ladles, "cranes": cranes, "baseline_assignments": scenario.baseline_assignments},
        "responses": {"decision_tree": {**_result_payload(comparison.decision_tree, 6.0, budget - 6.0), "assignments": dt_rows}, "llm": {**_result_payload(comparison.llm_react, 23.0, budget - 29.0), "assignments": llm_rows}},
        "validations": {
            "decision_tree": [{"check_code": "decision_tree_attempted_first", "passed": True, "details": {}}, {"check_code": "decision_tree_incomplete_expected", "passed": True, "details": {"assigned": comparison.decision_tree.num_assigned, "total": len(heats)}}, *dt_checks],
            "llm": [{"check_code": "codex_adapter_invoked", "passed": adapter.called, "details": {"external_api_called": False}}, *llm_checks],
        },
        "audit": {
            "evidence_boundary": "炉次、钢包、行车、路线和快照字段来自 PLAN(1)/CRANE 审计；事件与覆盖项为可复现压力输入，不是生产事故日志。",
            "controlled_overrides": controlled_overrides,
            "llm_attempted": adapter.called,
            "llm_provider": "Codex reviewed offline proposal",
            "external_api_called": False,
            "decision_tree_failure_context": adapter.failure_context,
            "budget_received_seconds": budget - 6.0,
            "timing_model": "deterministic_demo_timeline_not_wall_clock",
            "location_baseline": {
                "audit_path": source_audit,
                "location_dictionary": location_metadata["path"],
                "mapping": deepcopy(location_metadata["mapping"]),
                "algorithm_version": location_metadata["algorithm_version"],
            },
            "impact_scope": {
                "affected_heat_ids": [FLEX_HEAT_ID, TIGHT_HEAT_ID],
                "excluded_locked_heat_ids": [],
                "outside_scope_heat_ids": [],
            },
            "earliest_pour_at": earliest,
            "remaining_budget_seconds": budget,
        },
    }


def build_scenario_records(source_audit: str | Path = SOURCE_AUDIT) -> list[dict[str, Any]]:
    """Build the complete two-category, source-backed offline scenario set."""
    source_path = Path(source_audit)
    source = load_location_aware_audit(source_path)
    source_reference = _portable_source_path(source_path)
    indexes = _indexes(source)
    _require(indexes)
    records = [_ordinary_control(source, indexes, source_reference)]
    location_metadata = {
        "path": source["location"]["path"],
        "mapping": source["location"]["mapping"],
        "algorithm_version": source["tree_version"],
    }
    records.extend(_stress_record(row["kind"], ordinal, indexes, source_reference, location_metadata) for ordinal, row in enumerate(catalog_rows(), 1))
    # The browser's primary replay is the larger, real 11:00-11:20 window.
    # Keep the catalog's other verified fixtures intact while projecting this
    # same audited result into SQLite so API and HTML share one evidence set.
    window_audit_path = PROJECT_ROOT / "outputs/real_data_codex_stress_demo/audit.json"
    if window_audit_path.exists():
        window = json.loads(window_audit_path.read_text(encoding="utf-8"))
        target = next(row for row in records if row["disturbance_kind"] == CRANE_OFFLINE and row["category"] == "llm_fallback_stress")
        target["title"] = "11:00 行车离线 · Codex 兜底"
        target["description"] = "11:00 行车 2500 受控离线，31 炉局部窗口由决策树先尝试、Codex 完成兜底。"
        target["window_start"] = window["stress_audit"]["event"]["occurred_at"]
        target["window_end"] = target["window_start"] + 1200.0
        target["event"] = window["stress_audit"]["event"]
        target["events"] = [{"sequence": index, "event_type": "window_replay", "offset_seconds": float(index), "occurred_at": target["window_start"] + index, "payload": payload} for index, payload in enumerate((
            {"window_heat_count": window["stress_audit"]["window"]["heat_count"]},
            {"offline_crane_ids": window["stress_audit"]["controlled_overrides"]["offline_crane_ids"]},
            {"decision_tree_assigned": window["decision_tree"]["num_assigned"]},
            {"codex_assigned": window["codex_llm"]["num_assigned"]},
            {"changed_assignments": len(window["stress_audit"].get("changed_assignments", []))},
        ), 1)]
        target["inputs"] = {"heats": window["scenario_inputs"]["heats"], "ladles": window["scenario_inputs"]["ladles"], "cranes": window["scenario_inputs"]["cranes"], "baseline_assignments": window["scenario_inputs"]["source_baseline_assignments"]}
        known_routes = {str(item["asset_id"]) for item in target["assets"] if item["asset_type"] == "route"}
        for heat in target["inputs"]["heats"]:
            route = str(heat.get("refining_route") or "").strip()
            if route and route not in known_routes:
                target["assets"].append({"asset_type": "route", "asset_id": route, "role": "window_source_route", "source_record": deepcopy(heat)})
                known_routes.add(route)
        target["responses"] = {"decision_tree": window["decision_tree"], "llm": window["codex_llm"]}
        target["validations"] = window["validation_checks"]
        target["audit"] = {
            **target.get("audit", {}),
            "evidence_boundary": window["stress_audit"]["evidence_boundary"],
            "controlled_overrides": {
                **window["stress_audit"]["controlled_overrides"],
                "event_state_deltas": [{"asset_type": "crane", "asset_id": "2500", "before": {"online": True}, "after": {"online": False}}],
            },
            "llm_attempted": window["llm_invocation"]["controller_called_adapter"],
            "llm_provider": window["llm_invocation"]["provider"],
            "external_api_called": window["llm_invocation"]["external_api_called"],
            "location_baseline": {
                "audit_path": source_reference,
                "location_dictionary": source["location"]["path"],
                "mapping": deepcopy(source["location"]["mapping"]),
                "algorithm_version": source["tree_version"],
            },
            "impact_scope": {
                "affected_heat_ids": window["stress_audit"]["affected_heat_ids"],
                "excluded_locked_heat_ids": [],
                "outside_scope_heat_ids": [],
            },
            "earliest_pour_at": window["stress_audit"]["earliest_pour_at"],
            "remaining_budget_seconds": window["stress_audit"]["remaining_budget_seconds"],
        }
    categories = {record["category"] for record in records}
    if categories != {"decision_tree_control", "llm_fallback_stress"}:
        raise RuntimeError(f"unexpected scenario categories: {sorted(categories)}")
    return records
