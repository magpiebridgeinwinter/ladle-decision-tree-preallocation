"""Build the compact, browser-facing catalog from real audit outputs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"
COMPARISON_PATH = ROOT / "outputs/real_data_location_aware/three_way_comparison.json"
STRESS_PATH = ROOT / "outputs/real_data_codex_stress_demo/audit.json"
OUTPUT_PATH = ROOT / "visualization/demo_catalog.json"
ARCHIVE_OUTPUT_PATH = ROOT / "outputs/demo_catalog.json"
FRONTEND_OUTPUT_PATH = ROOT / "frontend/visualization/demo_catalog.json"

import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ladle_preallocation.real_data.audit import load_location_aware_audit


def _iso(timestamp: float | None) -> str | None:
    return None if timestamp is None else datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()


def _compact_heat(heat: dict[str, Any], assignment: dict[str, Any], minimum: float, span: float) -> dict[str, Any]:
    pour_at = float(heat.get("pour_at", 0) or 0)
    demo_minute = round((pour_at - minimum) / span * 600.0, 2) if span else 0.0
    return {
        "heat_id": str(heat["heat_id"]),
        "demo_minute": demo_minute,
        "pour_at": pour_at,
        "pour_at_iso": _iso(pour_at),
        "window_start": heat.get("window_start"),
        "window_end": heat.get("window_end"),
        "required_grade": str(heat.get("required_grade") or "").strip(),
        "refining_route": str(heat.get("refining_route") or "").strip(),
        "ladle_id": assignment.get("ladle_id"),
        "crane_id": assignment.get("crane_id"),
        "action": assignment.get("action"),
        "reason": assignment.get("reason"),
        "violations": list(assignment.get("violations") or []),
    }


def _summary_case(row: dict[str, Any], source_assignments: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event = row.get("event", {})
    return {
        "id": row["scenario_id"],
        "title": row["disturbance"],
        "kind": event.get("kind"),
        "resource_id": event.get("resource_id"),
        "source": "PLAN(1) / CRANE 真实回放",
        "evidence": "真实数据回放：不包含 LLM 调用",
        "affected": row.get("num_affected", 0),
        "dt_assigned": row.get("dt_assigned"),
        "total": row.get("num_total"),
        "dt_success": row.get("dt_path") == "decision_tree_success",
        "llm_status": "N/A（决策树未失败）",
        "event_time": _iso(event.get("occurred_at")),
        "affected_heat_ids": [
            heat_id for heat_id, assignment in source_assignments.items()
            if assignment.get("crane_id") == event.get("resource_id") or assignment.get("ladle_id") == event.get("resource_id")
        ][:12],
        "metrics": {
            "frozen_on_time_rate": row.get("frozen_metrics", {}).get("on_time_rate"),
            "dt_on_time_rate": row.get("decision_tree_metrics", {}).get("on_time_rate"),
            "avg_delay_seconds": row.get("frozen_metrics", {}).get("average_delay_seconds"),
        },
    }


def _offline_comparison(audit: dict[str, Any]) -> dict[str, Any]:
    """Project the mapped-input SQLite records into the legacy UI summary shape."""
    from ladle_preallocation.offline_scenarios.builder import build_scenario_records

    records = build_scenario_records(AUDIT_PATH)
    cases = []
    for record in records:
        dt = record["responses"]["decision_tree"]
        llm = record["responses"].get("llm")
        event = record["event"]
        cases.append({
            "scenario_id": record["scenario_id"],
            "disturbance": record["title"],
            "event": event,
            "num_affected": len(record["inputs"]["heats"]),
            "num_total": len(record["inputs"]["heats"]),
            "frozen_assigned": 0,
            "dt_assigned": dt["num_assigned"],
            "dt_saved": dt["num_assigned"],
            "dt_path": dt["path"],
            "dt_elapsed_s": dt["elapsed_seconds"],
            "llm_assigned": None if llm is None else llm["num_assigned"],
            "llm_saved_over_dt": None if llm is None else llm["num_assigned"] - dt["num_assigned"],
            "llm_saved_over_frozen": None if llm is None else llm["num_assigned"],
            "llm_path": None if llm is None else llm["path"],
            "llm_elapsed_s": None if llm is None else llm["elapsed_seconds"],
            "frozen_metrics": {},
            "decision_tree_metrics": dt.get("metrics", {}),
            "llm_metrics": None if llm is None else llm.get("metrics", {}),
        })
    return {
        "scenarios": cases,
        "summary": {
            "total_scenarios": len(cases),
            "total_affected_heats": sum(row["num_affected"] for row in cases),
            "dt_success_rate": sum(row["dt_path"] == "decision_tree_success" for row in cases) / len(cases),
            "llm_attempted": sum(row["llm_path"] is not None for row in cases),
        },
    }


def build() -> dict[str, Any]:
    audit = load_location_aware_audit(AUDIT_PATH)
    comparison = _offline_comparison(audit)
    stress = json.loads(STRESS_PATH.read_text(encoding="utf-8"))
    inputs = audit["scheduling_inputs"]
    stress_full_assignments = stress.get("baseline_full_assignments") or []
    assignment_by_heat = {
        str(row["heat_id"]): row
        for row in (stress_full_assignments or audit["assignments"])
    }
    pours = [float(heat["pour_at"]) for heat in inputs["heats"] if heat.get("pour_at") is not None]
    minimum, maximum = min(pours), max(pours)
    heats = [_compact_heat(heat, assignment_by_heat[str(heat["heat_id"])], minimum, maximum - minimum) for heat in inputs["heats"]]
    source_assignments = {str(row["heat_id"]): row for row in audit["assignments"]}
    comparison_cases = [_summary_case(row, source_assignments) for row in comparison["scenarios"]]
    kind_order = {"crane_offline": "行车离线", "ladle_unavailable": "钢包不可用", "facility_unavailable": "设施不可用", "schedule_deviation": "计划偏差"}
    cases_by_kind: dict[str, dict[str, Any]] = {}
    for case in comparison_cases:
        if case["kind"] not in cases_by_kind:
            case["title"] = kind_order.get(case["kind"], case["title"])
            cases_by_kind[case["kind"]] = case
    stress_audit = stress["stress_audit"]
    stress_window_ids = set(stress_audit["window"]["affected_heat_ids"])
    stress_window_by_heat = {
        str(row["heat_id"]): row
        for row in stress["scenario_inputs"]["source_baseline_assignments"]
    }
    changed_by_heat = {
        str(row["heat_id"]): row
        for row in stress_audit.get("changed_assignments", [])
    }
    for heat in heats:
        heat["stress_window"] = heat["heat_id"] in stress_window_ids
        if heat["heat_id"] in stress_window_by_heat:
            heat["baseline_window_crane_id"] = stress_window_by_heat[heat["heat_id"]].get("crane_id")
            heat["baseline_window_ladle_id"] = stress_window_by_heat[heat["heat_id"]].get("ladle_id")
        if heat["heat_id"] in changed_by_heat:
            heat["codex_change"] = changed_by_heat[heat["heat_id"]]
    stress_case = {
        "id": stress["scenario_id"],
        "title": "11:00 行车离线 · Codex 兜底",
        "kind": "crane_offline",
        "resource_id": "2500",
        "source": "真实快照派生受控压力测试",
        "evidence": "真实编号 + 受控扰动；不是生产事故日志",
        "affected": stress_audit["window"]["heat_count"],
        "dt_assigned": stress["decision_tree"]["num_assigned"],
        "total": stress_audit["window"]["heat_count"],
        "dt_success": False,
        "llm_status": f"Codex {stress['codex_llm']['num_assigned']}/{stress_audit['window']['heat_count']}（已审计）",
        "event_time": _iso(stress_audit["event"]["occurred_at"]),
        "affected_heat_ids": stress_audit["window"]["affected_heat_ids"],
        "offline_crane_ids": stress_audit["controlled_overrides"]["offline_crane_ids"],
        "available_crane_ids": stress_audit["controlled_overrides"]["available_crane_ids"],
        "window": stress_audit["window"],
        "baseline_strategy": stress_audit["baseline_strategy"],
        "changed_assignments": stress_audit.get("changed_assignments", []),
        "metrics": {
            "frozen_on_time_rate": stress["comparison"]["frozen_metrics"]["on_time_rate"],
            "dt_on_time_rate": stress["comparison"]["decision_tree_metrics"]["on_time_rate"],
            "llm_on_time_rate": stress["comparison"]["llm_metrics"]["on_time_rate"],
            "avg_delay_seconds": stress["comparison"]["decision_tree_metrics"]["average_delay_seconds"],
        },
        "audit_ref": "outputs/real_data_codex_stress_demo/audit.json",
        "decision_tree": stress["decision_tree"],
        "codex_llm": stress["codex_llm"],
        "invocation": stress["llm_invocation"],
    }
    # The browser catalog is intentionally Codex-only. The ordinary control is
    # retained in the offline SQLite evidence store, but is not a demo card.
    cards = [stress_case]
    return {
        "schema_version": 1,
        "source": {
            "plan": audit["inputs"]["plan"],
            "crane": audit["inputs"]["crane"],
            "plan_total": audit["plan"]["total_rows"],
            "plan_eligible": audit["plan"]["eligible_rows"],
            "crane_history_rows": audit["crane"]["source_rows_scanned"],
            "real_crane_ids": audit["real_crane_ids"],
            "ladle_count": audit["scenario"]["ladles"],
        },
        "baseline": {
            "total": len(heats),
            "assigned": sum(item["action"] == "assign" for item in heats),
            "success_rate": audit["metrics"]["配包成功率"],
            "metrics": audit["metrics"],
            "time_range": {"min_pour_at": minimum, "max_pour_at": maximum, "min_pour_at_iso": _iso(minimum), "max_pour_at_iso": _iso(maximum)},
            "heats": heats,
        },
        "real_replay": {
            "scenario_count": comparison["summary"]["total_scenarios"],
            "affected_heat_count": comparison["summary"]["total_affected_heats"],
            "dt_success_rate": comparison["summary"]["dt_success_rate"],
            "llm_attempted": comparison["summary"]["llm_attempted"],
            "by_kind": comparison_cases,
        },
        "cards": cards,
        "stress_audit": stress,
    }


if __name__ == "__main__":
    payload = json.dumps(build(), ensure_ascii=False, indent=2) + "\n"
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    ARCHIVE_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_OUTPUT_PATH.write_text(payload, encoding="utf-8")
    FRONTEND_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_OUTPUT_PATH.write_text(payload, encoding="utf-8")
    print(OUTPUT_PATH)
