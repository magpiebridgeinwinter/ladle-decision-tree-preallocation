"""Shared lifecycle state for rolling preallocation and local rescheduling."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


UNALLOCATED = "unallocated"
PREALLOCATED = "preallocated"
LOCKED = "locked"
VALID_STATES = frozenset({UNALLOCATED, PREALLOCATED, LOCKED})


@dataclass
class HeatLifecycle:
    """The mutable scheduling state for one heat, with immutable audit rows."""

    heat_id: str
    pour_at: float
    state: str = UNALLOCATED
    preallocated_at: float | None = None
    locked_at: float | None = None
    assignment: dict[str, Any] | None = None
    revision: int = 0
    audit: list[dict[str, Any]] = field(default_factory=list)


class LifecycleManager:
    """Owns all heat state transitions used by the rolling scheduler."""

    def __init__(self, heats: list[dict[str, Any]]):
        self._heats: dict[str, HeatLifecycle] = {}
        for heat in heats:
            heat_id = str(heat["heat_id"])
            pour_at = heat.get("pour_at", heat.get("window_end"))
            if pour_at is None:
                raise ValueError(f"heat {heat_id} has no pour_at/window_end time")
            self._heats[heat_id] = HeatLifecycle(heat_id=heat_id, pour_at=float(pour_at))

    def advance(self, now: float) -> None:
        """Lock preallocated heats once their lock/pour time has arrived."""
        for item in self._heats.values():
            if item.state == PREALLOCATED and now >= item.pour_at:
                self._transition(item, LOCKED, now, "pour_started")

    def eligible_heat_ids(self, now: float, window_seconds: float) -> list[str]:
        self.advance(now)
        return sorted(
            item.heat_id
            for item in self._heats.values()
            if item.state == UNALLOCATED and now <= item.pour_at <= now + window_seconds
        )

    def reschedulable_heat_ids(self, heat_ids: list[str] | None = None) -> list[str]:
        selected = heat_ids if heat_ids is not None else list(self._heats)
        return sorted(
            heat_id for heat_id in selected
            if heat_id in self._heats and self._heats[heat_id].state == PREALLOCATED
        )

    def locked_heat_ids(self) -> list[str]:
        return sorted(item.heat_id for item in self._heats.values() if item.state == LOCKED)

    def apply_assignments(self, assignments: list[dict[str, Any]], now: float, reason: str) -> None:
        """Apply valid assignments without ever overwriting a locked heat."""
        for assignment in assignments:
            heat_id = str(assignment.get("heat_id", ""))
            item = self._heats.get(heat_id)
            if item is None or item.state == LOCKED or assignment.get("action") != "assign":
                continue
            previous = deepcopy(item.assignment)
            item.assignment = deepcopy(assignment)
            if item.state == UNALLOCATED:
                self._transition(item, PREALLOCATED, now, reason, previous)
            else:
                item.revision += 1
                item.audit.append(self._audit_row(item, now, "reallocated", reason, previous))

    def records(self) -> list[dict[str, Any]]:
        return [
            {
                "heat_id": item.heat_id,
                "state": item.state,
                "preallocated_at": item.preallocated_at,
                "locked_at": item.locked_at,
                "assignment": deepcopy(item.assignment),
                "revision": item.revision,
                "audit": deepcopy(item.audit),
            }
            for item in sorted(self._heats.values(), key=lambda value: value.heat_id)
        ]

    def _transition(
        self,
        item: HeatLifecycle,
        target: str,
        now: float,
        reason: str,
        previous: dict[str, Any] | None = None,
    ) -> None:
        if target not in VALID_STATES:
            raise ValueError(f"unknown lifecycle state: {target}")
        if item.state == LOCKED and target != LOCKED:
            raise ValueError(f"locked heat {item.heat_id} cannot transition")
        old = item.state
        item.state = target
        if target == PREALLOCATED:
            item.preallocated_at = now
        elif target == LOCKED:
            item.locked_at = now
        item.audit.append(self._audit_row(item, now, f"{old}->{target}", reason, previous))

    @staticmethod
    def _audit_row(
        item: HeatLifecycle,
        now: float,
        transition: str,
        reason: str,
        previous: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "at": now,
            "transition": transition,
            "reason": reason,
            "revision": item.revision,
            "previous_assignment": previous,
            "assignment": deepcopy(item.assignment),
        }
