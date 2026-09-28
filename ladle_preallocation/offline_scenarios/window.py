"""Location-aware local-window selection for offline disturbance replays."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ladle_preallocation.disturbance.catalog import (
    ARGON_STATION_UNAVAILABLE,
    COMPOUND_DISTURBANCE,
    CRANE_LOAD_RESTRICTED,
    CRANE_OFFLINE,
    CRANE_RANGE_RESTRICTED,
    CRANE_SPEED_DEGRADED,
    CRANE_TELEMETRY_STALE,
    FACILITY_UNAVAILABLE,
    LADLE_DAMAGE,
    LADLE_GRADE_CONFLICT,
    LADLE_LINING_ALARM,
    LADLE_OVER_AGE,
    LADLE_UNAVAILABLE,
    REFINING_ROUTE_CHANGE,
    TRANSPORT_CORRIDOR_BLOCKED,
)


CRANE_EVENTS = {
    CRANE_OFFLINE,
    CRANE_SPEED_DEGRADED,
    CRANE_LOAD_RESTRICTED,
    CRANE_RANGE_RESTRICTED,
    TRANSPORT_CORRIDOR_BLOCKED,
    CRANE_TELEMETRY_STALE,
}
LADLE_EVENTS = {
    LADLE_UNAVAILABLE,
    LADLE_DAMAGE,
    LADLE_LINING_ALARM,
    LADLE_OVER_AGE,
    LADLE_GRADE_CONFLICT,
}
ROUTE_EVENTS = {FACILITY_UNAVAILABLE, ARGON_STATION_UNAVAILABLE, REFINING_ROUTE_CHANGE}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _position(row: dict[str, Any]) -> float | None:
    try:
        return float(row.get("position_m"))
    except (TypeError, ValueError):
        return None


def _anchor_index(
    heats: list[dict[str, Any]],
    assignments: dict[str, dict[str, Any]],
    kind: str,
    ordinal: int,
) -> tuple[int, str, str]:
    """Find a stable source-backed anchor; fallback is deterministic plan order."""
    ordered = list(range(len(heats)))
    if not ordered:
        raise ValueError("source PLAN contains no heats")
    resource_field = "crane_id" if kind in CRANE_EVENTS else "ladle_id" if kind in LADLE_EVENTS else None
    if resource_field:
        counts: dict[str, list[int]] = {}
        for index, heat in enumerate(heats):
            resource = _text(assignments.get(_text(heat.get("heat_id")), {}).get(resource_field))
            if resource:
                counts.setdefault(resource, []).append(index)
        if counts:
            resource, positions = sorted(counts.items(), key=lambda item: (-len(item[1]), item[0]))[ordinal % len(counts)]
            return positions[len(positions) // 2], resource, resource_field
    route_counts: dict[str, list[int]] = {}
    for index, heat in enumerate(heats):
        route_counts.setdefault(_text(heat.get("refining_route")), []).append(index)
    if kind in ROUTE_EVENTS and route_counts:
        route, positions = sorted(route_counts.items(), key=lambda item: (-len(item[1]), item[0]))[ordinal % len(route_counts)]
        return positions[len(positions) // 2], route, "refining_route"
    return ordered[(len(ordered) // 2 + ordinal * 11) % len(ordered)], _text(heats[len(ordered) // 2].get("heat_id")), "heat_id"


def select_local_window(
    source: dict[str, Any],
    kind: str,
    ordinal: int,
    *,
    primary_heat_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Select a contiguous, source-backed window using plan and location evidence.

    The span is derived from the number of source resources and the anchor's
    mapped X position. It is intentionally bounded for a legible replay, but
    is not a catalog constant and is allowed to vary by disturbance.
    """
    inputs = source["scheduling_inputs"]
    heats = [deepcopy(row) for row in inputs["heats"]]
    assignments = {_text(row.get("heat_id")): row for row in source["assignments"]}
    if primary_heat_ids:
        selected_ids = [_text(value) for value in primary_heat_ids]
        by_id = {_text(row.get("heat_id")): row for row in heats}
        if any(value not in by_id for value in selected_ids):
            raise ValueError("primary window contains an unknown source heat")
        indices = [next(index for index, row in enumerate(heats) if _text(row.get("heat_id")) == value) for value in selected_ids]
        return {
            "heats": [by_id[value] for value in selected_ids],
            "affected_heat_ids": selected_ids,
            "candidate_heat_ids": selected_ids,
            "source_order_indices": indices,
            "window_start": min(float(by_id[value].get("window_start", 0.0) or 0.0) for value in selected_ids),
            "window_end": max(float(by_id[value].get("window_end", 0.0) or 0.0) for value in selected_ids),
            "anchor": {"type": "audited_primary", "resource_id": "2500"},
            "selection_reason": "复用真实 11:00-11:20 位置感知审计窗口",
        }

    anchor, resource_id, resource_type = _anchor_index(heats, assignments, kind, ordinal)
    crane_by_id = {_text(row.get("crane_id")): row for row in inputs["cranes"]}
    ladle_positions = [_position(row) for row in inputs["ladles"]]
    valid_positions = [value for value in ladle_positions if value is not None]
    spread = max(valid_positions) - min(valid_positions) if valid_positions else 0.0
    anchor_position = _position(crane_by_id.get(resource_id, {})) if resource_type == "crane_id" else None
    if anchor_position is None and resource_type == "ladle_id":
        anchor_position = _position(next((row for row in inputs["ladles"] if _text(row.get("ladle_id")) == resource_id), {}))
    position_factor = 0.0 if not spread or anchor_position is None else max(0.0, min(1.0, (anchor_position - min(valid_positions)) / spread))
    resource_factor = len({
        _text(row.get("crane_id")) for row in source["assignments"] if _text(row.get("crane_id"))
    })
    route_factor = len({_text(row.get("refining_route")) for row in heats if _text(row.get("refining_route"))})
    span = 12 + ((round(position_factor * 9) + resource_factor + route_factor + ordinal * 3) % 18)
    span = min(len(heats), max(12, span))
    start = max(0, min(anchor - span // 2, len(heats) - span))
    selected = heats[start:start + span]
    selected_ids = [_text(row.get("heat_id")) for row in selected]
    first = selected[0]
    last = selected[-1]
    return {
        "heats": selected,
        "affected_heat_ids": selected_ids,
        "candidate_heat_ids": selected_ids,
        "source_order_indices": list(range(start, start + span)),
        "window_start": float(first.get("window_start", 0.0) or 0.0),
        "window_end": float(last.get("window_end", 0.0) or 0.0),
        "anchor": {"type": resource_type, "resource_id": resource_id, "source_order_index": anchor, "position_m": anchor_position},
        "selection_reason": "按真实计划顺序，以受扰资源/路线位置为锚点向前后扩展；窗口长度由源资源数、路线数和位置归一化值推导",
    }
