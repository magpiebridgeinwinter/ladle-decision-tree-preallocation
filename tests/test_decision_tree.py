from __future__ import annotations

import unittest

from ladle_preallocation.decision_tree import allocate, validate_output


def scenario() -> tuple[list[dict], list[dict], list[dict]]:
    heats = [
        {"heat_id": "H1", "required_grade": "1", "window_start": 0, "window_end": 100, "priority": 0},
        {"heat_id": "H2", "required_grade": "4", "window_start": 10, "window_end": 110, "priority": 0},
    ]
    ladles = [
        {"ladle_id": "L1", "grade": "1", "weight_tonnes": 10, "empty_ladle_weight_tonnes": 130, "position_m": 0, "age_seconds": 0, "max_age_seconds": 10},
        {"ladle_id": "L2", "grade": "4", "weight_tonnes": 10, "empty_ladle_weight_tonnes": 130, "position_m": 100, "age_seconds": 0, "max_age_seconds": 10},
    ]
    cranes = [
        {"crane_id": "1170", "current_load_tonnes": 0, "max_load_tonnes": 300, "position_m": 0, "speed_mps": 10, "safe_distance_m": 0, "limit_0_m": 0, "limit_1_m": 100},
        {"crane_id": "3170", "current_load_tonnes": 0, "max_load_tonnes": 300, "position_m": 100, "speed_mps": 10, "safe_distance_m": 0, "limit_0_m": 0, "limit_1_m": 100},
    ]
    return heats, ladles, cranes


class DecisionTreeTests(unittest.TestCase):
    def test_uses_crane_positions_and_returns_explainable_paths(self) -> None:
        heats, ladles, cranes = scenario()
        rows = allocate(heats, ladles, cranes)
        self.assertEqual([row.crane_id for row in rows], ["1170", "3170"])
        self.assertTrue(all(row.action == "assign" for row in rows))
        self.assertTrue(all("crane_distance_and_workload:scored" in row.decision_path for row in rows))

    def test_missing_required_input_requests_review(self) -> None:
        heats, ladles, cranes = scenario()
        row = allocate([{**heats[0], "required_grade": None}], ladles, cranes)[0]
        self.assertEqual(row.action, "request_human_review")
        self.assertIsNone(row.ladle_id)

    def test_hard_constraint_rejects_unreachable_ladle(self) -> None:
        heats, ladles, cranes = scenario()
        row = allocate([heats[0]], [{**ladles[0], "position_m": 200}], cranes)[0]
        self.assertIsNone(row.ladle_id)
        self.assertIn("x_limit", row.reason)

    def test_grade_is_observed_but_not_a_hard_constraint(self) -> None:
        heats, ladles, cranes = scenario()
        rows = validate_output([heats[0]], [{**ladles[0], "grade": "UNKNOWN"}], [cranes[0]], allocate([heats[0]], [{**ladles[0], "grade": "UNKNOWN"}], [cranes[0]]))
        self.assertEqual(rows[0]["action"], "assign")
        self.assertFalse(rows[0]["grade_match"])

    def test_untraceable_crane_is_rejected_by_final_validation(self) -> None:
        heats, ladles, cranes = scenario()
        rows = validate_output([heats[0]], [ladles[0]], [cranes[0]], [{"heat_id": "H1", "ladle_id": "L1", "crane_id": "C01"}])
        self.assertIsNone(rows[0]["crane_id"])
        self.assertIn("untraceable_crane", rows[0]["violations"])


if __name__ == "__main__":
    unittest.main()
