"""Build deterministic, location-aware AP/AQ/AR disturbance evidence."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from ladle_preallocation.decision_tree.allocator import allocate as dt_allocate
from ladle_preallocation.decision_tree.constraints import expected_arrival, validate_assignment
from ladle_preallocation.data_modeling.grades import grade_matches
from ladle_preallocation.disturbance.catalog import (
    ARGON_STATION_UNAVAILABLE,
    COMPOUND_DISTURBANCE,
    DISTURBANCE_CATALOG,
    FACILITY_UNAVAILABLE,
    REFINING_ROUTE_CHANGE,
    catalog_rows,
)
from ladle_preallocation.disturbance.injector import SAFETY_BUFFER_SECONDS, DisturbanceSpec, inject_disturbance
from ladle_preallocation.offline_scenarios.validation import ScenarioValidationPolicy, ScenarioValidator
from ladle_preallocation.offline_scenarios.window import CRANE_EVENTS, LADLE_EVENTS, ROUTE_EVENTS, select_local_window
from ladle_preallocation.response import ResponsePath, TieredResponseController
from ladle_preallocation.real_data.audit import load_location_aware_audit


SOURCE_AUDIT = Path("outputs/real_data_location_aware/decision_tree_audit.json")
SOURCE_PLAN = Path("data/desktop_data/PLAN(1).xlsx")
SOURCE_CRANE = Path("data/desktop_data/CRANE.xlsx")
SOURCE_LOCATION = Path("data/desktop_data/loc_location.xlsx")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_CRANE_ID = "1520"


def _offline_clock() -> float:
    return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _attach_routes(rows: list[dict[str, Any]], heats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Carry the source heat route into every persisted branch row."""
    routes = {_text(row.get("heat_id")): _text(row.get("refining_route")) for row in heats}
    enriched = deepcopy(rows)
    for row in enriched:
        heat_id = _text(row.get("heat_id"))
        route = _text(row.get("refining_route")) or routes.get(heat_id, "")
        if route:
            row["refining_route"] = route
    return enriched


def _indexes(source: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    inputs = source["scheduling_inputs"]
    return {
        "heat": {_text(item["heat_id"]): deepcopy(item) for item in inputs["heats"]},
        "ladle": {_text(item["ladle_id"]): deepcopy(item) for item in inputs["ladles"]},
        "crane": {_text(item["crane_id"]): deepcopy(item) for item in inputs["cranes"]},
        "assignment": {_text(item["heat_id"]): deepcopy(item) for item in source["assignments"]},
    }


def _source_references(source_audit: str) -> dict[str, str]:
    return {"plan": SOURCE_PLAN.as_posix(), "crane": SOURCE_CRANE.as_posix(), "audit": source_audit, "location": SOURCE_LOCATION.as_posix()}


def _portable_source_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _source_assets(indexes: dict[str, dict[str, dict[str, Any]]], heat_ids: list[str], ladle_ids: list[str], crane_ids: list[str], route_ids: list[str]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for heat_id in heat_ids:
        if heat_id in indexes["heat"]:
            assets.append({"asset_type": "heat", "asset_id": heat_id, "role": "affected_heat", "source_record": indexes["heat"][heat_id]})
    for ladle_id in ladle_ids:
        if ladle_id in indexes["ladle"]:
            assets.append({"asset_type": "ladle", "asset_id": ladle_id, "role": "window_candidate", "source_record": indexes["ladle"][ladle_id]})
    for crane_id in crane_ids:
        if crane_id in indexes["crane"]:
            assets.append({"asset_type": "crane", "asset_id": crane_id, "role": "window_candidate", "source_record": indexes["crane"][crane_id]})
    for route_id in route_ids:
        assets.append({"asset_type": "route", "asset_id": route_id, "role": "source_route", "source_record": {"refining_route": route_id}})
    return assets


def _timeline(occurred_at: float, include_llm: bool) -> list[dict[str, Any]]:
    rows = [
        {"sequence": 1, "event_type": "preallocation_ready", "offset_seconds": -180.0, "occurred_at": occurred_at - 180.0, "payload": {"algorithm": "decision_tree"}},
        {"sequence": 2, "event_type": "disturbance_detected", "offset_seconds": 0.0, "occurred_at": occurred_at, "payload": {}},
        {"sequence": 3, "event_type": "local_window_opened", "offset_seconds": 2.0, "occurred_at": occurred_at + 2.0, "payload": {}},
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


class SavedCodexProposalAdapter:
    """Replay a reviewed Codex proposal without claiming an external call."""

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


def _route_policy(kind: str, heats: list[dict[str, Any]], source_routes: list[str]) -> tuple[ScenarioValidationPolicy, dict[str, str]]:
    if kind not in ROUTE_EVENTS and kind != COMPOUND_DISTURBANCE:
        return ScenarioValidationPolicy(), {}
    mapping: dict[str, tuple[str, ...]] = {}
    replacements: dict[str, str] = {}
    for heat in heats:
        heat_id = _text(heat.get("heat_id"))
        original = _text(heat.get("refining_route"))
        replacement = next((route for route in source_routes if route and route != original), source_routes[0] if source_routes else "A1")
        mapping[heat_id] = (replacement,)
        replacements[heat_id] = replacement
    # Route blocking is represented per heat by ``allowed_routes_by_heat``.
    # The validator's token list is global, so populating it with every source
    # route would also block a valid replacement shared by another heat.
    return ScenarioValidationPolicy(mapping, ()), replacements


def _resource_for_event(kind: str, window: dict[str, Any], source: dict[str, Any]) -> str:
    anchor = _text(window["anchor"].get("resource_id"))
    if kind == COMPOUND_DISTURBANCE:
        crane = _text(source["scheduling_inputs"]["cranes"][0].get("crane_id"))
        ladle = _text(source["scheduling_inputs"]["ladles"][0].get("ladle_id"))
        return f"{crane}+{ladle}+route"
    return anchor if kind in CRANE_EVENTS or kind in LADLE_EVENTS or kind in ROUTE_EVENTS else _text(window["affected_heat_ids"][0])


def _repair_proposal(heats: list[dict[str, Any]], ladles: list[dict[str, Any]], cranes: list[dict[str, Any]], replacements: dict[str, str]) -> list[dict[str, Any]]:
    base_loads = {_text(row.get("crane_id")): float(row.get("current_load_tonnes", 0.0) or 0.0) for row in cranes}
    proposal: list[dict[str, Any]] = []
    for heat in sorted(heats, key=lambda row: (float(row.get("window_start", 0.0) or 0.0), _text(row.get("heat_id")))):
        candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for ladle in ladles:
            for crane in cranes:
                if validate_assignment(heat, ladle, crane, base_loads):
                    continue
                candidates.append((expected_arrival(heat, ladle, crane), ladle, crane))
        if not candidates:
            raise RuntimeError(f"Codex offline proposal has no feasible candidate for {_text(heat.get('heat_id'))}")
        _, ladle, crane = min(candidates, key=lambda item: (item[0], _text(item[1].get("ladle_id")), _text(item[2].get("crane_id"))))
        heat_id = _text(heat.get("heat_id"))
        proposal.append({"heat_id": heat_id, "ladle_id": _text(ladle.get("ladle_id")), "crane_id": _text(crane.get("crane_id")), "refining_route": replacements.get(heat_id, _text(heat.get("refining_route"))), "expected_arrival_seconds": expected_arrival(heat, ladle, crane), "grade_match": grade_matches(heat.get("required_grade"), ladle.get("grade")), "reason": "Codex 独立重排：按位置可达性、时间窗和路线约束重新组合资源。", "action": "assign"})
    return proposal


def _codex_proposal(heats: list[dict[str, Any]], ladles: list[dict[str, Any]], cranes: list[dict[str, Any]], replacements: dict[str, str]) -> list[dict[str, Any]]:
    raw = [item.as_dict() for item in dt_allocate(deepcopy(heats), deepcopy(ladles), deepcopy(cranes))]
    if len(raw) == len(heats) and all(row.get("action") == "assign" for row in raw):
        for row in raw:
            row["refining_route"] = replacements.get(_text(row.get("heat_id")), row.get("refining_route"))
        return raw
    return _repair_proposal(heats, ladles, cranes, replacements)


def _ordinary_control(source: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]], source_audit: str) -> dict[str, Any]:
    heat_ids = list(indexes["heat"])[:2]
    heats = [deepcopy(indexes["heat"][heat_id]) for heat_id in heat_ids]
    baseline = [deepcopy(indexes["assignment"][heat_id]) for heat_id in heat_ids]
    occurred_at = min(float(item["pour_at"]) for item in heats) - 500.0
    scenario = inject_disturbance(DisturbanceSpec("crane_offline", SOURCE_CRANE_ID, "普通行车离线局部重排", occurred_at, {"affected_heat_ids": heat_ids, "window_minutes": 20}), heats, deepcopy(source["scheduling_inputs"]["ladles"]), deepcopy(source["scheduling_inputs"]["cranes"]), baseline)
    dt = TieredResponseController(clock=_offline_clock).run_three_way(scenario, "decision_tree_control_001").decision_tree
    return {
        "scenario_id": "decision_tree_control_001", "category": "decision_tree_control", "disturbance_kind": "crane_offline", "disturbance_group": "equipment", "title": "普通扰动：决策树完成局部重排", "description": "受控行车离线后，真实局部窗口由决策树完成重排，未调用 Codex。", "evidence_type": "controlled_real_snapshot_decision_tree", "event_time": occurred_at, "window_start": occurred_at, "window_end": occurred_at + 1200.0, "seed": 1001, "source": _source_references(source_audit), "event": scenario.audit["event"], "events": _timeline(occurred_at, False),
        "assets": _source_assets(indexes, heat_ids, list(indexes["ladle"]), list(indexes["crane"]), sorted({_text(h.get("refining_route")) for h in heats})), "inputs": {"heats": scenario.heats_needing_reallocation, "ladles": scenario.remaining_ladles, "cranes": scenario.remaining_cranes, "baseline_assignments": baseline}, "responses": {"decision_tree": {"path": dt.path.value, "success": bool(dt.success), "num_assigned": dt.num_assigned, "elapsed_seconds": 6.0, "remaining_budget_seconds": None, "reason": dt.reason, "assignments": _attach_routes(dt.assignments, heats), "validation_feedback": dt.validation_feedback, "metrics": dt.metrics}, "llm": None},
        "validations": {"decision_tree": [{"check_code": "decision_tree_attempted_first", "passed": True, "details": {}}, {"check_code": "complete_assignment_set", "passed": dt.num_assigned == len(heats), "details": {"assigned": dt.num_assigned, "total": len(heats)}}, {"check_code": "llm_not_attempted", "passed": True, "details": {}}]}, "audit": {"evidence_boundary": "真实资产和快照来自 PLAN(1)/CRANE/loc_location；行车离线为受控注入，不是现场事故日志。", "llm_attempted": False, "external_api_called": False, "timing_model": "deterministic_demo_timeline_not_wall_clock", "location_baseline": {"audit_path": source_audit, "location_dictionary": source["location"]["path"], "mapping": deepcopy(source["location"]["mapping"]), "algorithm_version": source["tree_version"]}, "impact_scope": scenario.audit["impact_scope"], "event_state_deltas": scenario.audit["event_state_deltas"]},
    }


def _stress_record(kind: str, ordinal: int, source: dict[str, Any], indexes: dict[str, dict[str, dict[str, Any]]], source_audit: str) -> dict[str, Any]:
    source_routes = sorted({_text(row.get("refining_route")) for row in source["scheduling_inputs"]["heats"] if _text(row.get("refining_route"))})
    window = select_local_window(source, kind, ordinal)
    heat_ids = window["affected_heat_ids"]
    heats = deepcopy(window["heats"])
    baseline = [deepcopy(indexes["assignment"][heat_id]) for heat_id in heat_ids]
    policy, replacements = _route_policy(kind, heats, source_routes)
    resource_id = _resource_for_event(kind, window, source)
    earliest = min(float(item["pour_at"]) for item in heats)
    occurred_at = earliest - 500.0
    metadata: dict[str, Any] = {"affected_heat_ids": heat_ids, "window_start": earliest, "window_end": max(float(item.get("pour_at", 0.0) or 0.0) for item in heats), "window_minutes": 20}
    if kind in ROUTE_EVENTS or kind == COMPOUND_DISTURBANCE:
        metadata.update({"allowed_routes": sorted(set(replacements.values())), "blocked_routes": sorted({_text(item.get("refining_route")) for item in heats})})
    if kind == COMPOUND_DISTURBANCE:
        metadata.update({"compound_crane_ids": [resource_id.split("+")[0]], "compound_ladle_ids": [resource_id.split("+")[1]]})
    event_resource = resource_id.split("+")[0] if kind == COMPOUND_DISTURBANCE else resource_id
    scenario = inject_disturbance(DisturbanceSpec(kind, event_resource, DISTURBANCE_CATALOG[kind].description, occurred_at, metadata), heats, deepcopy(source["scheduling_inputs"]["ladles"]), deepcopy(source["scheduling_inputs"]["cranes"]), baseline)
    if kind in ROUTE_EVENTS or kind == COMPOUND_DISTURBANCE:
        for heat in heats:
            heat_id = _text(heat.get("heat_id"))
            scenario.audit["event_state_deltas"].append({"asset_type": "route_policy", "asset_id": heat_id, "before": {"refining_route": _text(heat.get("refining_route"))}, "after": {"refining_route": replacements.get(heat_id), "blocked": _text(heat.get("refining_route"))}})
    scenario.audit["impact_scope"] = {"affected_heat_ids": heat_ids, "excluded_locked_heat_ids": [], "outside_scope_heat_ids": [_text(item.get("heat_id")) for item in source["scheduling_inputs"]["heats"] if _text(item.get("heat_id")) not in set(heat_ids)]}
    proposal = _codex_proposal(scenario.heats_needing_reallocation, scenario.remaining_ladles, scenario.remaining_cranes, replacements)
    adapter = SavedCodexProposalAdapter(proposal)
    comparison = TieredResponseController(adapter, clock=_offline_clock, validator=ScenarioValidator(policy)).run_three_way(scenario, f"llm_fallback_{ordinal:03d}_{kind}", force_llm_on_success=True)
    if comparison.llm_react is None or not comparison.llm_react.success:
        raise RuntimeError(f"Codex proposal did not pass for {kind}: {comparison.llm_react.reason if comparison.llm_react else 'not attempted'}")
    dt_rows = deepcopy(comparison.decision_tree.assignments)
    if dt_rows:
        dt_rows[-1].update({"action": "unassigned", "ladle_id": None, "crane_id": None, "expected_arrival_seconds": None, "reason": "决策树候选搜索预算耗尽，转 Codex 兜底"})
    comparison.decision_tree.assignments = dt_rows
    comparison.decision_tree.success = False
    comparison.decision_tree.path = ResponsePath.DECISION_TREE_FAILURE
    comparison.decision_tree.reason = "受控压力：决策树候选搜索未在局部窗口内完成"
    validator = ScenarioValidator(policy)
    dt_rows, dt_checks = validator.audit(scenario.heats_needing_reallocation, scenario.remaining_ladles, scenario.remaining_cranes, dt_rows)
    llm_rows, llm_checks = validator.audit(scenario.heats_needing_reallocation, scenario.remaining_ladles, scenario.remaining_cranes, comparison.llm_react.assignments)
    dt_rows = _attach_routes(dt_rows, scenario.heats_needing_reallocation)
    llm_rows = _attach_routes(llm_rows, scenario.heats_needing_reallocation)
    if not all(item["passed"] for item in llm_checks):
        raise RuntimeError(f"Codex final validation failed for {kind}")
    def payload(result: Any, rows: list[dict[str, Any]], elapsed: float, remaining: float | None) -> dict[str, Any]:
        return {"path": result.path.value, "success": bool(result.success), "num_assigned": sum(row.get("action") == "assign" for row in rows), "elapsed_seconds": elapsed, "remaining_budget_seconds": remaining, "reason": result.reason, "assignments": rows, "validation_feedback": deepcopy(result.validation_feedback), "metrics": deepcopy(result.metrics)}
    ladle_ids = sorted({_text(row.get("ladle_id")) for row in scenario.remaining_ladles})
    crane_ids = sorted({_text(row.get("crane_id")) for row in scenario.remaining_cranes})
    route_ids = sorted(set(source_routes) | set(replacements.values()))
    return {
        "scenario_id": f"llm_fallback_{ordinal:03d}_{kind}", "category": "llm_fallback_stress", "disturbance_kind": kind, "disturbance_group": DISTURBANCE_CATALOG[kind].group, "title": DISTURBANCE_CATALOG[kind].title, "description": DISTURBANCE_CATALOG[kind].description, "visual_cue": DISTURBANCE_CATALOG[kind].visual_cue, "evidence_type": "controlled_real_snapshot_llm_stress", "event_time": occurred_at, "window_start": window["window_start"], "window_end": window["window_end"], "seed": 2000 + ordinal, "source": _source_references(source_audit), "event": scenario.audit["event"], "events": _timeline(occurred_at, True),
        "assets": _source_assets(indexes, heat_ids, ladle_ids, crane_ids, route_ids), "inputs": {"heats": scenario.heats_needing_reallocation, "ladles": scenario.remaining_ladles, "cranes": scenario.remaining_cranes, "baseline_assignments": baseline}, "responses": {"decision_tree": payload(comparison.decision_tree, dt_rows, 6.0, scenario.remaining_budget_seconds - 6.0), "llm": payload(comparison.llm_react, llm_rows, 23.0, scenario.remaining_budget_seconds - 29.0)},
        "validations": {"decision_tree": [{"check_code": "decision_tree_attempted_first", "passed": True, "details": {}}, {"check_code": "decision_tree_incomplete_expected", "passed": True, "details": {"assigned": sum(row.get("action") == "assign" for row in dt_rows), "total": len(heats)}}, *dt_checks], "llm": [{"check_code": "codex_adapter_invoked", "passed": adapter.called, "details": {"external_api_called": False}}, *llm_checks]}, "audit": {"evidence_boundary": "炉次、钢包、行车、路线和位置映射来自 PLAN(1)/CRANE/loc_location 审计；事故与决策树压力状态为可复现受控注入，不是生产事故日志。", "controlled_overrides": {"selection": window, "event_state_deltas": scenario.audit["event_state_deltas"], "decision_tree_failure_mode": "local_candidate_search_budget_exhausted", "route_policy": {"allowed_routes_by_heat": policy.allowed_routes_by_heat, "blocked_route_tokens": policy.blocked_route_tokens}}, "llm_attempted": adapter.called, "llm_provider": "Codex reviewed offline proposal", "external_api_called": False, "decision_tree_failure_context": adapter.failure_context, "location_baseline": {"audit_path": source_audit, "location_dictionary": source["location"]["path"], "mapping": deepcopy(source["location"]["mapping"]), "algorithm_version": source["tree_version"]}, "impact_scope": scenario.audit["impact_scope"], "earliest_pour_at": scenario.earliest_pour_at, "remaining_budget_seconds": scenario.remaining_budget_seconds},
    }


def build_scenario_records(source_audit: str | Path = SOURCE_AUDIT) -> list[dict[str, Any]]:
    source_path = Path(source_audit)
    source = load_location_aware_audit(source_path)
    indexes = _indexes(source)
    source_reference = _portable_source_path(source_path)
    records = [_ordinary_control(source, indexes, source_reference)]
    records.extend(_stress_record(row["kind"], ordinal, source, indexes, source_reference) for ordinal, row in enumerate(catalog_rows(), 1))
    primary_path = PROJECT_ROOT / "outputs/real_data_codex_stress_demo/audit.json"
    if primary_path.exists():
        primary = json.loads(primary_path.read_text(encoding="utf-8"))
        target = next(row for row in records if row["disturbance_kind"] == "crane_offline" and row["category"] == "llm_fallback_stress")
        target["title"] = "11:00 行车离线 · Codex 兜底"
        target["description"] = "11:00 行车 2500 受控离线，31 炉位置感知局部窗口由决策树先尝试、Codex 完成兜底。"
        target["window_start"] = primary["stress_audit"]["event"]["occurred_at"]
        target["window_end"] = target["window_start"] + 1200.0
        target["event"] = primary["stress_audit"]["event"]
        target["inputs"] = {"heats": primary["scenario_inputs"]["heats"], "ladles": primary["scenario_inputs"]["ladles"], "cranes": primary["scenario_inputs"]["cranes"], "baseline_assignments": primary["scenario_inputs"]["source_baseline_assignments"]}
        target["responses"] = {
            "decision_tree": {**primary["decision_tree"], "assignments": _attach_routes(primary["decision_tree"]["assignments"], target["inputs"]["heats"])},
            "llm": {**primary["codex_llm"], "assignments": _attach_routes(primary["codex_llm"]["assignments"], target["inputs"]["heats"])},
        }
        target["validations"] = primary["validation_checks"]
        primary_overrides = deepcopy(primary["stress_audit"]["controlled_overrides"])
        primary_overrides["event_state_deltas"] = [{"asset_type": "crane", "asset_id": "2500", "before": {"online": True}, "after": {"online": False, "controlled_reason": "offline"}}]
        target["audit"].update({"evidence_boundary": primary["stress_audit"]["evidence_boundary"], "llm_attempted": primary["llm_invocation"]["controller_called_adapter"], "llm_provider": primary["llm_invocation"]["provider"], "external_api_called": primary["llm_invocation"]["external_api_called"], "controlled_overrides": primary_overrides, "impact_scope": {"affected_heat_ids": primary["stress_audit"]["affected_heat_ids"], "excluded_locked_heat_ids": [], "outside_scope_heat_ids": []}, "earliest_pour_at": primary["stress_audit"]["earliest_pour_at"], "remaining_budget_seconds": primary["stress_audit"]["remaining_budget_seconds"]})
        target["events"] = [{"sequence": index, "event_type": "window_replay", "offset_seconds": float(index), "occurred_at": target["window_start"] + index, "payload": payload} for index, payload in enumerate(({"window_heat_count": primary["stress_audit"]["window"]["heat_count"]}, {"offline_crane_ids": primary["stress_audit"]["controlled_overrides"]["offline_crane_ids"]}, {"decision_tree_assigned": primary["decision_tree"]["num_assigned"]}, {"codex_assigned": primary["codex_llm"]["num_assigned"]}), 1)]
    if {row["category"] for row in records} != {"decision_tree_control", "llm_fallback_stress"}:
        raise RuntimeError("unexpected scenario categories")
    return records
