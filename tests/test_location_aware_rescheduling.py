from __future__ import annotations

import unittest

from ladle_preallocation.disturbance import DisturbanceSpec, inject_disturbance
from ladle_preallocation.disturbance.catalog import DISTURBANCE_KINDS
from ladle_preallocation.response import ResponsePath, TieredResponseController


def _fixture() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    heats = [
        {"heat_id": "H1", "required_grade": "5", "window_start": 0.0, "window_end": 300.0, "pour_at": 300.0, "refining_route": "A2"},
        {"heat_id": "H2", "required_grade": "5", "window_start": 0.0, "window_end": 500.0, "pour_at": 500.0, "refining_route": "R0"},
    ]
    ladles = [
        {"ladle_id": "L1", "grade": "5", "position_m": 1000.0, "weight_tonnes": 80.0, "age_seconds": 100.0},
        {"ladle_id": "L2", "grade": "5", "position_m": 2000.0, "weight_tonnes": 80.0, "age_seconds": 100.0},
    ]
    cranes = [{"crane_id": "C1", "position_m": 0.0, "current_load_tonnes": 0.0, "max_load_tonnes": 300.0, "speed_mps": 1000.0, "safe_distance_m": 0.0, "limit_0_m": 0.0, "limit_1_m": 5000.0}]
    assignments = [{"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1", "action": "assign"}, {"heat_id": "H2", "ladle_id": "L2", "crane_id": "C1", "action": "assign"}]
    return heats, ladles, cranes, assignments


class LocationAwareReschedulingTests(unittest.TestCase):
    def test_all_catalog_events_emit_an_auditable_state_delta(self) -> None:
        for kind in DISTURBANCE_KINDS:
            heats, ladles, cranes, assignments = _fixture()
            resource_id = "C1" if kind.startswith("crane") or kind in {"transport_corridor_blocked", "compound_disturbance"} else "L1" if kind.startswith("ladle") else "A2" if kind in {"facility_unavailable", "argon_station_unavailable", "refining_route_change"} else "H1"
            metadata = {"affected_heat_ids": ["H1", "H2"] if kind == "compound_disturbance" else ["H1"]} if kind not in {"crane_offline", "ladle_unavailable", "facility_unavailable"} else {}
            scenario = inject_disturbance(DisturbanceSpec(kind, resource_id, occurred_at=100.0, metadata=metadata), heats, ladles, cranes, assignments)
            with self.subTest(kind=kind):
                self.assertTrue(scenario.audit["event_state_deltas"])
                self.assertIn("impact_scope", scenario.audit)

    def test_emergency_three_way_does_not_call_llm(self) -> None:
        heats, ladles, cranes, assignments = _fixture()
        calls: list[bool] = []
        scenario = inject_disturbance(DisturbanceSpec("crane_offline", "C1", occurred_at=250.0), heats, ladles, cranes, assignments)
        comparison = TieredResponseController(lambda *_args, **_kwargs: calls.append(True) or (True, [])).run_three_way(scenario)
        self.assertNotEqual(comparison.decision_tree.path, ResponsePath.DECISION_TREE_SUCCESS)
        self.assertIsNone(comparison.llm_react)
        self.assertEqual(calls, [])

    def test_llm_context_contains_local_position_constraints(self) -> None:
        heats, ladles, cranes, assignments = _fixture()
        captured: dict = {}

        def llm(_heats, _ladles, _cranes, **kwargs):
            captured.update(kwargs)
            return False, []

        scenario = inject_disturbance(DisturbanceSpec("crane_offline", "C1", occurred_at=100.0), heats, ladles, cranes, assignments)
        TieredResponseController(llm).handle_disturbance(scenario)
        self.assertIn("failure_context", captured)
        self.assertIn("local_constraints", captured["failure_context"])
        self.assertEqual(captured["failure_context"]["affected_heat_ids"], ["H1", "H2"])


if __name__ == "__main__":
    unittest.main()
