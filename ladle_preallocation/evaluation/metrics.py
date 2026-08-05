"""Metrics for decision-tree assignment results."""
from __future__ import annotations

from statistics import pvariance
from typing import Any

FORMULAS = {"配包成功率": "成功指派炉次 / 总炉次", "等级匹配率": "等级满足的成功指派 / 成功指派", "天车负载均衡方差": "Var(各行车最终负载)", "平均等待时间(秒)": "mean(预计到达时刻 - 时间窗开始)", "包龄利用率": "mean(已指派包龄 / 包龄上限)", "规则违反次数": "所有指派 violations 的总数"}


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
