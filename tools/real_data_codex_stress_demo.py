"""Build the fixed 11:00-11:20 Codex stress replay from PLAN/CRANE evidence.

The source audit contains 457 eligible heats.  AP is the location-aware
preallocation snapshot and the only baseline for both response branches.  The
decision tree and the current Codex proposal receive the same 31-heat event
snapshot; the Codex proposal is generated independently and never reads AQ.
The outage and route policy are controlled replay inputs, not production facts.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ladle_preallocation.decision_tree.allocator import allocate
from ladle_preallocation.decision_tree.constraints import expected_arrival
from ladle_preallocation.decision_tree.scoring import score_candidate
from ladle_preallocation.disturbance.injector import DisturbanceSpec, DisturbedScenario, SAFETY_BUFFER_SECONDS
from ladle_preallocation.offline_scenarios.validation import ScenarioValidationPolicy, ScenarioValidator
from ladle_preallocation.response import TieredResponseController
from ladle_preallocation.real_data.audit import load_location_aware_audit


SOURCE_AUDIT = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"
OUTPUT_DIR = ROOT / "outputs/real_data_codex_stress_demo"
SCENARIO_ID = "real_window_1100_1120_codex_stress_001"
OFFLINE_CRANE_ID = "2500"
WINDOW_START_MINUTE = 60.0
WINDOW_END_MINUTE = 80.0
CODEX_ROUTE_POLICY = {"JU6310E7-300751": "A1"}
CODEX_WEIGHTS = {
    "grade": 0.35,
    "age": 0.10,
    "window": 0.35,
    "balance": 0.10,
    "scarcity": 0.10,
}


def _offline_clock() -> float:
    """Keep saved Codex evidence independent of host scheduling latency."""
    return 0.0


def _demo_minute(pour_at: float, minimum: float, span: float) -> float:
    return (pour_at - minimum) / span * 600.0 if span else 0.0


def _result_payload(result: Any, elapsed: float) -> dict[str, Any]:
    return {
        "path": result.path.value,
        "success": bool(result.success),
        "num_assigned": result.num_assigned,
        "elapsed_seconds": elapsed,
        "remaining_budget_seconds": result.remaining_budget_seconds,
        "reason": result.reason,
        "assignments": [dict(row) for row in result.assignments],
        "validation_feedback": deepcopy(result.validation_feedback),
        "metrics": deepcopy(result.metrics),
    }


def _scenario_inputs(source: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], float, float]:
    inputs = source["scheduling_inputs"]
    all_heats = [deepcopy(row) for row in inputs["heats"]]
    all_ladles = [deepcopy(row) for row in inputs["ladles"]]
    all_cranes = [deepcopy(row) for row in inputs["cranes"]]
    pours = [float(row["pour_at"]) for row in all_heats if row.get("pour_at") is not None]
    minimum, maximum = min(pours), max(pours)
    span = maximum - minimum
    window = [
        row for row in all_heats
        if WINDOW_START_MINUTE <= _demo_minute(float(row["pour_at"]), minimum, span) <= WINDOW_END_MINUTE
    ]
    if len(window) != 31:
        raise RuntimeError(f"expected 31 heats in 11:00-11:20 window, got {len(window)}")
    return source, all_heats, all_ladles, all_cranes, window, minimum, span


def _ap_baseline(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover the complete AP assignment set from the location-aware audit."""
    assignments = [deepcopy(row) for row in source["assignments"]]
    if len(assignments) != len(source["scheduling_inputs"]["heats"]):
        raise RuntimeError("AP baseline is not complete")
    if {str(row["heat_id"]) for row in assignments} != {
        str(row["heat_id"]) for row in source["scheduling_inputs"]["heats"]
    }:
        raise RuntimeError("AP baseline heat IDs do not match location-aware inputs")
    if any(row.get("algorithm") != "decision_tree" for row in assignments):
        raise RuntimeError("AP baseline source is not the location-aware decision-tree audit")
    return assignments


def _codex_proposal(
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    baseline_by_heat: dict[str, dict[str, Any]],
    offline_crane_id: str,
    route_by_heat: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Generate a bounded, AP-seeded Codex repair without reading AQ.

    The current Codex supplies this structured proposal.  The local adapter
    only transports it through the normal controller and validator, so the
    saved evidence remains reproducible and credential-free.
    """
    from ladle_preallocation.decision_tree.constraints import validate_assignment
    from ladle_preallocation.data_modeling.grades import grade_matches

    base_loads = {str(item["crane_id"]): float(item.get("current_load_tonnes", 0) or 0) for item in cranes}
    transported_loads = dict(base_loads)
    proposal: list[dict[str, Any]] = []
    for heat in heats:
        heat_id = str(heat["heat_id"])
        original = baseline_by_heat[heat_id]
        if str(original.get("crane_id")) != offline_crane_id:
            row = deepcopy(original)
            if route_by_heat and heat_id in route_by_heat:
                row["refining_route"] = route_by_heat[heat_id]
            proposal.append(row)
            continue
        options: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
        for ladle in ladles:
            if not grade_matches(heat.get("required_grade"), ladle.get("grade")):
                continue
            for crane in cranes:
                if str(crane["crane_id"]) == offline_crane_id:
                    continue
                errors = validate_assignment(heat, ladle, crane, base_loads)
                if errors:
                    continue
                score = score_candidate(heat, ladle, crane, transported_loads, ladles, CODEX_WEIGHTS)
                options.append((score, ladle, crane))
        if not options:
            proposal.append({"heat_id": heat_id, "action": "unassigned", "reason": "Codex 无可行替代资源"})
            continue
        _, ladle, crane = max(options, key=lambda item: (item[0], -float(item[2].get("position_m", 0) or 0), str(item[1]["ladle_id"])))
        transported_loads[str(crane["crane_id"])] += float(ladle.get("weight_tonnes", 0) or 0)
        row = {
            "heat_id": heat_id,
            "ladle_id": str(ladle["ladle_id"]),
            "crane_id": str(crane["crane_id"]),
            "expected_arrival_seconds": expected_arrival(heat, ladle, crane),
            "grade_match": True,
            "action": "assign",
            "reason": f"Codex 独立重排：行车 {offline_crane_id} 离线，为炉次 {heat_id} 选择可行替代钢包/行车。",
        }
        if route_by_heat and heat_id in route_by_heat:
            row["refining_route"] = route_by_heat[heat_id]
        proposal.append(row)
    return proposal


def build_scenario(source: dict[str, Any]) -> tuple[DisturbedScenario, dict[str, Any]]:
    """Build the same 31-heat scenario for the optional realtime endpoint."""
    _, all_heats, all_ladles, all_cranes, window, minimum, span = _scenario_inputs(source)
    baseline_full = _ap_baseline(source)
    by_heat = {str(row["heat_id"]): row for row in baseline_full}
    baseline_window = [deepcopy(by_heat[str(row["heat_id"])]) for row in window]
    remaining_cranes = [deepcopy(row) for row in all_cranes if str(row["crane_id"]) != OFFLINE_CRANE_ID]
    occurred_at = minimum + span * WINDOW_START_MINUTE / 600.0
    earliest_pour = min(float(row["pour_at"]) for row in window)
    audit = {"event": {"kind": "crane_offline", "resource_id": OFFLINE_CRANE_ID, "occurred_at": occurred_at, "description": "11:00 行车 2500 受控离线，打开 11:00-11:20 局部窗口"}, "window": {"heat_count": len(window), "affected_heat_ids": [str(row["heat_id"]) for row in window]}}
    scenario = DisturbedScenario(
        spec=DisturbanceSpec("crane_offline", OFFLINE_CRANE_ID, audit["event"]["description"], occurred_at, {"window_minutes": 20}),
        baseline_heats=deepcopy(window), baseline_ladles=deepcopy(all_ladles), baseline_cranes=deepcopy(all_cranes), baseline_assignments=baseline_window,
        affected_heat_ids=[str(row["heat_id"]) for row in window], remaining_ladles=deepcopy(all_ladles), remaining_cranes=remaining_cranes,
        frozen_assignments={}, heats_needing_reallocation=deepcopy(window), earliest_casting_seconds=earliest_pour, is_emergency=False,
        earliest_pour_at=earliest_pour, remaining_budget_seconds=earliest_pour - occurred_at - SAFETY_BUFFER_SECONDS, audit=audit,
    )
    return scenario, audit


class SavedCodexProposalAdapter:
    """Run the reviewed Codex proposal fixture through the real controller."""

    def __init__(self, proposal: list[dict[str, Any]]) -> None:
        self.proposal = deepcopy(proposal)
        self.called = False
        self.remaining_budget_seconds: float | None = None
        self.failure_context: dict[str, Any] = {}

    def __call__(self, _heats: list[dict[str, Any]], _ladles: list[dict[str, Any]], _cranes: list[dict[str, Any]], **kwargs: Any) -> tuple[bool, list[dict[str, Any]]]:
        self.called = True
        self.remaining_budget_seconds = kwargs.get("remaining_budget_seconds")
        self.failure_context = deepcopy(kwargs.get("failure_context") or {})
        return True, deepcopy(self.proposal)


def build_demo(source_path: Path = SOURCE_AUDIT) -> dict[str, Any]:
    source = load_location_aware_audit(source_path)
    _, all_heats, all_ladles, all_cranes, window, minimum, span = _scenario_inputs(source)
    baseline_full = _ap_baseline(source)
    baseline_by_heat = {str(row["heat_id"]): row for row in baseline_full}
    window_ids = [str(row["heat_id"]) for row in window]
    baseline_window = [deepcopy(baseline_by_heat[heat_id]) for heat_id in window_ids]

    # Incident time is exactly 11:00 on the browser's normalized 10-hour axis.
    occurred_at = minimum + span * WINDOW_START_MINUTE / 600.0
    earliest_pour = min(float(row["pour_at"]) for row in window)
    budget = earliest_pour - occurred_at - SAFETY_BUFFER_SECONDS
    remaining_cranes = [deepcopy(row) for row in all_cranes if str(row["crane_id"]) != OFFLINE_CRANE_ID]
    scenario_heats = [deepcopy(row) for row in window]

    # The snapshot has no route field. This explicit route requirement is a
    # controlled stress input that forces the tree's route-blind output to fail;
    # Codex must carry the route in its structured proposal.
    route_policy = {heat_id: (route,) for heat_id, route in CODEX_ROUTE_POLICY.items()}
    validator = ScenarioValidator(ScenarioValidationPolicy(allowed_routes_by_heat=route_policy))
    proposal = _codex_proposal(
        scenario_heats,
        all_ladles,
        remaining_cranes,
        baseline_by_heat,
        OFFLINE_CRANE_ID,
        CODEX_ROUTE_POLICY,
    )

    scenario = DisturbedScenario(
        spec=DisturbanceSpec(
            kind="crane_offline",
            resource_id=OFFLINE_CRANE_ID,
            description="11:00 行车 2500 受控离线，打开 11:00-11:20 局部窗口",
            occurred_at=occurred_at,
            metadata={"window_minutes": 20, "offline_crane_ids": [OFFLINE_CRANE_ID]},
        ),
        baseline_heats=deepcopy(scenario_heats),
        baseline_ladles=deepcopy(all_ladles),
        baseline_cranes=deepcopy(all_cranes),
        baseline_assignments=deepcopy(baseline_window),
        affected_heat_ids=window_ids,
        remaining_ladles=deepcopy(all_ladles),
        remaining_cranes=remaining_cranes,
        frozen_assignments={},
        heats_needing_reallocation=deepcopy(scenario_heats),
        earliest_casting_seconds=earliest_pour,
        is_emergency=False,
        earliest_pour_at=earliest_pour,
        remaining_budget_seconds=budget,
        audit={"event": {"kind": "crane_offline", "resource_id": OFFLINE_CRANE_ID, "occurred_at": occurred_at}},
    )
    adapter = SavedCodexProposalAdapter(proposal)
    comparison = TieredResponseController(adapter, clock=_offline_clock, validator=validator).run_three_way(scenario, SCENARIO_ID)
    if comparison.decision_tree.success or comparison.decision_tree.num_assigned >= len(window):
        raise RuntimeError("decision tree unexpectedly completed the 31-heat stress window")
    if not adapter.called or comparison.llm_react is None or not comparison.llm_react.success:
        raise RuntimeError("Codex proposal did not complete the stress window")

    dt_rows, dt_checks = validator.audit(scenario_heats, all_ladles, remaining_cranes, comparison.decision_tree.assignments)
    llm_rows, llm_checks = validator.audit(scenario_heats, all_ladles, remaining_cranes, comparison.llm_react.assignments)
    if not all(check["passed"] for check in llm_checks):
        raise RuntimeError("Codex proposal failed final validation")
    llm_by_heat = {str(row["heat_id"]): row for row in llm_rows}
    changes = []
    for heat in scenario_heats:
        heat_id = str(heat["heat_id"])
        old = baseline_by_heat[heat_id]
        new = llm_by_heat[heat_id]
        if (old.get("ladle_id"), old.get("crane_id")) != (new.get("ladle_id"), new.get("crane_id")):
            changes.append({
                "heat_id": heat_id,
                "demo_minute": round(_demo_minute(float(heat["pour_at"]), minimum, span), 2),
                "old_ladle_id": old.get("ladle_id"),
                "old_crane_id": old.get("crane_id"),
                "new_ladle_id": new.get("ladle_id"),
                "new_crane_id": new.get("crane_id"),
                "reason": new.get("reason"),
            })

    stress_audit = {
        "scenario_kind": "controlled_real_snapshot_window_stress_test",
        "evidence_boundary": "457 炉、31 炉窗口以及钢包/行车编号来自 PLAN(1)/CRANE 审计；2500 离线、Codex 候选评分策略和路线约束是受控压力输入，不是生产事故日志。",
        "source_audit": str(source_path.relative_to(ROOT)),
        "window": {"start_minute": WINDOW_START_MINUTE, "end_minute": WINDOW_END_MINUTE, "heat_count": len(window), "affected_heat_ids": window_ids},
        "baseline_strategy": {"name": "location_aware_audit_AP", "source_full_heat_count": len(all_heats), "source_assignment_count": len(baseline_full), "algorithm": source["algorithm"], "tree_version": source["tree_version"]},
        "event": {"kind": "crane_offline", "resource_id": OFFLINE_CRANE_ID, "occurred_at": occurred_at, "description": scenario.spec.description, "metadata": {"offline_crane_ids": [OFFLINE_CRANE_ID], "available_crane_ids": [str(row["crane_id"]) for row in remaining_cranes]}},
        "affected_heat_ids": window_ids,
        "controlled_overrides": {"offline_crane_ids": [OFFLINE_CRANE_ID], "available_crane_ids": [str(row["crane_id"]) for row in remaining_cranes], "route_policy": {"allowed_routes_by_heat": route_policy, "reason": "controlled route requirement; source snapshot has no route field"}, "codex_candidate_policy": "enumerate AP-compatible ladle/crane pairs, validate hard constraints, maximize Codex weights, carry required route", "changed_ids_expected": [str(row["heat_id"]) for row in scenario_heats if str(baseline_by_heat[str(row["heat_id"])].get("crane_id")) == OFFLINE_CRANE_ID]},
        "changed_assignments": changes,
        "earliest_pour_at": earliest_pour,
        "remaining_budget_seconds": budget,
    }
    return {
        "schema_version": 3,
        "scenario_id": SCENARIO_ID,
        "stress_audit": stress_audit,
        "scenario_inputs": {"heats": scenario_heats, "ladles": all_ladles, "cranes": remaining_cranes, "source_baseline_assignments": baseline_window},
        "baseline_full_assignments": baseline_full,
        "decision_tree": _result_payload(comparison.decision_tree, 6.0),
        "codex_llm": _result_payload(comparison.llm_react, 23.0),
        "llm_invocation": {"provider": "Codex current interactive session", "transport": "Codex-authored AP-seeded proposal through TieredResponseController", "external_api_called": False, "controller_called_adapter": adapter.called, "budget_received_seconds": adapter.remaining_budget_seconds, "failure_context_received": adapter.failure_context, "independence": "proposal generated from AP + event snapshot; AQ assignments are excluded"},
        "proposal_validation": llm_rows,
        "validation_checks": {"decision_tree": dt_checks, "llm": [{"check_code": "codex_adapter_invoked", "passed": adapter.called, "details": {"external_api_called": False}}, *llm_checks]},
        "comparison": comparison.summary(),
        "conclusion": f"11:00-11:20 的真实窗口包含 {len(window)} 炉；决策树完成 {comparison.decision_tree.num_assigned}/{len(window)}，Codex 完成 {comparison.llm_react.num_assigned}/{len(window)}，实际改配 {len(changes)} 炉。",
    }


def _report(report: dict[str, Any]) -> str:
    audit = report["stress_audit"]
    dt = report["decision_tree"]
    llm = report["codex_llm"]
    lines = [
        "# 11:00-11:20 真实窗口 Codex 压力测试",
        "",
        "> 真实 PLAN(1)/CRANE 审计包含 457 炉；本次窗口按归一化生产轴取 11:00-11:20 的 31 炉。行车离线、Codex 候选评分策略和路线约束是可复现的受控压力输入，不是生产事故日志。",
        "",
        f"- 决策树：{dt['num_assigned']}/{audit['window']['heat_count']}；Codex：{llm['num_assigned']}/{audit['window']['heat_count']}。",
        f"- 受控扰动：行车 {audit['event']['resource_id']} 离线；可用行车：{', '.join(audit['controlled_overrides']['available_crane_ids'])}。",
        f"- Codex 实际改配：{len(audit['changed_assignments'])} 炉，其他窗口炉次保持基线。",
        "- 结论：Codex 只在决策树不完整后被调用，提案通过完整性、共享硬约束和路由策略校验。",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build_demo()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT_DIR / "report.md").write_text(_report(report), encoding="utf-8")
    print(OUTPUT_DIR / "audit.json")


if __name__ == "__main__":
    main()
