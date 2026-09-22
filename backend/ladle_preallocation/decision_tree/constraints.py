"""Hard constraints used by the decision-tree allocator."""
from __future__ import annotations

from typing import Any

from ladle_preallocation.data_modeling.assumptions import (
    DEFAULT_X_LOWER_LIMIT,
    DEFAULT_X_UPPER_LIMIT,
)
from ladle_preallocation.rules import evaluate_ladle_rules


def expected_arrival(heat: dict[str, Any], ladle: dict[str, Any], crane: dict[str, Any]) -> float:
    travel = abs(float(crane.get("position_m", 0)) - float(ladle.get("position_m", 0))) / max(
        float(crane.get("speed_mps", 2)), 0.1
    )
    return float(heat.get("window_start", 0) or 0) + travel


def validate_assignment(
    heat: dict[str, Any],
    ladle: dict[str, Any],
    crane: dict[str, Any],
    crane_loads: dict[str, float],
) -> list[str]:
    """Return machine-checkable violations for one ladle/crane candidate."""
    errors = list(evaluate_ladle_rules(heat, ladle).violations)
    crane_id = str(crane["crane_id"])
    weight = float(ladle.get("weight_tonnes", 0) or 0)
    if crane_loads.get(crane_id, 0) + weight > float(crane.get("max_load_tonnes", 0) or 0):
        errors.append("load")

    position = float(ladle.get("position_m", 0) or 0)
    try:
        lower = float(crane.get("limit_0_m"))
    except (TypeError, ValueError):
        lower = DEFAULT_X_LOWER_LIMIT
    try:
        upper = float(crane.get("limit_1_m"))
    except (TypeError, ValueError):
        upper = DEFAULT_X_UPPER_LIMIT
    if not lower <= position <= upper:
        errors.append("x_limit")

    if heat.get("window_end") is not None and expected_arrival(heat, ladle, crane) > float(heat["window_end"]):
        errors.append("time_window")
    for other in crane.get("active_positions", []):
        if abs(position - float(other)) < float(crane.get("safe_distance_m", 10) or 0):
            errors.append("safe_distance")
            break
    return errors
