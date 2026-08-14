"""Metrics for decision-tree assignment results."""
from __future__ import annotations

from statistics import pvariance
from typing import Any

FORMULAS = {"配包成功率": "成功指派炉次 / 总炉次", "等级匹配率": "等级满足的成功指派 / 成功指派", "天车负载均衡方差": "Var(各行车最终负载)", "平均等待时间(秒)": "mean(预计到达时刻 - 时间窗开始)", "包龄利用率": "mean(已指派包龄 / 包龄上限)", "规则违反次数": "所有指派 violations 的总数"}

PATH_METRIC_FORMULAS = {
    "on_time_rate": "on-time assignments / all heats",
    "priority_on_time": "priority-weighted on-time assignments / total priority",
    "average_delay_seconds": "mean(max(arrival - window_end, 0))",
    "max_delay_seconds": "max(max(arrival - window_end, 0))",
    "changed_heats": "reschedulable heats whose ladle/crane mapping changed",
    "human_review_rate": "human-review/Frozen signal / all heats",
    "rule_violations": "sum of assignment hard-constraint violations",
    "decision_seconds": "measured response decision time",
}


def evaluate_path(
    heats: list[dict[str, Any]],
    baseline_assignments: list[dict[str, Any]],
    response_assignments: list[dict[str, Any]],
    reschedulable_heat_ids: list[str] | None = None,
    human_review_required: bool = False,
    decision_seconds: float = 0.0,
) -> dict[str, float | int]:
    """Return the PRD's uniform metrics for one response branch."""
    heat_map = {str(heat["heat_id"]): heat for heat in heats}
    baseline = {str(row.get("heat_id")): row for row in baseline_assignments}
    response = {str(row.get("heat_id")): row for row in response_assignments}
    rows = [response.get(heat_id, {"heat_id": heat_id, "action": "unassigned"}) for heat_id in heat_map]
    delays: list[float] = []
    on_time = 0
    weighted_on_time = 0.0
    total_weight = 0.0
    for heat_id, heat in heat_map.items():
        row = response.get(heat_id, {})
        priority = float(heat.get("priority", 1) or 1)
        total_weight += priority
        arrival = row.get("expected_arrival_seconds")
        deadline = heat.get("window_end")
        valid_assignment = row.get("action") == "assign" and arrival is not None
        delay = max(0.0, float(arrival) - float(deadline)) if valid_assignment and deadline is not None else (0.0 if valid_assignment else float(max(0.0, float(deadline or 0))))
        delays.append(delay)
        if valid_assignment and delay == 0.0:
            on_time += 1
            weighted_on_time += priority
    selected = set(reschedulable_heat_ids or heat_map)
    changed = sum(
        (baseline.get(heat_id, {}).get("ladle_id"), baseline.get(heat_id, {}).get("crane_id"))
        != (response.get(heat_id, {}).get("ladle_id"), response.get(heat_id, {}).get("crane_id"))
        for heat_id in selected
    )
    return {
        "on_time_rate": on_time / len(heat_map) if heat_map else 0.0,
        "priority_on_time": weighted_on_time / total_weight if total_weight else 0.0,
        "average_delay_seconds": sum(delays) / len(delays) if delays else 0.0,
        "max_delay_seconds": max(delays, default=0.0),
        "changed_heats": changed,
        "human_review_rate": (1.0 / len(heat_map)) if human_review_required and heat_map else 0.0,
        "rule_violations": sum(len(row.get("violations") or ()) for row in rows),
        "decision_seconds": max(0.0, float(decision_seconds)),
    }


def evaluate(heats: list[dict], ladles: list[dict], cranes: list[dict], assignments: list[Any]) -> dict[str, float | int]:
    by_ladle = {x["ladle_id"]: x for x in ladles}
    by_heat = {x["heat_id"]: x for x in heats}
    records = [x.as_dict() if hasattr(x, "as_dict") else x for x in assignments]
    success = [x for x in records if x.get("ladle_id")]
    loads = {x["crane_id"]: float(x.get("current_load_tonnes", 0)) for x in cranes}
    for record in success:
        loads[record["crane_id"]] += float(by_ladle[record["ladle_id"]].get("weight_tonnes", 0))
    waits = [float(x["expected_arrival_seconds"]) - float(by_heat[x["heat_id"]].get("window_start", 0)) for x in success]
    utilization = [
        float(by_ladle[x["ladle_id"]].get("age_seconds", 0)) / float(max_age)
        for x in success
        if (max_age := by_ladle[x["ladle_id"]].get("max_age_seconds")) not in (None, "", 0)
    ]
    return {"配包成功率": len(success) / len(heats) if heats else 0, "等级匹配率": sum(bool(x.get("grade_match")) for x in success) / len(success) if success else 0, "天车负载均衡方差": pvariance(loads.values()) if loads else 0, "平均等待时间(秒)": sum(waits) / len(waits) if waits else 0, "包龄利用率": sum(utilization) / len(utilization) if utilization else 0, "规则违反次数": sum(len(x.get("violations", [])) for x in records)}


def markdown_metrics(metrics: dict[str, float | int]) -> str:
    rows = ["| 指标 | 公式 | 本次值 |", "| --- | --- | --- |"]
    for name, formula in FORMULAS.items():
        value = metrics[name]
        shown = f"{value:.2%}" if name in {"配包成功率", "等级匹配率", "包龄利用率"} else f"{value:.2f}" if isinstance(value, float) else str(value)
        rows.append(f"| {name} | {formula} | {shown} |")
    return "\n".join(rows)
