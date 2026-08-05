"""Translate aligned production records into the existing allocation input tuple."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from ladle_preallocation.data_modeling.features import crane_features, relative_seconds
from ladle_preallocation.data_modeling.positions import decode_position
from ladle_preallocation.data_modeling.assumptions import (
    COORDINATE_UNITS_PER_METER,
    DEFAULT_MAX_LOAD_TONNES,
)
from ladle_preallocation.real_data.reader import parse_production_time


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def select_pending_heats(plan_records: list[dict[str, Any]], limit: int = 20, crane_range: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    selected = [row for row in plan_records if str(row.get("allocation_flag", "")).strip() in {"1", "5"} or row.get("_source_pre_filtered")]
    if crane_range is not None:
        lower, upper = crane_range
        def overlaps(row: dict[str, Any]) -> bool:
            times = [_timestamp(row, field) for field in ("tap_finish_at", "ladle_arrival_at", "ladle_pour_start_at")]
            actual = [value for value in times if value is not None]
            return bool(actual) and min(actual) <= upper and max(actual) >= lower
        selected = [row for row in selected if overlaps(row)]
    selected.sort(key=lambda row: (-_number(row.get("priority")), _timestamp(row, "tap_finish_at") or float("inf"), str(row.get("heat_id", ""))))
    return selected[:limit]


def _timestamp(row: dict[str, Any], field: str) -> float | None:
    value, invalid = parse_production_time(row.get(field))
    return None if invalid else value


def _heat(row: dict[str, Any], t0: float) -> dict[str, Any]:
    arrival = _timestamp(row, "ladle_arrival_at")
    end = _timestamp(row, "tap_finish_at")
    if end is None:
        end = _timestamp(row, "ladle_pour_start_at")
    start = relative_seconds(arrival, t0)
    window_end = relative_seconds(end, t0)
    if start is None:
        start = 0.0
    if window_end is None or window_end < start:
        window_end = start + 900.0
    raw_heat = str(row.get("heat_id") or row.get("manufacturing_order") or "unknown")
    sequence = row.get("plan_sequence")
    return {
        "heat_id": f"{raw_heat}-{sequence}" if sequence not in (None, "") else raw_heat,
        "required_grade": row.get("required_grade"),
        "window_start": start,
        "window_end": window_end,
        "target_age_seconds": 0.0,
        "priority": _number(row.get("priority")),
        "refining_route": row.get("refining_route"),
    }


def build_ladle_pool(plan_records: list[dict[str, Any]], t0: float) -> list[dict[str, Any]]:
    ladles: dict[str, dict[str, Any]] = {}
    for row in plan_records:
        ladle_id = row.get("decarb_ladle_id") or row.get("dephos_ladle_id") or row.get("preallocated_ladle")
        grade = row.get("current_ladle_grade")
        if ladle_id in (None, "") or grade in (None, ""):
            continue
        identifier = str(ladle_id)
        pour_finish = _timestamp(row, "ladle_pour_finish_at")
        age = max(0.0, t0 - pour_finish) if pour_finish is not None else 0.0
        decoded = decode_position(row.get("ladle_position"))
        # Prefer the PLAN-embedded coordinate derived from the approved location map.
        # The legacy fallback keeps historical, unmapped PLAN exports readable.
        position = _number(row.get("mapped_pos_x"), _number(row.get("ladle_position"), 0.0))
        empty_weight = _number(row.get("empty_ladle_weight"))
        if empty_weight is not None and empty_weight > 1000:
            empty_weight /= 1000.0
        ladles[identifier] = {"ladle_id": identifier, "grade": grade, "age_seconds": age, "max_age_seconds": None, "weight_tonnes": empty_weight, "empty_ladle_weight_tonnes": empty_weight, "position_m": position, "position_code": decoded["raw"], "location_mapping_status": row.get("location_mapping_status")}
    return list(ladles.values())


def latest_crane_snapshots(crane_records: list[dict[str, Any]], selected_plan: list[dict[str, Any]], t0: float) -> list[dict[str, Any]]:
    starts = [_timestamp(row, "ladle_arrival_at") for row in selected_plan]
    ends = [_timestamp(row, "ladle_pour_start_at") or _timestamp(row, "tap_finish_at") for row in selected_plan]
    lower, upper = min((x for x in starts if x is not None), default=t0) - 300, max((x for x in ends if x is not None), default=t0)
    latest: dict[str, tuple[float, dict[str, Any]]] = {}
    for row in crane_records:
        timestamp = _timestamp(row, "updated_at")
        if timestamp is None or timestamp < lower or timestamp > upper or str(row.get("online_status")) not in {"1", "1.0"}:
            continue
        identifier = str(row.get("crane_id"))
        if identifier not in latest or timestamp > latest[identifier][0]:
            latest[identifier] = (timestamp, row)
    # Fallback: if no cranes in the time window, use the latest snapshot of each online crane
    if not latest:
        for row in crane_records:
            if str(row.get("online_status")) not in {"1", "1.0"}:
                continue
            timestamp = _timestamp(row, "updated_at")
            if timestamp is None:
                continue
            identifier = str(row.get("crane_id"))
            if identifier not in latest or timestamp > latest[identifier][0]:
                latest[identifier] = (timestamp, row)
    cranes = []
    for _, row in latest.values():
        featured = crane_features(row)
        max_load = _number(featured.get("max_load_tonnes"), DEFAULT_MAX_LOAD_TONNES)
        weight = _number(featured.get("weight_tonnes"))
        cranes.append({"crane_id": str(featured["crane_id"]), "current_load_tonnes": weight / 1000.0 if weight > 1000 else weight, "max_load_tonnes": max_load, "position_m": _number(featured.get("position_x"), featured["position_m"]), "speed_mps": featured["speed_mps"] * COORDINATE_UNITS_PER_METER, "safe_distance_m": featured["safe_distance_m"], "limit_0_m": featured["limit_0_m"], "limit_1_m": featured["limit_1_m"]})
    return cranes


def build_real_data_scenario(plan_records: list[dict[str, Any]], crane_records: list[dict[str, Any]], limit: int = 20) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    crane_times = [_timestamp(row, "updated_at") for row in crane_records]
    available_times = [value for value in crane_times if value is not None]
    crane_range = (min(available_times), max(available_times)) if available_times else None
    selected = select_pending_heats(plan_records, limit, crane_range)
    t0_candidates = [_timestamp(row, "ladle_arrival_at") or _timestamp(row, "tap_finish_at") for row in selected]
    t0 = min((value for value in t0_candidates if value is not None), default=0.0)
    heats = [_heat(row, t0) for row in selected]
    ladles = build_ladle_pool(plan_records, t0)
    cranes = latest_crane_snapshots(crane_records, selected, t0)
    return heats, ladles, cranes


def build_scenario_from_real_snapshots(
    plan_records: list[dict[str, Any]],
    crane_snapshots: list[dict[str, Any]],
    limit: int = 1_000_000,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a scenario from pre-filtered PLAN rows and traceable CRANE snapshots."""
    selected = select_pending_heats(plan_records, limit, crane_range=None)
    t0_candidates = [_timestamp(row, "ladle_arrival_at") or _timestamp(row, "tap_finish_at") for row in selected]
    t0 = min((value for value in t0_candidates if value is not None), default=0.0)
    heats = [_heat(row, t0) for row in selected]
    ladles = build_ladle_pool(plan_records, t0)
    cranes = []
    for row in crane_snapshots:
        featured = crane_features(row)
        max_load = _number(featured.get("max_load_tonnes"), DEFAULT_MAX_LOAD_TONNES)
        weight = _number(featured.get("weight_tonnes"))
        speed = _number(featured.get("speed_mps"), 2.0) * COORDINATE_UNITS_PER_METER
        safe = _number(featured.get("safe_distance_m"), 10.0)
        lower = _number(featured.get("limit_0_m"), 0.0)
        upper = _number(featured.get("limit_1_m"), 48.0)
        # Plant-supplied limits and safe distances are metres when their scale
        # is much smaller than the PLAN X-coordinate scale.
        safe = safe * COORDINATE_UNITS_PER_METER if 0 < safe <= 100 else safe
        lower = lower * COORDINATE_UNITS_PER_METER if 0 < abs(lower) <= 100 else lower
        upper = upper * COORDINATE_UNITS_PER_METER if 0 < abs(upper) <= 100 else upper
        if upper <= lower:
            lower, upper = 0.0, 48000.0
        cranes.append({
            "crane_id": str(featured["crane_id"]),
            "current_load_tonnes": max(0.0, weight / 1000.0 if weight > 1000 else weight),
            "max_load_tonnes": max_load or DEFAULT_MAX_LOAD_TONNES,
            "position_m": _number(featured.get("position_x"), featured["position_m"]),
            "speed_mps": speed,
            "safe_distance_m": safe,
            "limit_0_m": lower,
            "limit_1_m": upper,
            "source_updated_at": row.get("updated_at"),
        })
    return heats, ladles, cranes
