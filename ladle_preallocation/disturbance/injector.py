"""Disturbance injector: simulate equipment failures in the production environment.

Simulates production abnormalities such as:
- Crane going offline (equipment failure)
- Ladle becoming unavailable (maintenance / scrap)
- Crane position shift (emergency stop)

Computes:
- Affected heats (those assigned to the failed resource)
- Earliest casting deadline among affected heats
- Remaining available resources
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DisturbanceSpec:
    """Defines what kind of disturbance to inject."""

    kind: str  # "crane_offline", "ladle_unavailable", "crane_position_shift"
    resource_id: str  # crane_id or ladle_id affected
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DisturbedScenario:
    """Result of injecting a disturbance into a baseline scenario."""

    spec: DisturbanceSpec
    # Baseline before disturbance
    baseline_heats: list[dict[str, Any]]
    baseline_ladles: list[dict[str, Any]]
    baseline_cranes: list[dict[str, Any]]
    baseline_assignments: list[dict[str, Any]]
    # Affected heats (those assigned to the now-offline resource)
    affected_heat_ids: list[str]
    # Resources after removing the failed one
    remaining_ladles: list[dict[str, Any]]
    remaining_cranes: list[dict[str, Any]]
    # Preserved assignments for unaffected heats
    frozen_assignments: dict[str, dict[str, Any]]
    # All heats that need reallocation (affected + potentially cascaded)
    heats_needing_reallocation: list[dict[str, Any]]
    # Time until earliest casting among affected heats (seconds)
    earliest_casting_seconds: float | None
    # Is this an emergency (< 90s)?
    is_emergency: bool

    @property
    def num_affected(self) -> int:
        return len(self.affected_heat_ids)

    @property
    def num_needing_reallocation(self) -> int:
        return len(self.heats_needing_reallocation)


def _build_heat_id_map(heats: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(h["heat_id"]): h for h in heats}


def _find_affected_heats(
    assignments: list[dict[str, Any]],
    resource_type: str,
    resource_id: str,
) -> list[str]:
    """Identify heats affected by the failure of a specific resource."""
    affected = []
    key = "crane_id" if resource_type == "crane_offline" else "ladle_id"
    for a in assignments:
        rid = str(a.get(key, "") or "")
        if rid == resource_id:
            affected.append(str(a["heat_id"]))
    return affected


def _calculate_earliest_casting(
    affected_heat_ids: list[str],
    heat_map: dict[str, dict[str, Any]],
) -> float | None:
    """Calculate time until earliest casting deadline among affected heats."""
    if not affected_heat_ids:
        return None
    window_ends = []
    for hid in affected_heat_ids:
        heat = heat_map.get(hid, {})
        we = heat.get("window_end")
        if we is not None:
            window_ends.append(float(we))
    return min(window_ends) if window_ends else None


def inject_disturbance(
    spec: DisturbanceSpec,
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    frozen_heat_ids: list[str] | None = None,
) -> DisturbedScenario:
    """Inject a disturbance and compute the resulting disrupted state.

    Args:
        spec: What kind of disturbance to inject.
        heats: All heats in the scenario.
        ladles: All ladles available.
        cranes: All cranes available.
        assignments: Current allocations (from baseline decision tree).
        frozen_heat_ids: Heats that are already in execution and cannot be
            reassigned (e.g. already being cast).

    Returns:
        DisturbedScenario with affected heats, remaining resources, and timing.
    """
    frozen = set(frozen_heat_ids or [])
    heat_map = _build_heat_id_map(heats)

    # Remove the failed resource
    if spec.kind == "crane_offline":
        remaining_cranes = [c for c in cranes if str(c["crane_id"]) != spec.resource_id]
        remaining_ladles = list(ladles)
    elif spec.kind == "ladle_unavailable":
        remaining_cranes = list(cranes)
        remaining_ladles = [l for l in ladles if str(l["ladle_id"]) != spec.resource_id]
    else:
        remaining_cranes = list(cranes)
        remaining_ladles = list(ladles)

    # Identify affected heats
    affected = _find_affected_heats(assignments, spec.kind, spec.resource_id)
    affected = [h for h in affected if h not in frozen]

    # Build frozen assignments: unaffected + already-frozen heats keep their allocation
    frozen_assignments: dict[str, dict[str, Any]] = {}
    for a in assignments:
        hid = str(a["heat_id"])
        if hid in frozen or hid not in affected:
            frozen_assignments[hid] = a

    # Heats needing reallocation: affected heats that are not frozen
    heats_to_realloc = [heat_map[hid] for hid in affected if hid in heat_map]

    # Calculate timing
    earliest = _calculate_earliest_casting(affected, heat_map)

    is_emergency = earliest is not None and earliest <= 90.0

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
        heats_needing_reallocation=heats_to_realloc,
        earliest_casting_seconds=earliest,
        is_emergency=is_emergency,
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
    """Generate a random disturbance scenario.

    Args:
        heats, ladles, cranes, assignments: Baseline scenario state.
        disturbance_probability: Probability of injecting a disturbance.
        seed: Random seed for reproducibility.

    Returns:
        A DisturbedScenario if a disturbance was generated, None otherwise.
    """
    rng = random.Random(seed)

    # Randomly decide whether to generate a disturbance
    if rng.random() > disturbance_probability:
        return None

    # Choose disturbance type: prefer crane_offline (most common in production)
    kinds = ["crane_offline", "crane_offline", "crane_offline", "ladle_unavailable"]
    kind = rng.choice(kinds)

    # Pick a random resource
    if kind == "crane_offline":
        assigned_cranes = list({str(a.get("crane_id", "")) for a in assignments if a.get("crane_id")})
        if not assigned_cranes:
            return None
        resource_id = rng.choice(assigned_cranes)
        desc = f"行车 {resource_id} 离线故障"
    else:
        assigned_ladles = list({str(a.get("ladle_id", "")) for a in assignments if a.get("ladle_id")})
        if not assigned_ladles:
            return None
        resource_id = rng.choice(assigned_ladles)
        desc = f"钢包 {resource_id} 不可用"

    spec = DisturbanceSpec(kind=kind, resource_id=resource_id, description=desc)
    return inject_disturbance(spec, heats, ladles, cranes, assignments, frozen_heat_ids)
