from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from ladle_preallocation.disturbance.catalog import DISTURBANCE_CATALOG
from ladle_preallocation.offline_scenarios import ScenarioRepository, build_scenario_records, write_database


ROOT = Path(__file__).resolve().parents[1]
SOURCE_AUDIT = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"


class OfflineScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = build_scenario_records(SOURCE_AUDIT)

    def test_exactly_two_categories_and_complete_catalog(self):
        self.assertEqual({row["category"] for row in self.records}, {"decision_tree_control", "llm_fallback_stress"})
        stress = [row for row in self.records if row["category"] == "llm_fallback_stress"]
        self.assertEqual(len(stress), len(DISTURBANCE_CATALOG))
        self.assertEqual({row["disturbance_kind"] for row in stress}, set(DISTURBANCE_CATALOG))

    def test_control_uses_decision_tree_without_llm(self):
        control = next(row for row in self.records if row["category"] == "decision_tree_control")
        self.assertTrue(control["responses"]["decision_tree"]["success"])
        self.assertIsNone(control["responses"]["llm"])
        self.assertFalse(control["audit"]["llm_attempted"])

    def test_every_stress_scenario_proves_llm_fallback(self):
        for row in self.records:
            if row["category"] != "llm_fallback_stress":
                continue
            with self.subTest(kind=row["disturbance_kind"]):
                self.assertFalse(row["responses"]["decision_tree"]["success"])
                self.assertLess(row["responses"]["decision_tree"]["num_assigned"], len(row["inputs"]["heats"]))
                self.assertTrue(row["audit"]["llm_attempted"])
                self.assertFalse(row["audit"]["external_api_called"])
                self.assertTrue(row["responses"]["llm"]["success"])
                self.assertEqual(row["responses"]["llm"]["num_assigned"], len(row["inputs"]["heats"]))
                self.assertTrue(all(check["passed"] for check in row["validations"]["llm"]))

    def test_facility_scenarios_persist_validated_alternate_routes(self):
        row = next(item for item in self.records if item["disturbance_kind"] == "facility_unavailable")
        routes = {item["heat_id"]: item["refining_route"] for item in row["responses"]["llm"]["assignments"]}
        self.assertEqual(routes, {"AQ0640E1-300703": "A1", "DU3851D1-300667": "R0"})
        self.assertTrue(all(item["action"] == "assign" for item in row["responses"]["llm"]["assignments"]))

    def test_event_state_changes_are_stored_for_concrete_failures(self):
        for kind in DISTURBANCE_CATALOG:
            row = next(
                item
                for item in self.records
                if item["category"] == "llm_fallback_stress" and item["disturbance_kind"] == kind
            )
            deltas = row["audit"]["controlled_overrides"]["event_state_deltas"]
            self.assertTrue(deltas, kind)
            self.assertTrue(all(delta["before"] != delta["after"] for delta in deltas))

    def test_sqlite_round_trip_and_secret_absence(self):
        with tempfile.TemporaryDirectory() as directory:
            database = write_database(self.records, Path(directory) / "scenarios.sqlite3")
            repository = ScenarioRepository(database)
            summary = repository.summary()
            self.assertEqual(summary["scenario_count"], 1 + len(DISTURBANCE_CATALOG))
            self.assertEqual(summary["verified_llm_fallback_count"], len(DISTURBANCE_CATALOG))
            detail = repository.get_scenario("llm_fallback_020_compound_disturbance")
            self.assertIsNotNone(detail)
            self.assertTrue(detail["llm_success"])
            serialized = json.dumps(detail, ensure_ascii=False).lower()
            self.assertNotIn("api_key", serialized)
            self.assertNotIn("authorization", serialized)

    def test_routes_are_source_backed_assets(self):
        for row in self.records:
            routes = {item["asset_id"] for item in row["assets"] if item["asset_type"] == "route"}
            self.assertTrue({"A1", "A2", "R0", "R1"}.issubset(routes))

    def test_primary_crane_replay_uses_real_31_heat_window(self):
        row = next(item for item in self.records if item["category"] == "llm_fallback_stress" and item["disturbance_kind"] == "crane_offline")
        self.assertEqual(len(row["inputs"]["heats"]), 31)
        self.assertFalse(row["responses"]["decision_tree"]["success"])
        self.assertEqual(row["responses"]["decision_tree"]["num_assigned"], 30)
        self.assertEqual(row["responses"]["llm"]["num_assigned"], 31)
        self.assertEqual(len(row["audit"]["controlled_overrides"]["offline_crane_ids"]), 1)

    def test_database_rejects_incomplete_llm_evidence(self):
        records = deepcopy(self.records)
        stress = next(row for row in records if row["category"] == "llm_fallback_stress")
        stress["responses"]["llm"]["assignments"].pop()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                write_database(records, Path(directory) / "invalid.sqlite3")

    def test_logical_records_are_reproducible(self):
        rebuilt = build_scenario_records(SOURCE_AUDIT)
        self.assertEqual(
            json.dumps(self.records, ensure_ascii=False, sort_keys=True),
            json.dumps(rebuilt, ensure_ascii=False, sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
