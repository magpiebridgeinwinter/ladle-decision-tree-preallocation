from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

from ladle_preallocation.disturbance.catalog import DISTURBANCE_KINDS
from ladle_preallocation.evaluation.benchmark import (
    BenchmarkContractError,
    build_benchmark,
    load_factory_ladle_mapping,
    recommend_branches,
)
from ladle_preallocation.offline_scenarios import build_scenario_records
from ladle_preallocation.real_data.audit import load_location_aware_audit


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"
PLAN = ROOT / "data/desktop_data/PLAN(1).xlsx"


class DisturbanceSolutionBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_location_aware_audit(AUDIT)
        cls.records = build_scenario_records(AUDIT)
        cls.factory, cls.factory_metadata = load_factory_ladle_mapping(PLAN)
        cls.result = build_benchmark(cls.records, cls.source, cls.factory, cls.factory_metadata)

    def test_complete_matrix_and_primary_window(self) -> None:
        scenarios = self.result["scenarios"]
        self.assertEqual(len(scenarios), len(DISTURBANCE_KINDS))
        self.assertEqual({row["disturbance_kind"] for row in scenarios}, set(DISTURBANCE_KINDS))
        primary = next(row for row in scenarios if row["disturbance_kind"] == "crane_offline")
        self.assertEqual(primary["affected_heat_count"], 31)
        self.assertEqual(primary["scenario_size_class"], "primary_31_heat")

    def test_hard_gates_recommend_codex_for_every_stress_scenario(self) -> None:
        for scenario in self.result["scenarios"]:
            with self.subTest(scenario=scenario["scenario_id"]):
                self.assertFalse(scenario["branches"]["decision_tree"]["executable"])
                self.assertTrue(scenario["branches"]["codex"]["executable"])
                self.assertEqual(scenario["recommendation"], "codex")
                self.assertFalse(scenario["external_api_called"])

    def test_factory_denominator_and_unavailable_boundaries_are_explicit(self) -> None:
        observations = [row for scenario in self.result["scenarios"] for row in scenario["heat_results"]]
        comparable = [row for row in observations if row["factory_comparison_available"]]
        self.assertTrue(comparable)
        for scenario in self.result["scenarios"]:
            self.assertIn(scenario["factory_comparison"]["ladle"]["status"], {"available", "not_available"})
            self.assertEqual(scenario["factory_comparison"]["crane"], "not_available")
            self.assertEqual(scenario["factory_comparison"]["post_disturbance_manual_plan"], "not_available")
        self.assertEqual(self.result["factory_reference"]["comparable_field"], "preallocated_ladle")

    def test_all_branch_rows_expose_the_source_or_proposed_route(self) -> None:
        for scenario in self.result["scenarios"]:
            for row in scenario["heat_results"]:
                with self.subTest(scenario=scenario["scenario_id"], heat=row["heat_id"]):
                    self.assertTrue(row["ap_refining_route"])
                    self.assertTrue(row["aq_refining_route"])
                    self.assertTrue(row["ar_refining_route"])

    def test_mixed_ap_baseline_is_rejected(self) -> None:
        records = deepcopy(self.records)
        stress = next(row for row in records if row["category"] == "llm_fallback_stress")
        stress["inputs"]["baseline_assignments"][0]["ladle_id"] = "ST999"
        with self.assertRaises(BenchmarkContractError):
            build_benchmark(records, self.source, self.factory, self.factory_metadata)

    def test_duplicate_disturbance_kind_is_rejected(self) -> None:
        records = deepcopy(self.records)
        stress = [row for row in records if row["category"] == "llm_fallback_stress"]
        stress[1]["disturbance_kind"] = stress[0]["disturbance_kind"]
        control = [row for row in records if row["category"] != "llm_fallback_stress"]
        with self.assertRaises(BenchmarkContractError):
            build_benchmark([*control, *stress], self.source, self.factory, self.factory_metadata)

    def test_primary_changed_heat_count_keeps_route_change_separate(self) -> None:
        primary = next(row for row in self.result["scenarios"] if row["disturbance_kind"] == "crane_offline")
        metrics = primary["branches"]["codex"]["metrics"]
        self.assertEqual(metrics["changed_heat_count"], 3)
        self.assertEqual(metrics["route_change_count"], 1)

    def test_recommendation_respects_metric_order(self) -> None:
        metrics = {
            "completion_rate": 1.0,
            "on_time_rate": 1.0,
            "average_delay_seconds": 0.0,
            "max_delay_seconds": 0.0,
            "changed_heat_count": 5,
            "resource_change_count": 5,
            "crane_load_dispersion": 1.0,
        }
        decision_tree = {"executable": True, "failed_hard_gates": [], "metrics": deepcopy(metrics)}
        codex = {"executable": True, "failed_hard_gates": [], "metrics": deepcopy(metrics)}
        codex["metrics"]["on_time_rate"] = 0.9
        codex["metrics"]["changed_heat_count"] = 1
        winner, reason = recommend_branches(decision_tree, codex)
        self.assertEqual(winner, "decision_tree")
        self.assertIn("on_time_rate", reason)


if __name__ == "__main__":
    unittest.main()
