"""Explainable ranking of feasible decision-tree candidates."""
from __future__ import annotations

from statistics import pvariance
from typing import Any, Mapping

from ladle_preallocation.data_modeling.grades import grade_matches, parse_grade
from ladle_preallocation.decision_tree.config import SCORING_WEIGHTS

DEFAULT_WEIGHTS = SCORING_WEIGHTS


def resolved_weights(weights: Mapping[str, float] | None = None) -> dict[str, float]:
    result = dict(DEFAULT_WEIGHTS)
    if weights:
        result.update({key: float(value) for key, value in weights.items() if key in result})
    total = sum(result.values())
    return {key: value / total for key, value in result.items()} if total else dict(DEFAULT_WEIGHTS)


def _grade_score(required: Any, actual: Any) -> float:
    if not grade_matches(required, actual):
        return 0.0
    required_kind, required_value = parse_grade(required)
    actual_kind, actual_value = parse_grade(actual)
    if required_kind == actual_kind == "alpha":
        return 1.0 / (1.0 + max(0, int(actual_value) - int(required_value)))
    return 1.0


def _grade_scarcity(heat: dict[str, Any], ladles: list[dict[str, Any]]) -> float:
    compatible = sum(grade_matches(heat.get("required_grade"), ladle.get("grade")) for ladle in ladles)
    return 1.0 / max(1, compatible)


def score_candidate(
    heat: dict[str, Any],
    ladle: dict[str, Any],
    crane: dict[str, Any],
    transported_loads: dict[str, float],
    ladle_pool: list[dict[str, Any]],
    weights: Mapping[str, float] | None = None,
) -> float:
    """Score a candidate after hard constraints have passed."""
    w = resolved_weights(weights)
    target_age = float(heat.get("target_age_seconds", 0) or 0)
    max_age = max(1.0, float(ladle.get("max_age_seconds", 1) or 1))
    age_score = max(0.0, 1.0 - abs(float(ladle.get("age_seconds", 0) or 0) - target_age) / max_age)
    window = max(1.0, float(heat.get("window_end", 0) or 0) - float(heat.get("window_start", 0) or 0))
    travel = abs(float(crane.get("position_m", 0) or 0) - float(ladle.get("position_m", 0) or 0)) / max(
        float(crane.get("speed_mps", 2) or 2), 0.1
    )
    window_score = max(0.0, 1.0 - travel / window)
    crane_id = str(crane["crane_id"])
    trial_loads = [
        load + (float(ladle.get("weight_tonnes", 0) or 0) if key == crane_id else 0.0)
        for key, load in transported_loads.items()
    ] or [0.0]
    balance_score = 1.0 / (1.0 + pvariance(trial_loads) / 10_000.0)
    return (
        w["grade"] * _grade_score(heat.get("required_grade"), ladle.get("grade"))
        + w["age"] * age_score
        + w["window"] * window_score
        + w["balance"] * balance_score
        + w["scarcity"] * _grade_scarcity(heat, ladle_pool)
    )
