from __future__ import annotations

import io
import importlib.util
import json
from pathlib import Path
import unittest

from ladle_preallocation.preallocation_api import allocate_preallocation


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("serve_visualization_api", ROOT / "tools/serve_visualization.py")
assert SPEC is not None and SPEC.loader is not None
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


def request_payload() -> dict:
    return {
        "request_id": "demo-001",
        "plan_date": "2026-03-06",
        "execution_mode": "sliding_window",
        "window_minutes": 180,
        "heats": [
            {
                "heat_id": "AQ0640E1",
                "plan_sequence": 640,
                "required_grade": 5,
                "refining_route": "LF-RH",
                "priority": 10,
                "tap_finish_at": "2026-03-06T08:20:00Z",
                "ladle_arrival_at": "2026-03-06T08:35:00Z",
                "ladle_pour_start_at": "2026-03-06T08:52:00Z",
            }
        ],
        "ladles": [
            {
                "ladle_id": "ST38",
                "grade": 5,
                "position_code": "4QF5",
                "position_m": 38105,
                "weight_tonnes": 160,
                "age_seconds": 420,
                "max_age_seconds": 3600,
                "availability": "available",
            }
        ],
        "cranes": [
            {
                "crane_id": "2500",
                "online_status": "online",
                "position_m": 35000,
                "speed_mps": 2,
                "current_load_tonnes": 0,
                "max_load_tonnes": 300,
                "safe_distance_m": 10,
                "limit_0_m": 0,
                "limit_1_m": 48000,
            }
        ],
        "location_map": [
            {
                "position_code": "4QF5",
                "span_name": "4Q",
                "position_m": 38105,
                "location_type": "ladle_yard",
                "status": "available",
            }
        ],
    }


class FakePostHandler:
    def __init__(self, path: str, payload: object) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.path = path
        self.headers = {"Content-Length": str(len(encoded))}
        self.rfile = io.BytesIO(encoded)
        self.status = None
        self.body = None

    def _send_json(self, status, body):
        self.status = status
        self.body = body


class LadlePreallocationApiTests(unittest.TestCase):
    def test_valid_request_returns_assigned_output(self):
        status, body = allocate_preallocation(request_payload())
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["algorithm"], "decision_tree")
        self.assertEqual(body["results"][0]["status"], "assigned")
        self.assertEqual(body["results"][0]["ladle_id"], "ST38")
        self.assertEqual(body["results"][0]["crane_id"], "2500")
        self.assertNotIn("api_key", json.dumps(body))

    def test_missing_required_field_returns_400(self):
        payload = request_payload()
        del payload["request_id"]
        status, body = allocate_preallocation(payload)
        self.assertEqual(status, 400)
        self.assertIn("request_id", body["error"])

    def test_invalid_timestamp_returns_400(self):
        payload = request_payload()
        payload["heats"][0]["tap_finish_at"] = "2026-03-06 08:20:00"
        status, body = allocate_preallocation(payload)
        self.assertEqual(status, 400)
        self.assertIn("timezone", body["error"])

    def test_duplicate_crane_returns_409(self):
        payload = request_payload()
        payload["cranes"].append(dict(payload["cranes"][0]))
        status, body = allocate_preallocation(payload)
        self.assertEqual(status, 409)
        self.assertIn("duplicate", body["error"])

    def test_location_conflict_returns_409(self):
        payload = request_payload()
        payload["location_map"][0]["position_m"] = 999
        status, body = allocate_preallocation(payload)
        self.assertEqual(status, 409)
        self.assertIn("conflicts", body["error"])

    def test_no_ladle_returns_422_with_unassigned_result(self):
        payload = request_payload()
        payload["ladles"] = []
        status, body = allocate_preallocation(payload)
        self.assertEqual(status, 422)
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["results"][0]["status"], "unassigned")

    def test_http_route_dispatches_new_endpoint(self):
        handler = FakePostHandler("/api/v1/ladle-preallocation/allocate", request_payload())
        SERVER.DemoHandler.do_POST(handler)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.body["request_id"], "demo-001")

    def test_existing_simulate_route_remains_separate(self):
        handler = FakePostHandler("/api/simulate", {"scenario_id": "unsupported"})
        SERVER.DemoHandler.do_POST(handler)
        self.assertEqual(handler.status, 400)
        self.assertIn("supported_scenario_ids", handler.body)


if __name__ == "__main__":
    unittest.main()
