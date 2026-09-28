"""HTTP-facing adapter for normal ladle preallocation.

The adapter owns the JSON boundary. The decision tree remains the only
allocator and ``validate_output`` remains the final hard-constraint check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ladle_preallocation.decision_tree import allocate, validate_output
from ladle_preallocation.decision_tree.config import TREE_VERSION
from ladle_preallocation.data_modeling.assumptions import COORDINATE_UNITS_PER_METER


class PreallocationInputError(ValueError):
    """A request is malformed or misses a required field."""


class PreallocationConflictError(ValueError):
    """A request contains conflicting resource or location records."""


@dataclass(frozen=True)
class NormalizedPreallocation:
    request_id: str
    plan_date: str | None
    execution_mode: str
    window_minutes: float
    source_heats: list[dict[str, Any]]
    heats: list[dict[str, Any]]
    ladles: list[dict[str, Any]]
    cranes: list[dict[str, Any]]
    location_map: list[dict[str, Any]]
    time_origin: float
    time_origin_at: str | None


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PreallocationInputError(f"{name} must be an object")
    return value


def _require_list(value: Any, name: str, *, minimum: int = 0) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise PreallocationInputError(f"{name} must be an array")
    if len(value) < minimum:
        raise PreallocationInputError(f"{name} must contain at least {minimum} item(s)")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        result.append(_require_mapping(item, f"{name}[{index}]"))
    return result


def _required_text(record: dict[str, Any], field: str, context: str) -> str:
    value = record.get(field)
    if value in (None, ""):
        raise PreallocationInputError(f"{context}.{field} is required")
    text = str(value).strip()
    if not text:
        raise PreallocationInputError(f"{context}.{field} is required")
    return text


def _number(record: dict[str, Any], field: str, context: str, *, minimum: float | None = None, required: bool = False) -> float | None:
    value = record.get(field)
    if value in (None, ""):
        if required:
            raise PreallocationInputError(f"{context}.{field} is required")
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise PreallocationInputError(f"{context}.{field} must be numeric") from exc
    if minimum is not None and parsed < minimum:
        raise PreallocationInputError(f"{context}.{field} must be >= {minimum}")
    return parsed


def _parse_datetime(value: Any, field: str, context: str, *, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise PreallocationInputError(f"{context}.{field} is required")
        return None
    if not isinstance(value, str):
        raise PreallocationInputError(f"{context}.{field} must be an RFC 3339 string")
    raw = value.strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreallocationInputError(f"{context}.{field} must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise PreallocationInputError(f"{context}.{field} must include a timezone")
    return parsed.astimezone(timezone.utc).timestamp()


def _normalise_online_status(value: Any, context: str) -> bool:
    if value in (None, ""):
        raise PreallocationInputError(f"{context}.online_status is required")
    normalized = str(value).strip().lower()
    if value is True or normalized in {"online", "1", "1.0", "true"}:
        return True
    if value is False or normalized in {"offline", "0", "0.0", "false", "maintenance", "unknown"}:
        return False
    raise PreallocationInputError(f"{context}.online_status is invalid")


def _ensure_unique(records: list[dict[str, Any]], field: str, name: str) -> None:
    seen: set[str] = set()
    for index, record in enumerate(records):
        identifier = _required_text(record, field, f"{name}[{index}]")
        if identifier in seen:
            raise PreallocationConflictError(f"duplicate {name} {field}: {identifier}")
        seen.add(identifier)


def normalize_preallocation_request(payload: dict[str, Any]) -> NormalizedPreallocation:
    """Validate and normalize the public request into allocator inputs."""
    request = _require_mapping(payload, "request")
    request_id = _required_text(request, "request_id", "request")
    plan_date = request.get("plan_date")
    if plan_date not in (None, ""):
        if not isinstance(plan_date, str):
            raise PreallocationInputError("request.plan_date must be a date string")
        try:
            datetime.fromisoformat(plan_date)
        except ValueError as exc:
            raise PreallocationInputError("request.plan_date must be YYYY-MM-DD") from exc
        plan_date = plan_date.strip()

    execution_mode = str(request.get("execution_mode", "sliding_window")).strip()
    if execution_mode not in {"full_replay", "sliding_window"}:
        raise PreallocationInputError("request.execution_mode must be full_replay or sliding_window")
    window_minutes = _number(request, "window_minutes", "request", minimum=0) or 180.0

    source_heats = _require_list(request.get("heats"), "heats", minimum=1)
    source_ladles = _require_list(request.get("ladles", []), "ladles")
    source_cranes = _require_list(request.get("cranes"), "cranes", minimum=1)
    source_locations = _require_list(request.get("location_map", []), "location_map")
    _ensure_unique(source_heats, "heat_id", "heats")
    _ensure_unique(source_ladles, "ladle_id", "ladles")
    _ensure_unique(source_cranes, "crane_id", "cranes")
    _ensure_unique(source_locations, "position_code", "location_map") if source_locations else None

    location_by_code: dict[str, dict[str, Any]] = {}
    normalized_locations: list[dict[str, Any]] = []
    for index, source in enumerate(source_locations):
        context = f"location_map[{index}]"
        code = _required_text(source, "position_code", context)
        position = _number(source, "position_m", context, required=True)
        existing = location_by_code.get(code)
        if existing is not None and existing["position_m"] != position:
            raise PreallocationConflictError(f"conflicting location_map position_code: {code}")
        normalized = {
            "position_code": code,
            "span_name": source.get("span_name"),
            "position_m": position,
            "location_type": source.get("location_type"),
            "status": source.get("status"),
        }
        location_by_code[code] = normalized
        normalized_locations.append(normalized)

    parsed_heat_rows: list[tuple[dict[str, Any], float, float]] = []
    all_times: list[float] = []
    for index, source in enumerate(source_heats):
        context = f"heats[{index}]"
        heat_id = _required_text(source, "heat_id", context)
        plan_sequence = source.get("plan_sequence")
        if plan_sequence in (None, ""):
            raise PreallocationInputError(f"{context}.plan_sequence is required")
        try:
            sequence_number = int(plan_sequence)
        except (TypeError, ValueError) as exc:
            raise PreallocationInputError(f"{context}.plan_sequence must be an integer") from exc
        required_grade = source.get("required_grade")
        if required_grade in (None, ""):
            raise PreallocationInputError(f"{context}.required_grade is required")
        tap_finish = _parse_datetime(source.get("tap_finish_at"), "tap_finish_at", context, required=True)
        arrival = _parse_datetime(source.get("ladle_arrival_at"), "ladle_arrival_at", context)
        pour_start = _parse_datetime(source.get("ladle_pour_start_at"), "ladle_pour_start_at", context)
        window_start = arrival if arrival is not None else tap_finish
        window_end = pour_start if pour_start is not None else tap_finish
        assert tap_finish is not None and window_start is not None and window_end is not None
        if window_end < window_start:
            raise PreallocationInputError(f"{context} time window end precedes start")
        all_times.extend(value for value in (tap_finish, arrival, pour_start) if value is not None)
        parsed_heat_rows.append((source, float(window_start), float(window_end)))

    time_origin = min(all_times)
    heats: list[dict[str, Any]] = []
    for source, window_start, window_end in parsed_heat_rows:
        heat_id = str(source["heat_id"]).strip()
        heats.append({
            "heat_id": heat_id,
            "required_grade": source["required_grade"],
            "window_start": window_start - time_origin,
            "window_end": window_end - time_origin,
            "target_age_seconds": 0.0,
            "priority": _number(source, "priority", "heat", minimum=0) or 0.0,
            "refining_route": source.get("refining_route"),
            "pour_at": window_end,
            "blow_at": window_start,
        })

    ladles: list[dict[str, Any]] = []
    for index, source in enumerate(source_ladles):
        context = f"ladles[{index}]"
        ladle_id = _required_text(source, "ladle_id", context)
        position = _number(source, "position_m", context, required=True)
        grade = source.get("grade")
        if grade in (None, ""):
            raise PreallocationInputError(f"{context}.grade is required")
        code = source.get("position_code")
        if code not in (None, ""):
            code = str(code).strip()
            mapped = location_by_code.get(code)
            if mapped is not None and mapped["position_m"] != position:
                raise PreallocationConflictError(f"ladle {ladle_id} conflicts with location_map {code}")
        availability = str(source.get("availability", "available")).strip().lower()
        if availability not in {"available", "unavailable", "maintenance", "unknown"}:
            raise PreallocationInputError(f"{context}.availability is invalid")
        ladles.append({
            "ladle_id": ladle_id,
            "grade": grade,
            "position_m": position,
            "position_code": code,
            "location_mapping_status": "mapped" if code in location_by_code else "api_input",
            "weight_tonnes": _number(source, "weight_tonnes", context, minimum=0, required=True),
            "age_seconds": _number(source, "age_seconds", context, minimum=0) or 0.0,
            "max_age_seconds": _number(source, "max_age_seconds", context, minimum=0),
            "availability": availability,
        })
    ladles = [item for item in ladles if item["availability"] == "available"]

    cranes: list[dict[str, Any]] = []
    for index, source in enumerate(source_cranes):
        context = f"cranes[{index}]"
        crane_id = _required_text(source, "crane_id", context)
        online = _normalise_online_status(source.get("online_status"), context)
        if not online:
            continue
        position = _number(source, "position_m", context, required=True)
        limit_0 = _number(source, "limit_0_m", context, required=True)
        limit_1 = _number(source, "limit_1_m", context, required=True)
        if limit_1 <= limit_0:
            raise PreallocationInputError(f"{context}.limit_1_m must be greater than limit_0_m")
        speed_mps = _number(source, "speed_mps", context, minimum=0) or 2.0
        safe_distance_m = _number(source, "safe_distance_m", context, minimum=0) or 10.0
        # Public requests use metres/second and metres for these fields while
        # the existing allocator uses the PLAN coordinate scale internally.
        safe_distance = safe_distance_m * COORDINATE_UNITS_PER_METER if safe_distance_m <= 100 else safe_distance_m
        cranes.append({
            "crane_id": crane_id,
            "position_m": position,
            "current_load_tonnes": _number(source, "current_load_tonnes", context, minimum=0) or 0.0,
            "max_load_tonnes": _number(source, "max_load_tonnes", context, minimum=0, required=True),
            "speed_mps": speed_mps * COORDINATE_UNITS_PER_METER,
            "safe_distance_m": safe_distance,
            "limit_0_m": limit_0,
            "limit_1_m": limit_1,
            "source_updated_at": source.get("updated_at"),
        })

    if not cranes:
        raise PreallocationConflictError("no online cranes are available")

    time_origin_at = datetime.fromtimestamp(time_origin, timezone.utc).isoformat().replace("+00:00", "Z")
    return NormalizedPreallocation(
        request_id=request_id,
        plan_date=plan_date,
        execution_mode=execution_mode,
        window_minutes=float(window_minutes),
        source_heats=source_heats,
        heats=heats,
        ladles=ladles,
        cranes=cranes,
        location_map=normalized_locations,
        time_origin=time_origin,
        time_origin_at=time_origin_at,
    )


def _status_for_row(row: dict[str, Any]) -> str:
    if row.get("action") == "assign":
        return "assigned"
    if row.get("action") == "request_human_review":
        return "manual_review"
    return "unassigned"


def allocate_preallocation(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run normal preallocation and return ``(HTTP status, JSON body)``."""
    try:
        normalized = normalize_preallocation_request(payload)
    except PreallocationConflictError as exc:
        return 409, {"error": str(exc), "request_id": payload.get("request_id") if isinstance(payload, dict) else None, "details": [str(exc)]}
    except PreallocationInputError as exc:
        return 400, {"error": str(exc), "request_id": payload.get("request_id") if isinstance(payload, dict) else None, "details": [str(exc)]}

    raw_assignments = allocate(normalized.heats, normalized.ladles, normalized.cranes)
    assignments = validate_output(normalized.heats, normalized.ladles, normalized.cranes, raw_assignments)
    by_source = {str(row["heat_id"]): row for row in normalized.source_heats}
    result_rows: list[dict[str, Any]] = []
    waits: list[float] = []
    assigned_count = 0
    violations_count = 0
    for row in assignments:
        heat_id = str(row["heat_id"])
        source = by_source[heat_id]
        status = _status_for_row(row)
        arrival_seconds = row.get("expected_arrival_seconds")
        wait_seconds = None
        arrival_at = None
        if status == "assigned" and arrival_seconds is not None:
            wait_seconds = round(max(0.0, float(arrival_seconds) - float(next(item["window_start"] for item in normalized.heats if item["heat_id"] == heat_id))), 3)
            waits.append(wait_seconds)
            arrival_at = datetime.fromtimestamp(normalized.time_origin + float(arrival_seconds), timezone.utc).isoformat().replace("+00:00", "Z")
            assigned_count += 1
        violations = [str(item) for item in row.get("violations") or ()]
        violations_count += len(violations)
        result_rows.append({
            "plan_key": f"{heat_id}::{source['plan_sequence']}",
            "heat_id": heat_id,
            "plan_sequence": int(source["plan_sequence"]),
            "algorithm": "decision_tree",
            "status": status,
            "ladle_id": row.get("ladle_id"),
            "crane_id": row.get("crane_id"),
            "expected_arrival_at": arrival_at,
            "expected_wait_seconds": wait_seconds,
            "grade_match": row.get("grade_match"),
            "violations": violations,
            "reason": row.get("reason") or "未分配",
            "decision_path": list(row.get("decision_path") or ()),
        })

    total = len(result_rows)
    complete = assigned_count == total
    manual = any(row["status"] == "manual_review" for row in result_rows)
    top_status = "completed" if complete else ("manual_review" if manual else "partial")
    http_status = 200 if complete else 422
    body = {
        "request_id": normalized.request_id,
        "status": top_status,
        "algorithm": "decision_tree",
        "tree_version": TREE_VERSION,
        "execution_mode": normalized.execution_mode,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "results": result_rows,
        "metrics": {
            "total_heats": total,
            "assigned_heats": assigned_count,
            "success_rate": assigned_count / total if total else 0.0,
            "rule_violation_count": violations_count,
            "average_wait_seconds": sum(waits) / len(waits) if waits else 0.0,
            "max_wait_seconds": max(waits, default=0.0),
        },
        "audit": {
            "input_sources": {"plan": "api_request.heats", "crane": "api_request.cranes", "location": "api_request.location_map"},
            "excluded_heat_count": 0,
            "time_origin": normalized.time_origin_at,
            "location_mapping_count": len(normalized.location_map),
            "online_crane_count": len(normalized.cranes),
            "available_ladle_count": len(normalized.ladles),
        },
    }
    return http_status, body
