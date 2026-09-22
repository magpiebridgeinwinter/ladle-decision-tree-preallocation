from __future__ import annotations

from copy import deepcopy
import json
import unittest

from ladle_preallocation.offline_scenarios.validation import ScenarioValidator
from ladle_preallocation.real_data.audit import load_location_aware_audit
from tools.real_data_codex_stress_demo import SOURCE_AUDIT, build_demo


class IndependentCodexComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = load_location_aware_audit(SOURCE_AUDIT)
        cls.report = build_demo(SOURCE_AUDIT)

    def test_ap_is_the_only_full_baseline(self) -> None:
        self.assertEqual(
            json.dumps(self.report["baseline_full_assignments"], ensure_ascii=False, sort_keys=True),
            json.dumps(self.source["assignments"], ensure_ascii=False, sort_keys=True),
        )
        self.assertEqual(self.report["stress_audit"]["baseline_strategy"]["name"], "location_aware_audit_AP")

    def test_codex_branch_is_independent_and_completes_real_window(self) -> None:
        self.assertEqual(self.report["decision_tree"]["num_assigned"], 30)
        self.assertEqual(self.report["codex_llm"]["num_assigned"], 31)
        self.assertFalse(self.report["llm_invocation"]["external_api_called"])
        self.assertIn("AQ assignments are excluded", self.report["llm_invocation"]["independence"])
        changed = self.report["stress_audit"]["changed_assignments"]
        self.assertEqual(len(changed), 3)
        self.assertEqual({row["old_crane_id"] for row in changed}, {"2500"})

    def test_codex_proposal_requires_complete_shared_validation(self) -> None:
        scenario = self.report["scenario_inputs"]
        proposal = deepcopy(self.report["codex_llm"]["assignments"])
        proposal.pop()
        _, checks = ScenarioValidator().audit(
            scenario["heats"], scenario["ladles"], scenario["cranes"], proposal,
        )
        self.assertFalse(checks[0]["passed"])


if __name__ == "__main__":
    unittest.main()
