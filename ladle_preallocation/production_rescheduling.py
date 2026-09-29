"""Versioned production disturbance and rescheduling boundary.

This module keeps the HTTP layer thin. It owns the durable version chain and
adapts public snapshots to the existing disturbance injector/controller.
Secrets and prompts are deliberately excluded from persisted payloads.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ladle_preallocation.disturbance.catalog import DISTURBANCE_KINDS
from ladle_preallocation.disturbance.injector import DisturbanceSpec, inject_disturbance
from ladle_preallocation.llm.config import load_runtime_config
from ladle_preallocation.llm.react_agent import ReActRescheduler
from ladle_preallocation.preallocation_api import NormalizedPreallocation, normalize_preallocation_request
from ladle_preallocation.response.controller import TieredResponseController


EVENT_ALIASES = {
    "plan_change": "schedule_deviation",
    "schedule_change": "schedule_deviation",
    "crane_state_change": "crane_offline",
    "ladle_state_change": "ladle_unavailable",
    "facility_change": "facility_unavailable",
}
SUPPORTED_EVENT_TYPES = frozenset(set(DISTURBANCE_KINDS) | set(EVENT_ALIASES))
TERMINAL_JOB_STATES = {"published", "rejected", "frozen", "human_review"}
REVISION_STATES = {"candidate", "pending_confirmation", "confirmed", "rejected", "published", "frozen", "human_review"}
ALLOWED_TRANSITIONS = {
    "received": {"scoped", "frozen", "human_review"},
    "scoped": {"running", "frozen", "human_review"},
    "running": {"pending_confirmation", "frozen", "human_review"},
    "pending_confirmation": {"confirmed", "rejected", "frozen", "human_review"},
    "confirmed": {"published", "rejected"},
    "rejected": set(),
    "frozen": set(),
    "human_review": set(),
    "published": set(),
}


class JobStatus(str, Enum):
    RECEIVED = "received"
    SCOPED = "scoped"
    RUNNING = "running"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    PUBLISHED = "published"
    FROZEN = "frozen"
    HUMAN_REVIEW = "human_review"
    REJECTED = "rejected"


class RevisionStatus(str, Enum):
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FROZEN = "frozen"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class VersionSet:
    """Immutable links between an upstream plan, snapshot and result."""

    plan_version: str
    snapshot_version: str
    allocation_version: str


@dataclass(frozen=True)
class DisturbanceEvent:
    """Typed identity and source metadata for one production event."""

    disturbance_id: str
    event_type: str
    occurred_at: str
    versions: VersionSet
    resource_id: str = ""


@dataclass(frozen=True)
class ReschedulingRevision:
    """Typed identity for a candidate or published revision."""

    revision_id: str
    job_id: str
    parent_revision_id: str
    status: RevisionStatus


class ProductionReschedulingError(ValueError):
    """A request cannot be accepted by the production boundary."""

    status = 400


class ProductionConflictError(ProductionReschedulingError):
    status = 409


class ProductionNotFoundError(ProductionReschedulingError):
    status = 404


class ProductionLockedError(ProductionReschedulingError):
    status = 423


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(prefix: str, value: Any) -> str:
    digest = hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in {"api_key", "authorization", "prompt", "llm_api_key"} else _redact(item)
            for key, item in value.items()
            if str(key).lower() not in {"headers", "request_headers"}
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {key: row[key] for key in row.keys()}


class ProductionRepository:
    """Small SQLite repository with explicit transactions and JSON payloads."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS baselines (
                    allocation_version TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    plan_version TEXT NOT NULL,
                    snapshot_version TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_baseline_plan_allocation
                    ON baselines(plan_version, allocation_version);
                CREATE TABLE IF NOT EXISTS disturbance_events (
                    disturbance_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    disturbance_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    parent_revision_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def save_baseline(self, baseline: dict[str, Any]) -> None:
        with self._connect() as connection:
            existing = connection.execute("SELECT 1 FROM baselines WHERE allocation_version = ?", (baseline["allocation_version"],)).fetchone()
            if existing is not None:
                return
            connection.execute(
                "INSERT INTO baselines(allocation_version, request_id, plan_version, snapshot_version, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (baseline["allocation_version"], baseline["request_id"], baseline["plan_version"], baseline["snapshot_version"], _json(_redact(baseline)), baseline["created_at"]),
            )

    def get_baseline(self, allocation_version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM baselines WHERE allocation_version = ?", (allocation_version,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        return payload

    def create_event(self, event: dict[str, Any], job: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._connect() as connection:
            existing = connection.execute("SELECT * FROM disturbance_events WHERE disturbance_id = ?", (event["disturbance_id"],)).fetchone()
            if existing is not None:
                return {"event": json.loads(existing["payload_json"]), "job_id": existing["job_id"]}, True
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO disturbance_events(disturbance_id, idempotency_key, event_type, payload_json, job_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (event["disturbance_id"], event.get("idempotency_key"), event["event_type"], _json(_redact(event)), job["job_id"], event["created_at"]),
                )
                connection.execute(
                    "INSERT INTO jobs(job_id, disturbance_id, status, payload_json, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (job["job_id"], event["disturbance_id"], job["status"], _json(_redact(job)), job["updated_at"]),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                existing = connection.execute("SELECT * FROM disturbance_events WHERE disturbance_id = ?", (event["disturbance_id"],)).fetchone()
                if existing is not None:
                    return {"event": json.loads(existing["payload_json"]), "job_id": existing["job_id"]}, True
                raise ProductionConflictError(f"disturbance could not be created: {exc}") from exc
        return {"event": event, "job_id": job["job_id"]}, False

    def update_job(self, job_id: str, payload: dict[str, Any], status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE jobs SET status = ?, payload_json = ?, updated_at = ? WHERE job_id = ?", (status, _json(_redact(payload)), _now(), job_id))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def get_job_by_disturbance(self, disturbance_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM jobs WHERE disturbance_id = ?", (disturbance_id,)).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def save_revision(self, revision: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO revisions(revision_id, job_id, parent_revision_id, status, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (revision["revision_id"], revision["job_id"], revision["parent_revision_id"], revision["status"], _json(_redact(revision)), revision["created_at"], revision["updated_at"]),
            )

    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM revisions WHERE revision_id = ?", (revision_id,)).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def audit(self, resource_type: str, resource_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO audit_events(resource_type, resource_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)", (resource_type, resource_id, event_type, _json(_redact(payload)), _now()))


def versioned_allocation_response(payload: dict[str, Any], normalized: NormalizedPreallocation, response: dict[str, Any]) -> dict[str, Any]:
    """Attach stable versions without changing the existing result shape."""
    plan_version = str(payload.get("plan_version") or _hash("PLAN", normalized.source_heats))
    snapshot = {"ladles": normalized.ladles, "cranes": normalized.cranes, "location_map": normalized.location_map, "time_origin": normalized.time_origin_at}
    snapshot_version = str(payload.get("snapshot_version") or _hash("SNAPSHOT", snapshot))
    allocation_version = str(payload.get("allocation_version") or _hash("ALLOC", {"request_id": normalized.request_id, "plan_version": plan_version, "snapshot_version": snapshot_version, "results": response.get("results", [])}))
    return {**response, "plan_version": plan_version, "snapshot_version": snapshot_version, "allocation_version": allocation_version, "baseline": {"plan_version": plan_version, "snapshot_version": snapshot_version, "allocation_version": allocation_version}}


def _internal_assignments(response: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in response.get("results", []):
        item = dict(row)
        item["action"] = "assign" if row.get("status") == "assigned" else "unassigned"
        rows.append(item)
    return rows


def _epoch(value: Any) -> float:
    if not isinstance(value, str):
        raise ProductionReschedulingError("occurred_at must be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProductionReschedulingError("occurred_at must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise ProductionReschedulingError("occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


@dataclass
class ProductionReschedulingService:
    repository: ProductionRepository

    def register_baseline(self, payload: dict[str, Any], normalized: NormalizedPreallocation, response: dict[str, Any]) -> dict[str, Any]:
        versioned = versioned_allocation_response(payload, normalized, response)
        baseline = {
            "request_id": normalized.request_id,
            "plan_version": versioned["plan_version"],
            "snapshot_version": versioned["snapshot_version"],
            "allocation_version": versioned["allocation_version"],
            "created_at": versioned.get("generated_at", _now()),
            "heats": normalized.heats,
            "source_heats": normalized.source_heats,
            "ladles": normalized.ladles,
            "cranes": normalized.cranes,
            "location_map": normalized.location_map,
            "source_ladles": deepcopy(payload.get("ladles", [])),
            "source_cranes": deepcopy(payload.get("cranes", [])),
            "source_location_map": deepcopy(payload.get("location_map", [])),
            "time_origin": normalized.time_origin,
            "time_origin_at": normalized.time_origin_at,
            "assignments": _internal_assignments(versioned),
            "response_summary": {"status": versioned.get("status"), "algorithm": versioned.get("algorithm"), "metrics": versioned.get("metrics", {})},
        }
        self.repository.save_baseline(baseline)
        return versioned

    def create_disturbance(self, payload: dict[str, Any], idempotency_key: str | None = None) -> tuple[int, dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ProductionReschedulingError("request body must be an object")
        required = ("disturbance_id", "event_type", "occurred_at", "plan_version", "allocation_version", "snapshot_version")
        missing = [field for field in required if payload.get(field) in (None, "")]
        if missing:
            raise ProductionReschedulingError(f"missing required fields: {', '.join(missing)}")
        event_type = str(payload["event_type"]).strip()
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ProductionReschedulingError(f"unsupported event_type: {event_type}")
        baseline = self.repository.get_baseline(str(payload["allocation_version"]))
        if baseline is None:
            raise ProductionConflictError("allocation_version does not identify a stored baseline")
        for field in ("plan_version", "snapshot_version"):
            if str(payload[field]) != str(baseline[field]):
                raise ProductionConflictError(f"{field} conflicts with allocation baseline",)
        _epoch(payload["occurred_at"])
        disturbance_id = str(payload["disturbance_id"])
        existing = self.repository.get_job_by_disturbance(disturbance_id) if hasattr(self.repository, "get_job_by_disturbance") else None
        if existing is not None:
            return 200, {**existing, "duplicate": True}
        event = {**payload, "event_type": EVENT_ALIASES.get(event_type, event_type), "idempotency_key": idempotency_key or payload.get("idempotency_key"), "created_at": _now()}
        job_id = f"JOB-{secrets.token_hex(8)}"
        job = {"job_id": job_id, "disturbance_id": disturbance_id, "status": "received", "created_at": event["created_at"], "updated_at": event["created_at"], "versions": {field: payload[field] for field in ("plan_version", "allocation_version", "snapshot_version")}}
        self.repository.create_event(event, job)
        self.repository.update_job(job_id, job, "scoped")
        try:
            result = self._run_workflow(payload, event, job, baseline)
        except ProductionReschedulingError:
            raise
        except Exception as exc:
            job.update({"status": "human_review", "error": type(exc).__name__, "reason": "workflow execution failed"})
            self.repository.update_job(job_id, job, "human_review")
            self.repository.audit("job", job_id, "workflow_failed", {"error_type": type(exc).__name__})
            return 422, job
        return result

    def _run_workflow(self, payload: dict[str, Any], event: dict[str, Any], job: dict[str, Any], baseline: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.repository.update_job(job["job_id"], job, "running")
        snapshot = payload.get("current_snapshot") or {}
        resource_id = str(payload.get("resource_id") or payload.get("affected_resource_id") or (payload.get("affected_resources", {}).get("cranes") or payload.get("affected_resources", {}).get("ladles") or [{}])[0].get("crane_id") or (payload.get("affected_resources", {}).get("ladles") or [{}])[0].get("ladle_id") or "")
        source_cranes = snapshot.get("cranes") or baseline.get("source_cranes", [])
        raw_cranes = snapshot.get("cranes") or []
        raw_ladles = snapshot.get("ladles") or []
        if payload.get("current_snapshot") and resource_id:
            if event["event_type"] in {"crane_offline", "crane_telemetry_stale"}:
                matches = [row for row in raw_cranes if str(row.get("crane_id")) == resource_id]
                if matches and str(matches[0].get("online_status", "")).lower() not in {"offline", "maintenance", "unknown", "0", "false"}:
                    raise ProductionConflictError("current snapshot contradicts crane disturbance")
            if event["event_type"] in {"ladle_unavailable", "ladle_damage", "ladle_lining_alarm", "ladle_over_age"}:
                matches = [row for row in raw_ladles if str(row.get("ladle_id")) == resource_id]
                if matches and event["event_type"] != "ladle_over_age" and str(matches[0].get("availability", "available")).lower() == "available":
                    raise ProductionConflictError("current snapshot contradicts ladle disturbance")
        # The injector applies offline/maintenance deltas after normalization;
        # keep those records in the candidate pool long enough to validate the
        # remaining snapshot, even when every crane is currently offline.
        normalization_cranes = [
            {**crane, "online_status": "online"} if str(crane.get("online_status", "online")).lower() != "online" else crane
            for crane in source_cranes
        ]
        source_ladles = snapshot.get("ladles") or baseline.get("source_ladles", [])
        normalization_ladles = [
            {**ladle, "availability": "available"} if str(ladle.get("availability", "available")).lower() != "available" else ladle
            for ladle in source_ladles
        ]
        snapshot_payload = {"request_id": f"snapshot-{job['job_id']}", "plan_date": None, "execution_mode": "full_replay", "heats": snapshot.get("heats") or baseline["source_heats"], "ladles": normalization_ladles, "cranes": normalization_cranes, "location_map": snapshot.get("location_map") or baseline.get("source_location_map", [])}
        current = normalize_preallocation_request(snapshot_payload)
        delta = current.time_origin - float(baseline["time_origin"])
        heats = deepcopy(baseline["heats"])
        if delta:
            for heat in heats:
                for key in ("window_start", "window_end", "pour_at", "blow_at"):
                    if heat.get(key) is not None:
                        heat[key] += delta
        metadata = dict(payload.get("metadata") or {})
        metadata.update({"affected_heat_ids": payload.get("affected_heat_ids") or metadata.get("affected_heat_ids", []), "window_minutes": payload.get("window_minutes", 180)})
        occurred = _epoch(payload["occurred_at"]) - float(baseline["time_origin"])
        spec = DisturbanceSpec(kind=event["event_type"], resource_id=resource_id, description=str(payload.get("description") or ""), occurred_at=occurred, metadata=metadata)
        locked = [str(value) for value in payload.get("locked_heat_ids", [])]
        scenario = inject_disturbance(spec, heats, current.ladles, current.cranes, baseline["assignments"], locked_heat_ids=locked)
        job.update({"status": "scoped", "impact_scope": {"affected_heat_ids": scenario.affected_heat_ids, "locked_heat_ids": scenario.locked_heat_ids, "unchanged_heat_ids": sorted(set(str(row["heat_id"]) for row in heats) - set(scenario.affected_heat_ids) - set(scenario.locked_heat_ids)), "remaining_budget_seconds": scenario.remaining_budget_seconds}})
        self.repository.update_job(job["job_id"], job, "scoped")
        config = load_runtime_config()
        llm = ReActRescheduler(api_base=config.api_base, api_key=config.api_key, model=config.model, max_rounds=5, configuration_source=config.source)
        primary, llm_result = TieredResponseController(llm).handle_disturbance(scenario)
        is_candidate = bool(primary.success and not primary.human_review_required)
        revision_status = "pending_confirmation" if is_candidate else ("frozen" if primary.path.value == "frozen" else "human_review")
        revision_id = _hash("REV", {"job_id": job["job_id"], "path": primary.path.value, "assignments": primary.assignments})
        revision = {
            "revision_id": revision_id,
            "job_id": job["job_id"],
            "disturbance_id": event["disturbance_id"],
            "parent_revision_id": baseline["allocation_version"],
            "status": revision_status,
            "algorithm": primary.extra.get("algorithm", primary.path.value),
            "base": {field: baseline[field] for field in ("plan_version", "allocation_version", "snapshot_version")},
            "impact_scope": job["impact_scope"],
            "results": primary.assignments,
            "validation": {"passed": is_candidate, "feedback": primary.validation_feedback, "failure_reasons": primary.failure_reasons},
            "workflow": primary.workflow.as_dict() if primary.workflow else None,
            "created_at": _now(),
            "updated_at": _now(),
            "api_configured": bool(config.api_key),
            "next_action": "human_confirm" if is_candidate else "human_review",
        }
        self.repository.save_revision(revision)
        job.update({"status": revision_status, "revision_id": revision_id, "workflow": revision.get("workflow"), "api_configured": bool(config.api_key)})
        self.repository.update_job(job["job_id"], job, revision_status)
        self.repository.audit("job", job["job_id"], "workflow_completed", {"revision_id": revision_id, "status": revision_status, "llm_attempted": llm_result is not None})
        return 200 if is_candidate else 422, {**job, "revision": revision}

    def get_job_response(self, job_id: str) -> dict[str, Any]:
        job = self.repository.get_job(job_id)
        if job is None:
            raise ProductionNotFoundError("job not found")
        return job

    def get_revision_response(self, revision_id: str) -> dict[str, Any]:
        revision = self.repository.get_revision(revision_id)
        if revision is None:
            raise ProductionNotFoundError("revision not found")
        return revision

    def transition_revision(self, revision_id: str, action: str, operator: str, reason: str = "") -> dict[str, Any]:
        revision = self.get_revision_response(revision_id)
        current = str(revision["status"])
        target = {"confirm": "confirmed", "reject": "rejected", "publish": "published"}.get(action)
        if target is None or target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise ProductionConflictError(f"illegal revision transition: {current} -> {action}")
        if action == "publish":
            baseline = self.repository.get_baseline(revision["base"]["allocation_version"])
            if baseline is None or revision.get("validation", {}).get("passed") is not True:
                raise ProductionLockedError("revision is not publishable")
            revision["published_allocation_version"] = _hash("ALLOC", {"parent": revision["parent_revision_id"], "revision": revision_id})
            revision["publish_token"] = secrets.token_urlsafe(12)
            revision["next_action"] = "dispatch"
        elif action == "confirm":
            if revision.get("validation", {}).get("passed") is not True:
                raise ProductionLockedError("revision requires human review")
            revision["next_action"] = "publish"
        else:
            revision["next_action"] = "regenerate"
        revision["status"] = target
        revision["operator"] = operator or "unknown"
        revision["decision_reason"] = reason
        revision["updated_at"] = _now()
        self.repository.save_revision(revision)
        self.repository.update_job(revision["job_id"], {**(self.repository.get_job(revision["job_id"]) or {}), "status": target, "revision_id": revision_id}, target)
        self.repository.audit("revision", revision_id, action, {"operator": operator, "reason": reason, "status": target})
        return revision
