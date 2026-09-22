"""SQLite persistence and read-only queries for offline scenario playback."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from ladle_preallocation.disturbance.catalog import DISTURBANCE_KINDS


SCHEMA_VERSION = 2
ALLOWED_CATEGORIES = frozenset({"decision_tree_control", "llm_fallback_stress"})


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE scenario (
    scenario_id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN ('decision_tree_control', 'llm_fallback_stress')),
    disturbance_kind TEXT NOT NULL,
    disturbance_group TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    visual_cue TEXT,
    evidence_type TEXT NOT NULL,
    event_time REAL NOT NULL,
    window_start REAL NOT NULL,
    window_end REAL NOT NULL,
    seed INTEGER NOT NULL,
    source_plan TEXT NOT NULL,
    source_crane TEXT NOT NULL,
    source_audit TEXT NOT NULL,
    decision_tree_success INTEGER NOT NULL CHECK (decision_tree_success IN (0, 1)),
    llm_attempted INTEGER NOT NULL CHECK (llm_attempted IN (0, 1)),
    llm_success INTEGER CHECK (llm_success IN (0, 1)),
    affected_heat_count INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    CHECK (
        (category = 'decision_tree_control' AND decision_tree_success = 1 AND llm_attempted = 0 AND llm_success IS NULL)
        OR
        (category = 'llm_fallback_stress' AND decision_tree_success = 0 AND llm_attempted = 1 AND llm_success = 1)
    )
);
CREATE INDEX idx_scenario_category ON scenario(category);
CREATE INDEX idx_scenario_kind ON scenario(disturbance_kind);
CREATE INDEX idx_scenario_group ON scenario(disturbance_group);

CREATE TABLE event (
    scenario_id TEXT NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    offset_seconds REAL NOT NULL,
    occurred_at REAL NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, sequence)
);

CREATE TABLE scenario_asset (
    scenario_id TEXT NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    role TEXT NOT NULL,
    source_record_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, asset_type, asset_id, role)
);
CREATE INDEX idx_scenario_asset_lookup ON scenario_asset(asset_type, asset_id);

CREATE TABLE response_result (
    scenario_id TEXT NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
    stage TEXT NOT NULL CHECK (stage IN ('decision_tree', 'llm')),
    path TEXT NOT NULL,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    num_assigned INTEGER NOT NULL CHECK (num_assigned >= 0),
    elapsed_seconds REAL NOT NULL CHECK (elapsed_seconds >= 0),
    remaining_budget_seconds REAL,
    reason TEXT NOT NULL,
    validation_feedback_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, stage)
);

CREATE TABLE assignment (
    scenario_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    heat_id TEXT NOT NULL,
    ladle_id TEXT,
    crane_id TEXT,
    refining_route TEXT,
    action TEXT NOT NULL CHECK (action IN ('assign', 'unassigned', 'request_human_review')),
    reason TEXT NOT NULL,
    violations_json TEXT NOT NULL,
    source_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, stage, heat_id),
    FOREIGN KEY (scenario_id, stage) REFERENCES response_result(scenario_id, stage) ON DELETE CASCADE
);
CREATE INDEX idx_assignment_assets ON assignment(ladle_id, crane_id);

CREATE TABLE validation (
    scenario_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('decision_tree', 'llm')),
    sequence INTEGER NOT NULL,
    check_code TEXT NOT NULL,
    passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
    details_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, stage, sequence),
    FOREIGN KEY (scenario_id, stage) REFERENCES response_result(scenario_id, stage) ON DELETE CASCADE
);

CREATE TABLE audit_metadata (
    scenario_id TEXT NOT NULL REFERENCES scenario(scenario_id) ON DELETE CASCADE,
    metadata_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    PRIMARY KEY (scenario_id, metadata_key)
);

CREATE TABLE build_metadata (
    metadata_key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _insert_record(connection: sqlite3.Connection, record: dict[str, Any]) -> None:
    source = record["source"]
    dt = record["responses"]["decision_tree"]
    llm = record["responses"].get("llm")
    affected_count = len(record["inputs"]["heats"])
    connection.execute(
        """INSERT INTO scenario VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record["scenario_id"], record["category"], record["disturbance_kind"], record["disturbance_group"],
            record["title"], record["description"], record.get("visual_cue"), record["evidence_type"],
            record["event_time"], record["window_start"], record["window_end"], record["seed"],
            source["plan"], source["crane"], source["audit"], int(dt["success"]),
            int(record["audit"].get("llm_attempted", False)), None if llm is None else int(llm["success"]),
            affected_count, SCHEMA_VERSION,
        ),
    )
    connection.executemany(
        "INSERT INTO event VALUES (?,?,?,?,?,?)",
        [(record["scenario_id"], item["sequence"], item["event_type"], item["offset_seconds"], item["occurred_at"], _json(item.get("payload", {}))) for item in record["events"]],
    )
    connection.executemany(
        "INSERT INTO scenario_asset VALUES (?,?,?,?,?)",
        [(record["scenario_id"], item["asset_type"], item["asset_id"], item["role"], _json(item["source_record"])) for item in record["assets"]],
    )
    for stage, response in record["responses"].items():
        if response is None:
            continue
        connection.execute(
            "INSERT INTO response_result VALUES (?,?,?,?,?,?,?,?,?,?)",
            (record["scenario_id"], stage, response["path"], int(response["success"]), response["num_assigned"], response["elapsed_seconds"], response.get("remaining_budget_seconds"), response["reason"], _json(response.get("validation_feedback", {})), _json(response.get("metrics", {}))),
        )
        connection.executemany(
            "INSERT INTO assignment VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(
                record["scenario_id"], stage, str(row["heat_id"]), row.get("ladle_id"), row.get("crane_id"),
                str(row.get("refining_route") or "").strip() or None, str(row.get("action") or "unassigned"),
                str(row.get("reason") or ""), _json(row.get("violations") or ()), _json(row),
            ) for row in response["assignments"]],
        )
    for stage, checks in record["validations"].items():
        connection.executemany(
            "INSERT INTO validation VALUES (?,?,?,?,?,?)",
            [(record["scenario_id"], stage, sequence, check["check_code"], int(check["passed"]), _json(check.get("details", {}))) for sequence, check in enumerate(checks, 1)],
        )
    audit_values = {**record["audit"], "event": record["event"], "controlled_inputs": record["inputs"]}
    connection.executemany(
        "INSERT INTO audit_metadata VALUES (?,?,?)",
        [(record["scenario_id"], key, _json(value)) for key, value in sorted(audit_values.items())],
    )


def _assert_database(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {integrity}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        raise RuntimeError(f"SQLite foreign-key check failed: {foreign_keys}")
    categories = {row[0] for row in connection.execute("SELECT DISTINCT category FROM scenario")}
    if categories != ALLOWED_CATEGORIES:
        raise RuntimeError(f"database categories are invalid: {sorted(categories)}")
    counts = dict(connection.execute("SELECT category, COUNT(*) FROM scenario GROUP BY category"))
    expected_counts = {"decision_tree_control": 1, "llm_fallback_stress": len(DISTURBANCE_KINDS)}
    if counts != expected_counts:
        raise RuntimeError(f"database category counts are invalid: {counts}")
    stress_kinds = {row[0] for row in connection.execute("SELECT disturbance_kind FROM scenario WHERE category='llm_fallback_stress'")}
    if stress_kinds != DISTURBANCE_KINDS:
        raise RuntimeError("database stress catalog does not match the supported disturbance catalog")
    bad_stress = connection.execute("SELECT COUNT(*) FROM scenario WHERE category='llm_fallback_stress' AND (decision_tree_success!=0 OR llm_attempted!=1 OR llm_success!=1)").fetchone()[0]
    bad_control = connection.execute("SELECT COUNT(*) FROM scenario WHERE category='decision_tree_control' AND (decision_tree_success!=1 OR llm_attempted!=0 OR llm_success IS NOT NULL)").fetchone()[0]
    failed_llm_checks = connection.execute("SELECT COUNT(*) FROM validation JOIN scenario USING(scenario_id) WHERE category='llm_fallback_stress' AND stage='llm' AND passed=0").fetchone()[0]
    response_count_mismatches = connection.execute(
        """SELECT COUNT(*) FROM response_result AS response
           WHERE response.num_assigned != (
               SELECT COUNT(*) FROM assignment AS item
               WHERE item.scenario_id=response.scenario_id AND item.stage=response.stage AND item.action='assign'
           )"""
    ).fetchone()[0]
    missing_route_assets = connection.execute(
        """SELECT COUNT(*) FROM assignment AS item
           WHERE item.refining_route IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM scenario_asset AS asset
               WHERE asset.scenario_id=item.scenario_id AND asset.asset_type='route' AND asset.asset_id=item.refining_route
           )"""
    ).fetchone()[0]
    missing_source_asset_types = connection.execute(
        """SELECT COUNT(*) FROM scenario AS item
           WHERE EXISTS (
               SELECT 1 FROM (SELECT 'heat' AS asset_type UNION ALL SELECT 'ladle' UNION ALL SELECT 'crane' UNION ALL SELECT 'route') AS required
               WHERE NOT EXISTS (
                   SELECT 1 FROM scenario_asset AS asset
                   WHERE asset.scenario_id=item.scenario_id AND asset.asset_type=required.asset_type
               )
           )"""
    ).fetchone()[0]
    if bad_stress or bad_control or failed_llm_checks or response_count_mismatches or missing_route_assets or missing_source_asset_types:
        raise RuntimeError(
            "scenario invariants failed: "
            f"stress={bad_stress}, control={bad_control}, llm_checks={failed_llm_checks}, "
            f"response_counts={response_count_mismatches}, routes={missing_route_assets}, "
            f"source_assets={missing_source_asset_types}"
        )

    required_llm_checks = {"codex_adapter_invoked", "complete_assignment_set", "shared_hard_constraints", "scenario_policy"}
    for row in connection.execute(
        """SELECT scenario_id, affected_heat_count FROM scenario
           WHERE category='llm_fallback_stress' ORDER BY scenario_id"""
    ):
        scenario_id, affected_count = row
        decision_tree = connection.execute(
            "SELECT success, num_assigned FROM response_result WHERE scenario_id=? AND stage='decision_tree'",
            (scenario_id,),
        ).fetchone()
        llm = connection.execute(
            "SELECT success, num_assigned FROM response_result WHERE scenario_id=? AND stage='llm'",
            (scenario_id,),
        ).fetchone()
        passed_checks = {
            check[0]
            for check in connection.execute(
                "SELECT check_code FROM validation WHERE scenario_id=? AND stage='llm' AND passed=1",
                (scenario_id,),
            )
        }
        if (
            decision_tree is None
            or decision_tree[0] != 0
            or decision_tree[1] >= affected_count
            or llm is None
            or llm[0] != 1
            or llm[1] != affected_count
            or not required_llm_checks.issubset(passed_checks)
        ):
            raise RuntimeError(f"incomplete fallback evidence for scenario: {scenario_id}")

    stored_text = "\n".join(
        str(row[0]).lower()
        for query in (
            "SELECT payload_json FROM event",
            "SELECT source_record_json FROM scenario_asset",
            "SELECT validation_feedback_json FROM response_result",
            "SELECT metrics_json FROM response_result",
            "SELECT source_json FROM assignment",
            "SELECT details_json FROM validation",
            "SELECT value_json FROM audit_metadata",
        )
        for row in connection.execute(query)
    )
    forbidden_secret_keys = ('"api_key"', '"authorization"', '"password"', '"secret"')
    if any(marker in stored_text for marker in forbidden_secret_keys):
        raise RuntimeError("database contains a forbidden credential-shaped key")


def write_database(records: Iterable[dict[str, Any]], database_path: str | Path) -> Path:
    """Write and verify a complete database before atomically replacing output."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    rows = list(records)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT INTO build_metadata VALUES (?,?)", ("schema_version", _json(SCHEMA_VERSION)))
            connection.execute("INSERT INTO build_metadata VALUES (?,?)", ("scenario_count", _json(len(rows))))
            for record in rows:
                _insert_record(connection, record)
            _assert_database(connection)
            connection.commit()
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return path


def _decode(value: str | None) -> Any:
    return None if value is None else json.loads(value)


class ScenarioRepository:
    """Read-only database facade consumed by the local JSON API."""

    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(f"file:{self.path.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute("SELECT value_json FROM build_metadata WHERE metadata_key='schema_version'").fetchone()
            version = None if row is None else _decode(row[0])
            if version != SCHEMA_VERSION:
                raise sqlite3.DatabaseError(f"unsupported offline scenario schema: {version}")
        except Exception:
            connection.close()
            raise
        return connection

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM scenario").fetchone()[0]
            categories = [dict(row) for row in connection.execute("SELECT category, COUNT(*) AS count FROM scenario GROUP BY category ORDER BY category")]
            groups = [dict(row) for row in connection.execute("SELECT disturbance_group, COUNT(*) AS count FROM scenario GROUP BY disturbance_group ORDER BY disturbance_group")]
            stress = connection.execute("SELECT COUNT(*) FROM scenario WHERE category='llm_fallback_stress' AND decision_tree_success=0 AND llm_success=1").fetchone()[0]
            version = _decode(connection.execute("SELECT value_json FROM build_metadata WHERE metadata_key='schema_version'").fetchone()[0])
            return {"schema_version": version, "scenario_count": total, "categories": categories, "disturbance_groups": groups, "verified_llm_fallback_count": stress}

    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM scenario"
        parameters: tuple[Any, ...] = ()
        if category is not None:
            if category not in ALLOWED_CATEGORIES:
                raise ValueError(f"unsupported category: {category}")
            query += " WHERE category=?"
            parameters = (category,)
        query += " ORDER BY category, scenario_id"
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute(query, parameters)]
        for row in rows:
            for key in ("decision_tree_success", "llm_attempted", "llm_success"):
                if row[key] is not None:
                    row[key] = bool(row[key])
        return rows

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            scenario = connection.execute("SELECT * FROM scenario WHERE scenario_id=?", (scenario_id,)).fetchone()
            if scenario is None:
                return None
            payload = dict(scenario)
            payload["events"] = [{**dict(row), "payload": _decode(row["payload_json"])} for row in connection.execute("SELECT * FROM event WHERE scenario_id=? ORDER BY sequence", (scenario_id,))]
            for item in payload["events"]:
                item.pop("payload_json", None)
            payload["assets"] = [{**dict(row), "source_record": _decode(row["source_record_json"])} for row in connection.execute("SELECT * FROM scenario_asset WHERE scenario_id=? ORDER BY asset_type, asset_id", (scenario_id,))]
            for item in payload["assets"]:
                item.pop("source_record_json", None)
            payload["responses"] = {}
            for result in connection.execute("SELECT * FROM response_result WHERE scenario_id=? ORDER BY stage", (scenario_id,)):
                item = dict(result)
                stage = item.pop("stage")
                item["success"] = bool(item["success"])
                item["validation_feedback"] = _decode(item.pop("validation_feedback_json"))
                item["metrics"] = _decode(item.pop("metrics_json"))
                assignments = []
                for row in connection.execute("SELECT * FROM assignment WHERE scenario_id=? AND stage=? ORDER BY heat_id", (scenario_id, stage)):
                    assignment = dict(row)
                    assignment["violations"] = _decode(assignment.pop("violations_json"))
                    assignment["source"] = _decode(assignment.pop("source_json"))
                    assignments.append(assignment)
                item["assignments"] = assignments
                payload["responses"][stage] = item
            payload["validations"] = {}
            for row in connection.execute("SELECT * FROM validation WHERE scenario_id=? ORDER BY stage, sequence", (scenario_id,)):
                item = dict(row)
                stage = item.pop("stage")
                item["passed"] = bool(item["passed"])
                item["details"] = _decode(item.pop("details_json"))
                payload["validations"].setdefault(stage, []).append(item)
            payload["audit"] = {row["metadata_key"]: _decode(row["value_json"]) for row in connection.execute("SELECT * FROM audit_metadata WHERE scenario_id=? ORDER BY metadata_key", (scenario_id,))}
        for key in ("decision_tree_success", "llm_attempted", "llm_success"):
            if payload[key] is not None:
                payload[key] = bool(payload[key])
        return payload
