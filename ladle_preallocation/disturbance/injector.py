"""Auditable single-event disturbances using one explicit time coordinate."""
from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from ladle_preallocation.disturbance.catalog import (
    ARGON_STATION_UNAVAILABLE,
    CASTER_DELAY,
    CRANE_OFFLINE,
    CRANE_LOAD_RESTRICTED,
    CRANE_RANGE_RESTRICTED,
    CRANE_SPEED_DEGRADED,
    CRANE_TELEMETRY_STALE,
    COMPOUND_DISTURBANCE,
    DISTURBANCE_KINDS,
    FACILITY_UNAVAILABLE,
    LADLE_DAMAGE,
    LADLE_GRADE_CONFLICT,
    LADLE_LINING_ALARM,
    LADLE_OVER_AGE,
    LADLE_UNAVAILABLE,
    PRIORITY_ESCALATION,
    REFINING_ROUTE_CHANGE,
    SCHEDULE_DEVIATION,
    TRANSPORT_CORRIDOR_BLOCKED,
    URGENT_HEAT_INSERTED,
    CONVERTER_DELAY,
)
SAFETY_BUFFER_SECONDS = 90.0


@dataclass
class DisturbanceSpec:
    """A single production event; ``occurred_at`` matches heat ``pour_at``."""

    kind: str
    resource_id: str
    description: str = ""
    occurred_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in DISTURBANCE_KINDS:
            raise ValueError(f"unsupported disturbance kind: {self.kind}")


@dataclass
class DisturbedScenario:
    spec: DisturbanceSpec
    baseline_heats: list[dict[str, Any]]
    baseline_ladles: list[dict[str, Any]]
    baseline_cranes: list[dict[str, Any]]
    baseline_assignments: list[dict[str, Any]]
    affected_heat_ids: list[str]
    remaining_ladles: list[dict[str, Any]]
    remaining_cranes: list[dict[str, Any]]
    frozen_assignments: dict[str, dict[str, Any]]
    heats_needing_reallocation: list[dict[str, Any]]
    earliest_casting_seconds: float | None
    is_emergency: bool
    earliest_pour_at: float | None = None
    remaining_budget_seconds: float | None = None
    locked_heat_ids: list[str] = field(default_factory=list)
    excluded_heat_ids: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)

    @property
    def num_affected(self) -> int:
        return len(self.affected_heat_ids)

    @property
    def num_needing_reallocation(self) -> int:
        return len(self.heats_needing_reallocation)


def _heat_id_map(heats: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(heat["heat_id"]): heat for heat in heats}


def _assigned_heat_ids(assignments: list[dict[str, Any]], field: str, resource_id: str) -> list[str]:
    return [
        str(assignment["heat_id"])
        for assignment in assignments
        if str(assignment.get(field, "") or "") == resource_id
    ]


def _affected_ids(spec: DisturbanceSpec, heats: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> list[str]:
    configured = spec.metadata.get("affected_heat_ids")
    if configured is not None:
        requested = [str(heat_id) for heat_id in configured]
    elif spec.kind in {
        CRANE_OFFLINE, CRANE_SPEED_DEGRADED, CRANE_LOAD_RESTRICTED,
        CRANE_RANGE_RESTRICTED, TRANSPORT_CORRIDOR_BLOCKED,
        CRANE_TELEMETRY_STALE,
    }:
        requested = _assigned_heat_ids(assignments, "crane_id", spec.resource_id)
    elif spec.kind in {LADLE_UNAVAILABLE, LADLE_DAMAGE, LADLE_LINING_ALARM, LADLE_OVER_AGE, LADLE_GRADE_CONFLICT}:
        requested = _assigned_heat_ids(assignments, "ladle_id", spec.resource_id)
    elif spec.kind in {FACILITY_UNAVAILABLE, ARGON_STATION_UNAVAILABLE, REFINING_ROUTE_CHANGE}:
        fields = ("facility_id", "facility", "refining_route")
        requested = [str(heat["heat_id"]) for heat in heats if any(str(heat.get(field, "")) == spec.resource_id for field in fields)]
    elif spec.kind == COMPOUND_DISTURBANCE:
        requested = [str(assignment["heat_id"]) for assignment in assignments if assignment.get("action") == "assign"]
    else:
        requested = [spec.resource_id] if any(str(heat["heat_id"]) == spec.resource_id for heat in heats) else []

    start = spec.metadata.get("window_start")
    end = spec.metadata.get("window_end")
    if start is None and end is None and spec.metadata.get("window_minutes") is not None and spec.occurred_at is not None:
        start = spec.occurred_at
        end = float(spec.occurred_at) + float(spec.metadata["window_minutes"]) * 60.0
    if start is None or end is None:
        return list(dict.fromkeys(requested))
    heat_map = _heat_id_map(heats)
    return list(dict.fromkeys(
        heat_id for heat_id in requested
        if heat_id in heat_map
        and _pour_at(heat_map[heat_id]) is not None
        and float(start) <= float(_pour_at(heat_map[heat_id])) <= float(end)
    ))


def _pour_at(heat: dict[str, Any]) -> float | None:
    value = heat.get("pour_at", heat.get("window_end"))
    return None if value is None else float(value)


def inject_disturbance(
    spec: DisturbanceSpec,
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    frozen_heat_ids: list[str] | None = None,
    locked_heat_ids: list[str] | None = None,
) -> DisturbedScenario:
    """Apply a disturbance without exposing or rewriting locked allocations."""
    heat_map = _heat_id_map(heats)
    locked = set(locked_heat_ids or frozen_heat_ids or [])
    requested = _affected_ids(spec, heats, assignments)
    affected = [heat_id for heat_id in requested if heat_id in heat_map and heat_id not in locked]
    excluded = [heat_id for heat_id in requested if heat_id in locked]

    remaining_ladles = [deepcopy(ladle) for ladle in ladles]
    remaining_cranes = [deepcopy(crane) for crane in cranes]
    deltas: list[dict[str, Any]] = []

    def change_asset(asset_type: str, asset_id: str, before: dict[str, Any], after: dict[str, Any]) -> None:
        deltas.append({"asset_type": asset_type, "asset_id": asset_id, "before": before, "after": after})

    crane_ids = {str(value) for value in spec.metadata.get("offline_crane_ids", ())}
    crane_ids.add(spec.resource_id)
    ladle_ids = {str(value) for value in spec.metadata.get("unavailable_ladle_ids", ())}
    ladle_ids.add(spec.resource_id)
    if spec.kind in {CRANE_OFFLINE, CRANE_TELEMETRY_STALE, COMPOUND_DISTURBANCE}:
        selected = crane_ids if spec.kind != COMPOUND_DISTURBANCE else crane_ids | {str(value) for value in spec.metadata.get("compound_crane_ids", ())}
        for crane in list(remaining_cranes):
            if str(crane.get("crane_id")) not in selected:
                continue
            before = deepcopy(crane)
            remaining_cranes.remove(crane)
            after = {**before, "availability": "unavailable", "controlled_reason": "telemetry_stale" if spec.kind == CRANE_TELEMETRY_STALE else "offline"}
            change_asset("crane", str(crane["crane_id"]), before, after)
    elif spec.kind == CRANE_SPEED_DEGRADED:
        for crane in remaining_cranes:
            if str(crane.get("crane_id")) != spec.resource_id:
                continue
            before = deepcopy(crane)
            if "speed_mps" in spec.metadata:
                crane["speed_mps"] = float(spec.metadata["speed_mps"])
            else:
                crane["speed_mps"] = float(crane.get("speed_mps", 2.0)) * float(spec.metadata.get("speed_factor", 0.5))
            change_asset("crane", spec.resource_id, before, deepcopy(crane))
    elif spec.kind == CRANE_LOAD_RESTRICTED:
        for crane in remaining_cranes:
            if str(crane.get("crane_id")) != spec.resource_id:
                continue
            before = deepcopy(crane)
            if "max_load_tonnes" in spec.metadata:
                crane["max_load_tonnes"] = float(spec.metadata["max_load_tonnes"])
            else:
                crane["max_load_tonnes"] = float(crane.get("max_load_tonnes", 0.0)) * 0.5
            change_asset("crane", spec.resource_id, before, deepcopy(crane))
    elif spec.kind == CRANE_RANGE_RESTRICTED:
        for crane in remaining_cranes:
            if str(crane.get("crane_id")) != spec.resource_id:
                continue
            before = deepcopy(crane)
            lower = float(crane.get("limit_0_m", 0.0))
            upper = float(crane.get("limit_1_m", 48000.0))
            crane["limit_0_m"] = float(spec.metadata.get("limit_0_m", lower + (upper - lower) * 0.25))
            crane["limit_1_m"] = float(spec.metadata.get("limit_1_m", upper - (upper - lower) * 0.25))
            change_asset("crane", spec.resource_id, before, deepcopy(crane))
    elif spec.kind == TRANSPORT_CORRIDOR_BLOCKED:
        for crane in remaining_cranes:
            if str(crane.get("crane_id")) != spec.resource_id:
                continue
            before = deepcopy(crane)
            crane["blocked_corridor"] = spec.metadata.get("blocked_corridor", True)
            crane["active_positions"] = list(spec.metadata.get("active_positions", crane.get("active_positions", ())))
            change_asset("crane", spec.resource_id, before, deepcopy(crane))

    if spec.kind in {LADLE_UNAVAILABLE, LADLE_DAMAGE, LADLE_LINING_ALARM, LADLE_OVER_AGE, LADLE_GRADE_CONFLICT, COMPOUND_DISTURBANCE}:
        selected = ladle_ids if spec.kind != COMPOUND_DISTURBANCE else ladle_ids | {str(value) for value in spec.metadata.get("compound_ladle_ids", ())}
        for ladle in list(remaining_ladles):
            if str(ladle.get("ladle_id")) not in selected:
                continue
            before = deepcopy(ladle)
            if spec.kind in {LADLE_UNAVAILABLE, LADLE_DAMAGE, LADLE_LINING_ALARM, COMPOUND_DISTURBANCE}:
                remaining_ladles.remove(ladle)
                after = {**before, "availability": "unavailable", "controlled_reason": spec.kind}
            elif spec.kind == LADLE_OVER_AGE:
                ladle["age_seconds"] = float(spec.metadata.get("age_seconds", ladle.get("age_seconds", 0.0)))
                ladle["max_age_seconds"] = float(spec.metadata.get("max_age_seconds", 3600.0))
                after = deepcopy(ladle)
            else:
                ladle["grade"] = str(spec.metadata.get("conflict_grade", "CONTROLLED_CONFLICT"))
                after = deepcopy(ladle)
            change_asset("ladle", str(ladle["ladle_id"]), before, after)

    reallocation = [deepcopy(heat_map[heat_id]) for heat_id in affected]
    if spec.kind in {SCHEDULE_DEVIATION, CONVERTER_DELAY, CASTER_DELAY}:
        shift = float(spec.metadata.get("delay_seconds", 120.0) or 120.0)
        if spec.kind == CONVERTER_DELAY:
            shift = float(spec.metadata.get("delay_seconds", 240.0))
        elif spec.kind == CASTER_DELAY:
            shift = float(spec.metadata.get("delay_seconds", 180.0))
        for heat in reallocation:
            before = {field: heat.get(field) for field in ("window_start", "window_end", "pour_at", "blow_at")}
            for field in ("window_start", "window_end", "pour_at", "blow_at"):
                if heat.get(field) is not None:
                    heat[field] = float(heat[field]) + shift
            deltas.append({"asset_type": "heat", "asset_id": str(heat["heat_id"]), "before": before, "after": {field: heat.get(field) for field in before}})
    elif spec.kind in {URGENT_HEAT_INSERTED, PRIORITY_ESCALATION}:
        for heat in reallocation:
            before = {"priority": heat.get("priority"), "urgent_inserted": heat.get("urgent_inserted")}
            heat["priority"] = float(spec.metadata.get("priority", 100.0 if spec.kind == URGENT_HEAT_INSERTED else 50.0))
            if spec.kind == URGENT_HEAT_INSERTED:
                heat["urgent_inserted"] = True
            deltas.append({"asset_type": "heat", "asset_id": str(heat["heat_id"]), "before": before, "after": {"priority": heat.get("priority"), "urgent_inserted": heat.get("urgent_inserted")}})

    if spec.kind in {FACILITY_UNAVAILABLE, ARGON_STATION_UNAVAILABLE, REFINING_ROUTE_CHANGE, COMPOUND_DISTURBANCE}:
        allowed = list(spec.metadata.get("allowed_routes", ()))
        blocked = list(spec.metadata.get("blocked_routes", ()))
        for heat in reallocation:
            route = str(heat.get("refining_route") or "")
            deltas.append({"asset_type": "route_policy", "asset_id": str(heat["heat_id"]), "before": {"refining_route": route}, "after": {"refining_route": route, "allowed_routes": allowed, "blocked_routes": blocked}})

    # Schedule events move the local production axis; budget must use the
    # post-event pour time that the response actually has to protect.
    pours = [_pour_at(heat) for heat in reallocation]
    earliest = min(value for value in pours if value is not None) if any(value is not None for value in pours) else None
    budget = None if earliest is None or spec.occurred_at is None else earliest - float(spec.occurred_at) - SAFETY_BUFFER_SECONDS
    # Legacy relative fixtures omit event time; preserve their documented <=90 interpretation.
    emergency = budget <= 0.0 if budget is not None else (earliest is not None and earliest <= SAFETY_BUFFER_SECONDS)

    frozen_assignments = {
        str(assignment["heat_id"]): dict(assignment)
        for assignment in assignments
        if str(assignment["heat_id"]) not in affected
    }
    audit = {
        "event": {
            "kind": spec.kind,
            "resource_id": spec.resource_id,
            "occurred_at": spec.occurred_at,
            "metadata": deepcopy(spec.metadata),
            "description": spec.description,
        },
        "affected_heat_ids": affected,
        "locked_heat_ids": sorted(locked),
        "excluded_locked_heat_ids": excluded,
        "earliest_pour_at": earliest,
        "remaining_budget_seconds": budget,
    }
    return DisturbedScenario(
        spec=spec,
        baseline_heats=deepcopy(heats),
        baseline_ladles=deepcopy(ladles),
        baseline_cranes=deepcopy(cranes),
        baseline_assignments=deepcopy(assignments),
        affected_heat_ids=affected,
        remaining_ladles=remaining_ladles,
        remaining_cranes=remaining_cranes,
        frozen_assignments=frozen_assignments,
        heats_needing_reallocation=reallocation,
        earliest_casting_seconds=earliest,
        is_emergency=emergency,
        earliest_pour_at=earliest,
        remaining_budget_seconds=budget,
        locked_heat_ids=sorted(locked),
        excluded_heat_ids=excluded,
        audit={**audit, "event_state_deltas": deltas, "impact_scope": {"affected_heat_ids": affected, "excluded_locked_heat_ids": excluded, "outside_scope_heat_ids": sorted(set(heat_map) - set(affected) - set(excluded))}},
    )


def random_disturbance(
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    disturbance_probability: float = 0.3,
    frozen_heat_ids: list[str] | None = None,
    seed: int | None = None,
) -> DisturbedScenario | None:
    """Build a reproducible single-event scenario across all supported kinds."""
    rng = random.Random(seed)
    if rng.random() > disturbance_probability or not assignments:
        return None
    # Random replay remains restricted to the four legacy events whose state
    # transformations are fully represented by this generic injector.
    kinds = (CRANE_OFFLINE, LADLE_UNAVAILABLE, FACILITY_UNAVAILABLE, SCHEDULE_DEVIATION)
    kind = rng.choice(kinds)
    assigned_cranes = sorted({str(row["crane_id"]) for row in assignments if row.get("crane_id")})
    assigned_ladles = sorted({str(row["ladle_id"]) for row in assignments if row.get("ladle_id")})
    facilities = sorted({str(heat.get("facility_id") or heat.get("facility") or heat.get("refining_route")) for heat in heats if heat.get("facility_id") or heat.get("facility") or heat.get("refining_route")})
    heat_ids = sorted(str(heat["heat_id"]) for heat in heats)
    if kind == CRANE_OFFLINE and assigned_cranes:
        resource_id, description, metadata = rng.choice(assigned_cranes), "行车离线故障", {}
    elif kind == LADLE_UNAVAILABLE and assigned_ladles:
        resource_id, description, metadata = rng.choice(assigned_ladles), "钢包不可用", {}
    elif kind == FACILITY_UNAVAILABLE and facilities:
        resource_id, description, metadata = rng.choice(facilities), "设施不可用", {}
    elif heat_ids:
        resource_id, description, metadata = rng.choice(heat_ids), "计划偏差", {"delay_seconds": rng.choice((60.0, 120.0, 300.0))}
        kind = SCHEDULE_DEVIATION
    else:
        return None
    candidates = [value for value in (_pour_at(heat) for heat in heats) if value is not None]
    occurred_at = rng.uniform(min(candidates), max(candidates)) if candidates else 0.0
    spec = DisturbanceSpec(kind, resource_id, description, occurred_at, metadata)
    return inject_disturbance(spec, heats, ladles, cranes, assignments, frozen_heat_ids)
