"""Normalize and independently validate decision-tree output."""
from __future__ import annotations

from typing import Any

from ladle_preallocation.data_modeling.grades import grade_matches
from ladle_preallocation.decision_tree.constraints import validate_assignment


def _record(value: Any) -> dict[str, Any]:
    return value.as_dict() if hasattr(value, "as_dict") else dict(value)


def validate_output(
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    assignments: list[Any],
) -> list[dict[str, Any]]:
    """Return one traceable, constraint-checked result for every heat."""
    by_ladle = {str(item["ladle_id"]): item for item in ladles}
    by_crane = {str(item["crane_id"]): item for item in cranes}
    supplied = {str(_record(item).get("heat_id")): _record(item) for item in assignments}
    base_loads = {str(item["crane_id"]): float(item.get("current_load_tonnes", 0) or 0) for item in cranes}
    result: list[dict[str, Any]] = []
    for heat in heats:
        heat_id = str(heat["heat_id"])
        row = supplied.get(heat_id, {"heat_id": heat_id, "reason": "决策树未返回该炉次"})
        ladle_id = str(row["ladle_id"]) if row.get("ladle_id") else None
        crane_id = str(row["crane_id"]) if row.get("crane_id") else None
        violations = list(row.get("violations") or ())
        if ladle_id and ladle_id not in by_ladle:
            violations.append("untraceable_ladle")
        if crane_id and crane_id not in by_crane:
            violations.append("untraceable_crane")
        if ladle_id and crane_id and not violations:
            violations.extend(validate_assignment(heat, by_ladle[ladle_id], by_crane[crane_id], base_loads))
        successful = bool(ladle_id and crane_id and not violations)
        if successful:
            grade_match = grade_matches(heat.get("required_grade"), by_ladle[ladle_id].get("grade"))
            reason = row.get("reason", "规则决策树")
        else:
            ladle_id = crane_id = None
            grade_match = False
            reason = (
                "硬约束终检失败：" + ",".join(sorted(set(violations)))
                if violations
                else row.get("reason", "未分配")
            )
        result.append({
            **row,
            "algorithm": "decision_tree",
            "heat_id": heat_id,
            "ladle_id": ladle_id,
            "crane_id": crane_id,
            "action": "assign" if successful else (
                "request_human_review" if row.get("action") == "request_human_review" else "unassigned"
            ),
            "reason": reason,
            "violations": tuple(sorted(set(violations))),
            "grade_match": grade_match,
            "expected_arrival_seconds": row.get("expected_arrival_seconds") if successful else None,
        })
    return result
