from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ladle_preallocation.preallocation_api import allocate_preallocation, normalize_preallocation_request
from ladle_preallocation.production_rescheduling import (
    ProductionConflictError,
    ProductionRepository,
    ProductionReschedulingService,
)

from test_ladle_preallocation_api import request_payload


class ProductionReschedulingApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.service = ProductionReschedulingService(ProductionRepository(Path(self.tempdir.name) / "production.sqlite3"))
        self.payload = request_payload()
        self.payload.update({"request_id": "baseline-001", "plan_version": "PLAN-001", "snapshot_version": "SNAPSHOT-001"})
        status, response = allocate_preallocation(self.payload)
        self.assertEqual(status, 200)
        self.response = self.service.register_baseline(self.payload, normalize_preallocation_request(self.payload), response)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def event(self, event_id: str = "DIST-001") -> dict:
        return {
            "disturbance_id": event_id,
            "event_type": "crane_offline",
            "occurred_at": "2026-03-06T08:40:00Z",
            "resource_id": "2500",
            "plan_version": self.response["plan_version"],
            "allocation_version": self.response["allocation_version"],
            "snapshot_version": self.response["snapshot_version"],
            "current_snapshot": {
                "heats": self.payload["heats"],
                "ladles": self.payload["ladles"],
                "cranes": [{**self.payload["cranes"][0], "online_status": "offline"}],
                "location_map": self.payload["location_map"],
            },
        }

    def test_versions_are_linked_to_baseline(self) -> None:
        baseline = self.service.repository.get_baseline(self.response["allocation_version"])
        self.assertEqual(baseline["plan_version"], "PLAN-001")
        self.assertEqual(baseline["snapshot_version"], "SNAPSHOT-001")
        self.assertEqual(baseline["request_id"], "baseline-001")

    def test_disturbance_creates_job_and_is_idempotent(self) -> None:
        status, first = self.service.create_disturbance(self.event())
        self.assertIn(status, (200, 422))
        self.assertIn(first["status"], {"pending_confirmation", "frozen", "human_review"})
        retry_status, retry = self.service.create_disturbance(self.event())
        self.assertEqual(retry_status, 200)
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["job_id"], first["job_id"])

    def test_stale_version_is_rejected(self) -> None:
        event = self.event()
        event["snapshot_version"] = "SNAPSHOT-STALE"
        with self.assertRaises(ProductionConflictError):
            self.service.create_disturbance(event)

    def test_confirmation_and_publication_state_gate(self) -> None:
        revision = {
            "revision_id": "REV-MANUAL-001",
            "job_id": "JOB-MANUAL-001",
            "parent_revision_id": self.response["allocation_version"],
            "status": "pending_confirmation",
            "validation": {"passed": True},
            "base": {"plan_version": self.response["plan_version"], "allocation_version": self.response["allocation_version"], "snapshot_version": self.response["snapshot_version"]},
            "created_at": "2026-03-06T08:40:00Z",
            "updated_at": "2026-03-06T08:40:00Z",
        }
        self.service.repository.save_revision(revision)
        confirmed = self.service.transition_revision(revision["revision_id"], "confirm", "operator-1")
        self.assertEqual(confirmed["status"], "confirmed")
        published = self.service.transition_revision(revision["revision_id"], "publish", "operator-1")
        self.assertEqual(published["status"], "published")
        self.assertTrue(published["publish_token"])


if __name__ == "__main__":
    unittest.main()
