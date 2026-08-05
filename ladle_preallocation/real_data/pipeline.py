"""Run the only supported method: decision-tree allocation on real PLAN/CRANE data."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ladle_preallocation.decision_tree import allocate, validate_output
from ladle_preallocation.decision_tree.config import TREE_VERSION
from ladle_preallocation.evaluation.metrics import FORMULAS, evaluate
from ladle_preallocation.real_data.reader import parse_production_time, read_plan
from ladle_preallocation.real_data.scenario import build_scenario_from_real_snapshots
from ladle_preallocation.real_data.xlsx_stream import read_latest_online_cranes_stream

DEFAULT_PLAN = Path("data/PLAN(1)_预配包输入.xlsx")
DEFAULT_CRANE = Path("data/CRANE.xlsx")
DEFAULT_OUTPUT = Path("outputs")


def plan_key(record: dict[str, Any]) -> str:
    return f"{str(record.get('heat_id') or '').strip()}::{str(record.get('plan_sequence') or '').strip()}"


def _dominant_month(records: list[dict[str, Any]]) -> str:
    months = Counter(
        str(row.get("tap_finish_at") or "")[:7]
        for row in records
        if len(str(row.get("tap_finish_at") or "")) >= 7
    )
    if not months:
        raise ValueError("PLAN 中没有可解析的出钢终了日期")
    return months.most_common(1)[0][0]


def filter_plan_records(
    records: list[dict[str, Any]], month: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, str], str]:
    """Keep mapped rows in the selected month and explain every exclusion."""
    target_month = month or _dominant_month(records)
    included: list[dict[str, Any]] = []
    excluded: dict[str, str] = {}
    for row in records:
        key = plan_key(row)
        if not row.get("heat_id") or row.get("plan_sequence") in (None, ""):
            excluded[key] = "主键缺失"
            continue
        if row.get("location_mapping_status") not in (None, "", "已匹配"):
            excluded[key] = f"位置无效：{row.get('location_mapping_status')}"
            continue
        timestamp, invalid = parse_production_time(row.get("tap_finish_at"))
        if invalid or timestamp is None:
            excluded[key] = "出钢终了时间无效"
            continue
        if not str(row.get("tap_finish_at")).startswith(target_month):
            excluded[key] = f"不在评测月份 {target_month}"
            continue
        included.append(row)
    return included, excluded, target_month


def _time_range(records: list[dict[str, Any]]) -> tuple[float, float]:
    values: list[float] = []
    for row in records:
        for field in ("tap_finish_at", "ladle_arrival_at", "ladle_pour_start_at"):
            timestamp, invalid = parse_production_time(row.get(field))
            if not invalid and timestamp is not None:
                values.append(timestamp)
    if not values:
        raise ValueError("筛选后的 PLAN 没有可解析时间")
    return min(values), max(values)


def _serialize(value: Any) -> Any:
    if isinstance(value, tuple):
        return list(value)
    raise TypeError(type(value).__name__)


def _scenario_heat_ids(records: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in records:
        raw_heat = str(row.get("heat_id") or row.get("manufacturing_order") or "unknown")
        sequence = row.get("plan_sequence")
        result[plan_key(row)] = f"{raw_heat}-{sequence}" if sequence not in (None, "") else raw_heat
    return result


def run_pipeline(
    plan_path: Path = DEFAULT_PLAN,
    crane_path: Path = DEFAULT_CRANE,
    output_dir: Path = DEFAULT_OUTPUT,
    month: str | None = None,
) -> dict[str, Any]:
    """Allocate eligible heats and write the auditable JSON and summary outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_records = read_plan(plan_path)
    eligible, excluded, selected_month = filter_plan_records(plan_records, month)
    start_at, end_at = _time_range(eligible)
    snapshots, stream_stats = read_latest_online_cranes_stream(crane_path, start_at, end_at)
    if not snapshots:
        raise RuntimeError("PLAN 时间范围内未找到真实在线行车，停止分配")

    heats, ladles, cranes = build_scenario_from_real_snapshots(eligible, snapshots)
    snapshot_ids = {str(row["crane_id"]) for row in snapshots}
    if {str(row["crane_id"]) for row in cranes} != snapshot_ids:
        raise RuntimeError("场景行车编号与 CRANE 快照来源不一致")

    assignments = validate_output(heats, ladles, cranes, allocate(heats, ladles, cranes))
    if any(row.get("crane_id") and str(row["crane_id"]) not in snapshot_ids for row in assignments):
        raise RuntimeError("决策树结果包含无法追溯的行车编号")

    assignment_by_heat = {str(row["heat_id"]): row for row in assignments}
    heat_by_id = {str(row["heat_id"]): row for row in heats}
    scenario_heat_by_key = _scenario_heat_ids(eligible)
    assignment_rows: list[dict[str, Any]] = []
    assignment_by_key: dict[str, dict[str, Any]] = {}
    for record in eligible:
        key = plan_key(record)
        scenario_heat_id = scenario_heat_by_key[key]
        assignment = assignment_by_heat[scenario_heat_id]
        heat = heat_by_id[scenario_heat_id]
        arrival = assignment.get("expected_arrival_seconds")
        wait_seconds = None if arrival is None else round(
            max(0.0, float(arrival) - float(heat.get("window_start", 0) or 0)), 3
        )
        row = {
            "plan_key": key,
            "heat_id": record.get("heat_id"),
            "plan_sequence": record.get("plan_sequence"),
            "algorithm": "decision_tree",
            "status": "已分配" if assignment.get("action") == "assign" else (
                "人工复核" if assignment.get("action") == "request_human_review" else "未分配"
            ),
            "ladle_id": assignment.get("ladle_id"),
            "crane_id": assignment.get("crane_id"),
            "expected_wait_seconds": wait_seconds,
            "grade_match": assignment.get("grade_match"),
            "violations": ";".join(assignment.get("violations") or ()),
            "reason": assignment.get("reason"),
            "decision_path": ";".join(assignment.get("decision_path") or ()),
        }
        assignment_rows.append(row)
        assignment_by_key[key] = row

    plan_output_rows: list[dict[str, Any]] = []
    for record in plan_records:
        key = plan_key(record)
        row = assignment_by_key.get(key)
        if row and row["status"] == "已分配":
            result = f"方法=决策树；状态=已分配；钢包={row['ladle_id']}；行车={row['crane_id']}"
            status = "已分配"
        elif row:
            result = f"方法=决策树；状态={row['status']}；原因={row.get('reason') or '无可行候选'}"
            status = row["status"]
        else:
            reason = excluded.get(key, "炉次主键未匹配")
            result = f"状态=未纳入；原因={reason}"
            status = "未纳入"
        plan_output_rows.append({"plan_key": key, "status": status, "result": result})

    metrics = evaluate(heats, ladles, cranes, assignments)
    crane_assignment_counts = dict(
        Counter(str(row["crane_id"]) for row in assignments if row.get("action") == "assign")
    )
    success = sum(row.get("action") == "assign" for row in assignments)
    audit = {
        "algorithm": "decision_tree",
        "tree_version": TREE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {"plan": str(plan_path), "crane": str(crane_path)},
        "selected_month": selected_month,
        "time_range": [
            datetime.fromtimestamp(start_at, timezone.utc).isoformat(),
            datetime.fromtimestamp(end_at, timezone.utc).isoformat(),
        ],
        "plan": {
            "total_rows": len(plan_records),
            "eligible_rows": len(eligible),
            "excluded_rows": len(excluded),
            "exclusion_counts": dict(Counter(excluded.values())),
        },
        "crane": stream_stats.as_dict(),
        "real_crane_ids": sorted(snapshot_ids),
        "crane_snapshots": snapshots,
        "scenario": {"heats": len(heats), "ladles": len(ladles), "cranes": len(cranes)},
        "assumptions": {
            "speed": "CRANE 缺失时统一使用 2 m/s",
            "max_load": "CRANE 缺失时统一使用 300 t",
            "run_range": "CRANE 缺失时统一使用 PLAN 坐标 0-48000",
            "safe_distance": "CRANE 缺失时统一使用 10 m（换算为 10000 PLAN 坐标单位）",
            "ladle_release": "完成本次转运后立即释放，可参与下一炉次预分配",
            "grade_compatibility": "不作为硬约束，仅用于候选评分和结果观察",
        },
        "metric_formulas": FORMULAS,
        "metrics": metrics,
        "crane_assignment_counts": crane_assignment_counts,
        "assignments": assignments,
        "assignment_rows": assignment_rows,
        "plan_output_rows": plan_output_rows,
    }
    audit_path = output_dir / "decision_tree_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=_serialize), encoding="utf-8")

    success_rate = success / len(assignments) if assignments else 0.0
    summary = [
        "# 决策树预配包结果",
        "",
        f"- PLAN：{len(eligible)}/{len(plan_records)} 条纳入评测",
        f"- CRANE：扫描 {stream_stats.source_rows_scanned} 条历史，提取 {len(snapshots)} 台真实在线行车",
        f"- 真实行车编号：{', '.join(sorted(snapshot_ids))}",
        f"- 成功分配：{success}/{len(assignments)}（{success_rate:.2%}）",
        f"- 规则违反：{metrics['规则违反次数']}",
        f"- 平均等待：{metrics['平均等待时间(秒)']:.3f} 秒",
        "- 行车作业分布：" + "，".join(f"{key}={value}" for key, value in sorted(crane_assignment_counts.items())),
        "- 边界：本结果为处理后数据的离线回放，不代表现场实时生产验收。",
    ]
    (output_dir / "result_summary.md").write_text("\n".join(summary), encoding="utf-8")
    return {
        "algorithm": "decision_tree",
        "audit": str(audit_path),
        "success": success,
        "heats": len(assignments),
        "metrics": metrics,
        "real_crane_ids": sorted(snapshot_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run decision-tree allocation on real PLAN/CRANE data.")
    parser.add_argument("--plan-path", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--crane-path", type=Path, default=DEFAULT_CRANE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--month", help="Evaluation month in YYYY-MM; defaults to PLAN dominant month")
    args = parser.parse_args()
    print(json.dumps(run_pipeline(args.plan_path, args.crane_path, args.output_dir, args.month), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
