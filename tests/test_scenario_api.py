from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("serve_visualization", ROOT / "tools/serve_visualization.py")
assert SPEC is not None and SPEC.loader is not None
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class FakeHandler:
    scenario_database = ROOT / "outputs/offline_scenarios/ladle_scenarios.sqlite3"

    def __init__(self, path: str) -> None:
        self.path = path
        self.status = None
        self.body = None

    def _send_json(self, status, body):
        self.status = status
        self.body = body


class ScenarioApiTests(unittest.TestCase):
    def _get(self, path: str) -> FakeHandler:
        handler = FakeHandler(path)
        SERVER.DemoHandler.do_GET(handler)
        return handler

    def test_summary_endpoint(self):
        handler = self._get("/api/scenarios/summary")
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.body["scenario_count"], 21)
        self.assertEqual(handler.body["verified_llm_fallback_count"], 20)

    def test_filtered_list_endpoint(self):
        handler = self._get("/api/scenarios?category=decision_tree_control")
        self.assertEqual(handler.status, 200)
        self.assertEqual(len(handler.body["scenarios"]), 1)

    def test_detail_and_not_found_endpoints(self):
        detail = self._get("/api/scenarios/llm_fallback_007_ladle_damage")
        self.assertEqual(detail.status, 200)
        self.assertTrue(detail.body["llm_success"])
        missing = self._get("/api/scenarios/does-not-exist")
        self.assertEqual(missing.status, 404)


if __name__ == "__main__":
    unittest.main()
