"""Auditable single-event disturbances using one explicit time coordinate."""
from __future__ import annotations

import random
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


CRANE_OFFLINE = "crane_offline"
LADLE_UNAVAILABLE = "ladle_unavailable"
FACILITY_UNAVAILABLE = "facility_unavailable"
SCHEDULE_DEVIATION = "schedule_deviation"
DISTURBANCE_KINDS = frozenset({
    CRANE_OFFLINE, LADLE_UNAVAILABLE, FACILITY_UNAVAILABLE, SCHEDULE_DEVIATION,
})
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
    if spec.kind == CRANE_OFFLINE:
        return _assigned_heat_ids(assignments, "crane_id", spec.resource_id)
    if spec.kind == LADLE_UNAVAILABLE:
        return _assigned_heat_ids(assignments, "ladle_id", spec.resource_id)
    if spec.kind == FACILITY_UNAVAILABLE:
        fields = ("facility_id", "facility", "refining_route")
        return [str(heat["heat_id"]) for heat in heats if any(str(heat.get(field, "")) == spec.resource_id for field in fields)]
    configured = spec.metadata.get("affected_heat_ids")
    if configured is not None:
        return [str(heat_id) for heat_id in configured]
    return [spec.resource_id] if any(str(heat["heat_id"]) == spec.resource_id for heat in heats) else []


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

    remaining_ladles = [dict(ladle) for ladle in ladles]
    remaining_cranes = [dict(crane) for crane in cranes]
    if spec.kind == CRANE_OFFLINE:
        remaining_cranes = [crane for crane in remaining_cranes if str(crane["crane_id"]) != spec.resource_id]
    elif spec.kind == LADLE_UNAVAILABLE:
        remaining_ladles = [ladle for ladle in remaining_ladles if str(ladle["ladle_id"]) != spec.resource_id]

    reallocation = [deepcopy(heat_map[heat_id]) for heat_id in affected]
    if spec.kind == SCHEDULE_DEVIATION:
        shift = float(spec.metadata.get("delay_seconds", 0.0) or 0.0)
        for heat in reallocation:
            for field in ("window_start", "window_end", "pour_at", "blow_at"):
                if heat.get(field) is not None:
                    heat[field] = float(heat[field]) + shift

    pours = [_pour_at(heat_map[heat_id]) for heat_id in affected]
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
        baseline_heats=heats,
        baseline_ladles=ladles,
        baseline_cranes=cranes,
        baseline_assignments=assignments,
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
        audit=audit,
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
