"""Machine-checkable subset of the ladle rules in the functional specification."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ladle_preallocation.data_modeling.grades import grade_matches


@dataclass(frozen=True)
class RuleEvaluation:
    violations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def feasible(self) -> bool:
        return not self.violations


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _required_argon(heat: dict[str, Any]) -> tuple[bool, bool]:
    route = str(heat.get("refining_route", "")).upper()
    return bool(heat.get("requires_north_argon") or "LF" in route or "LATS" in route), bool(heat.get("requires_south_argon") or "LF" in route)


def evaluate_ladle_rules(heat: dict[str, Any], ladle: dict[str, Any]) -> RuleEvaluation:
    """Evaluate documented red/yellow ladle rules against available fields."""
    red: list[str] = []
    yellow: list[str] = []
    if not grade_matches(heat.get("required_grade"), ladle.get("grade")):
        if heat.get("enforce_grade"):
            red.append("grade")
        else:
            yellow.append("grade_not_enforced")
    state = str(ladle.get("state", "")).lower()
    allowed_states = {str(x).lower() for x in heat.get("allowed_ladle_states", [])}
    if state in {"offline", "unavailable", "maintenance", "scrapped"}:
        red.append("ladle_state")
    elif allowed_states and state and state not in allowed_states:
        red.append("ladle_state")
    elif not state:
        yellow.append("missing.ladle_state")
    age = _number(ladle.get("age_seconds"))
    max_age = _number(ladle.get("max_age_seconds"))
    if age is not None and max_age is not None and age > max_age:
        if heat.get("enforce_ladle_age"):
            red.append("age")
        else:
            yellow.append("age_not_enforced")
    weight = _number(ladle.get("empty_ladle_weight_tonnes"))
    lower = _number(heat.get("min_empty_ladle_weight_tonnes", 127.0))
    upper = _number(heat.get("max_empty_ladle_weight_tonnes", 155.0))
    if weight is None:
        yellow.append("missing.empty_ladle_weight")
    elif (lower is not None and weight < lower) or (upper is not None and weight > upper):
        if heat.get("enforce_empty_ladle_weight"):
            red.append("empty_ladle_weight")
        else:
            yellow.append("empty_ladle_weight_not_enforced")
    north_required, south_required = _required_argon(heat)
    for field, required in (("argon_north_ok", north_required), ("argon_south_ok", south_required)):
        if required and ladle.get(field) is False:
            red.append(field)
        elif required and ladle.get(field) is None:
            yellow.append(f"missing.{field}")
    if heat.get("forbid_major_repair") and str(ladle.get("repair_type", "")).lower() in {"major", "full"}:
        red.append("repair_type")
    if heat.get("forbidden_previous_grade") and str(ladle.get("previous_steel_grade", "")).upper() == str(heat["forbidden_previous_grade"]).upper():
        red.append("previous_steel_grade")
    return RuleEvaluation(tuple(red), tuple(yellow))
