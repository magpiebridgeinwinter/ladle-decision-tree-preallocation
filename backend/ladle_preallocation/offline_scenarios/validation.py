"""Scenario-level validation layered on the shared assignment validator."""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any

from ladle_preallocation.decision_tree.validation import validate_output


@dataclass(frozen=True)
class ScenarioValidationPolicy:
    allowed_routes_by_heat: dict[str, tuple[str, ...]] = field(default_factory=dict)
    blocked_route_tokens: tuple[str, ...] = ()
    distinct_cranes: bool = False
    distinct_ladles: bool = False


def _invalidate(row: dict[str, Any], violation: str) -> None:
    violations = set(row.get("violations") or ())
    violations.add(violation)
    row["action"] = "unassigned"
    row["ladle_id"] = None
    row["crane_id"] = None
    row["expected_arrival_seconds"] = None
    row["grade_match"] = False
    row["violations"] = tuple(sorted(violations))
    row["reason"] = "场景约束终检失败：" + ",".join(row["violations"])


class ScenarioValidator:
    """Apply core constraints and explicit controlled-scenario policies."""

    def __init__(self, policy: ScenarioValidationPolicy | None = None) -> None:
        self.policy = policy or ScenarioValidationPolicy()

    def __call__(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        assignments: list[Any],
    ) -> list[dict[str, Any]]:
        rows = validate_output(heats, ladles, cranes, assignments)
        return self._apply_policy(rows)

    def _apply_policy(self, core_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = deepcopy(core_rows)
        seen_cranes: set[str] = set()
        seen_ladles: set[str] = set()
        for row in rows:
            if row.get("action") != "assign":
                continue
            heat_id = str(row["heat_id"])
            allowed_routes = self.policy.allowed_routes_by_heat.get(heat_id)
            route = str(row.get("refining_route") or "").strip()
            if allowed_routes:
                if not route:
                    _invalidate(row, "missing_refining_route")
                    continue
                if route not in allowed_routes:
                    _invalidate(row, "refining_route_not_allowed")
                    continue
            if route and any(token and token in route for token in self.policy.blocked_route_tokens):
                _invalidate(row, "blocked_refining_facility")
                continue
            crane_id = str(row.get("crane_id") or "")
            ladle_id = str(row.get("ladle_id") or "")
            if self.policy.distinct_cranes and crane_id in seen_cranes:
                _invalidate(row, "overlapping_crane_reservation")
                continue
            if self.policy.distinct_ladles and ladle_id in seen_ladles:
                _invalidate(row, "overlapping_ladle_reservation")
                continue
            seen_cranes.add(crane_id)
            seen_ladles.add(ladle_id)
        return rows

    def audit(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        assignments: list[Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        core_rows = validate_output(heats, ladles, cranes, assignments)
        rows = self._apply_policy(core_rows)
        expected_ids = {str(item["heat_id"]) for item in heats}
        returned_ids = {str(item.get("heat_id", "")) for item in assignments}
        complete = len(assignments) == len(expected_ids) and returned_ids == expected_ids
        shared_valid = all(row.get("action") == "assign" for row in core_rows)
        all_valid = complete and all(row.get("action") == "assign" for row in rows)
        checks = [
            {"check_code": "complete_assignment_set", "passed": complete, "details": {"expected": sorted(expected_ids), "returned": sorted(returned_ids)}},
            {"check_code": "shared_hard_constraints", "passed": shared_valid, "details": {"actions": {str(row["heat_id"]): row["action"] for row in core_rows}}},
            {"check_code": "scenario_policy", "passed": all_valid, "details": {"actions": {str(row["heat_id"]): row["action"] for row in rows}, "policy": {"allowed_routes_by_heat": self.policy.allowed_routes_by_heat, "blocked_route_tokens": self.policy.blocked_route_tokens, "distinct_cranes": self.policy.distinct_cranes, "distinct_ladles": self.policy.distinct_ladles}}},
        ]
        return rows, checks
