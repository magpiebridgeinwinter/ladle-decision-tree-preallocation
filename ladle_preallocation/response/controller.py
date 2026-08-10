"""Tiered response controller: decision-tree rerank → LLM ReAct → Frozen.

Implements the disturbance response flow from the report:
- Emergency (earliest_casting <= 90s): decision tree fast rerank,
  failure → Frozen + call human.
- Non-emergency (earliest_casting > 90s): decision tree rerank first,
  failure → LLM ReAct, failure → Frozen + alarm.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ladle_preallocation.decision_tree.allocator import allocate as dt_allocate
from ladle_preallocation.decision_tree.validation import validate_output
from ladle_preallocation.disturbance.injector import DisturbedScenario


class ResponsePath(str, Enum):
    """Which path the response took."""

    DECISION_TREE_SUCCESS = "decision_tree_success"
    DECISION_TREE_FAILURE = "decision_tree_failure"
    LLM_REACT_SUCCESS = "llm_react_success"
    LLM_REACT_FAILURE = "llm_react_failure"
    FROZEN = "frozen"
    CALL_HUMAN = "call_human"


@dataclass
class ResponseResult:
    """Result of a single response attempt."""

    path: ResponsePath
    assignments: list[dict[str, Any]]
    success: bool
    elapsed_seconds: float
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def num_assigned(self) -> int:
        return sum(1 for a in self.assignments if a.get("action") == "assign")

    @property
    def num_failed(self) -> int:
        return sum(1 for a in self.assignments if a.get("action") != "assign")


@dataclass
class ThreeWayComparison:
    """Compare three paths: Frozen, Decision Tree, LLM ReAct."""

    scenario_id: str
    disturbance_desc: str

    num_affected: int
    num_total: int

    frozen: ResponseResult
    decision_tree: ResponseResult
    llm_react: ResponseResult | None = None

    @property
    def dt_saved(self) -> int:
        """How many heats did decision tree save over frozen."""
        return self.decision_tree.num_assigned - self.frozen.num_assigned

    @property
    def llm_saved(self) -> int | None:
        """How many heats did LLM save over decision tree."""
        if self.llm_react is None:
            return None
        return self.llm_react.num_assigned - self.decision_tree.num_assigned

    @property
    def llm_delta_from_frozen(self) -> int | None:
        """How many heats did LLM save over frozen."""
        if self.llm_react is None:
            return None
        return self.llm_react.num_assigned - self.frozen.num_assigned

    def summary(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "disturbance": self.disturbance_desc,
            "num_affected": self.num_affected,
            "num_total": self.num_total,
            "frozen_assigned": self.frozen.num_assigned,
            "dt_assigned": self.decision_tree.num_assigned,
            "dt_saved": self.dt_saved,
            "dt_path": self.decision_tree.path.value,
            "dt_elapsed_s": round(self.decision_tree.elapsed_seconds, 4),
            "llm_assigned": self.llm_react.num_assigned if self.llm_react else None,
            "llm_saved_over_dt": self.llm_saved,
            "llm_saved_over_frozen": self.llm_delta_from_frozen,
            "llm_path": self.llm_react.path.value if self.llm_react else None,
            "llm_elapsed_s": round(self.llm_react.elapsed_seconds, 4) if self.llm_react else None,
        }


class TieredResponseController:
    """Controller for the disturbance response pipeline.

    Flow:
    1. Try decision tree rerank on remaining resources
    2. If emergency (< 90s) and DT fails → Frozen + call human
    3. If non-emergency (> 90s) and DT fails → LLM ReAct
    4. If LLM fails → Frozen + alarm
    """

    EMERGENCY_THRESHOLD = 90.0  # seconds

    def __init__(self, llm_rescheduler: Callable | None = None):
        """Initialize with optional LLM rescheduler function.

        Args:
            llm_rescheduler: Callable that takes (heats, ladles, cranes) and
                returns (success: bool, assignments: list[dict]).
        """
        self._llm = llm_rescheduler

    def _run_decision_tree(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        path_label: str,
    ) -> ResponseResult:
        """Run decision tree allocation and return result."""
        t0 = time.perf_counter()
        try:
            raw = dt_allocate(heats, ladles, cranes)
            validated = validate_output(heats, ladles, cranes, raw)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return ResponseResult(
                path=ResponsePath.DECISION_TREE_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=elapsed,
                reason=f"决策树异常: {exc}",
            )
        elapsed = time.perf_counter() - t0
        success = all(a.get("action") == "assign" for a in validated)
        return ResponseResult(
            path=ResponsePath.DECISION_TREE_SUCCESS if success else ResponsePath.DECISION_TREE_FAILURE,
            assignments=validated,
            success=success,
            elapsed_seconds=elapsed,
            reason=f"{path_label}：{'全部成功' if success else '存在未分配炉次'}",
            extra={"algorithm": "decision_tree"},
        )

    def _run_llm_react(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
    ) -> ResponseResult:
        """Run LLM ReAct rescheduling."""
        if self._llm is None:
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=0.0,
                reason="LLM 重调度器未配置",
            )
        t0 = time.perf_counter()
        try:
            success, assignments = self._llm(heats, ladles, cranes)
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=elapsed,
                reason=f"LLM ReAct 异常: {exc}",
            )
        elapsed = time.perf_counter() - t0
        return ResponseResult(
            path=ResponsePath.LLM_REACT_SUCCESS if success else ResponsePath.LLM_REACT_FAILURE,
            assignments=assignments,
            success=success,
            elapsed_seconds=elapsed,
            reason="LLM ReAct 重调度成功" if success else "LLM ReAct 未能解决所有冲突",
            extra={"algorithm": "llm_react"},
        )

    def _frozen_result(
        self,
        baseline_assignments: list[dict[str, Any]],
        affected_heat_ids: list[str],
    ) -> ResponseResult:
        """Build the frozen (no reallocation) result."""
        affected_set = set(affected_heat_ids)
        frozen = []
        for a in baseline_assignments:
            row = dict(a)
            if str(row.get("heat_id", "")) in affected_set:
                row["action"] = "unassigned"
                row["ladle_id"] = None
                row["crane_id"] = None
                row["reason"] = "扰动影响，原地硬扛（Frozen）"
                row["expected_arrival_seconds"] = None
            frozen.append(row)
        return ResponseResult(
            path=ResponsePath.FROZEN,
            assignments=frozen,
            success=False,
            elapsed_seconds=0.0,
            reason="原地不动硬扛",
            extra={"algorithm": "frozen"},
        )

    def handle_disturbance(
        self,
        scenario: DisturbedScenario,
    ) -> tuple[ResponseResult, ResponseResult | None]:
        """Execute the tiered response.

        Returns:
            (primary_result, llm_result):
            - primary_result is always the effective response
            - llm_result is the LLM result (or None if not attempted)
        """
        remaining_heats = scenario.heats_needing_reallocation

        if not remaining_heats:
            # No heats to reallocate, keep baseline
            return (
                ResponseResult(
                    path=ResponsePath.FROZEN,
                    assignments=scenario.baseline_assignments,
                    success=True,
                    elapsed_seconds=0.0,
                    reason="无受波及炉次",
                    extra={"algorithm": "frozen"},
                ),
                None,
            )

        # Step 1: Try decision tree rerank
        dt_result = self._run_decision_tree(
            remaining_heats,
            scenario.remaining_ladles,
            scenario.remaining_cranes,
            "决策树重排",
        )

        if dt_result.success:
            # Decision tree succeeded → merge with frozen assignments
            merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in dt_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            dt_result.assignments = merged
            return dt_result, None

        # Step 2: Decision tree failed → check emergency threshold
        if scenario.is_emergency:
            frozen = self._frozen_result(
                scenario.baseline_assignments,
                scenario.affected_heat_ids,
            )
            frozen.reason = "紧急场景（≤90s），决策树失败，Frozen + 呼叫人工"
            return frozen, None

        # Step 3: Non-emergency → LLM ReAct
        llm_result = self._run_llm_react(
            remaining_heats,
            scenario.remaining_ladles,
            scenario.remaining_cranes,
        )

        if llm_result.success:
            merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in llm_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            llm_result.assignments = merged
            return llm_result, llm_result

        # Step 4: LLM also failed → Frozen + alarm
        frozen = self._frozen_result(
            scenario.baseline_assignments,
            scenario.affected_heat_ids,
        )
        frozen.reason = "决策树+LLM 均失败，Frozen + 告警等人工"
        return frozen, llm_result

    def run_three_way(
        self,
        scenario: DisturbedScenario,
        scenario_id: str = "1",
    ) -> ThreeWayComparison:
        """Run and compare all three paths: Frozen, DT, LLM.

        This is for batch experiment evaluation — runs all paths regardless
        of success/failure.
        """
        # Frozen
        frozen = self._frozen_result(
            scenario.baseline_assignments,
            scenario.affected_heat_ids,
        )

        # Decision Tree rerank
        remaining_heats = scenario.heats_needing_reallocation
        if remaining_heats:
            dt_result = self._run_decision_tree(
                remaining_heats,
                scenario.remaining_ladles,
                scenario.remaining_cranes,
                "决策树重排",
            )
            dt_merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in dt_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            dt_result.assignments = dt_merged
        else:
            dt_result = ResponseResult(
                path=ResponsePath.DECISION_TREE_SUCCESS,
                assignments=scenario.baseline_assignments,
                success=True,
                elapsed_seconds=0.0,
                reason="无受波及炉次",
                extra={"algorithm": "decision_tree"},
            )

        # LLM ReAct (only if DT failed and we have LLM)
        llm = None
        if not dt_result.success and self._llm is not None and remaining_heats:
            llm_result = self._run_llm_react(
                remaining_heats,
                scenario.remaining_ladles,
                scenario.remaining_cranes,
            )
            llm_merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in llm_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            llm_result.assignments = llm_merged
            llm = llm_result

        return ThreeWayComparison(
            scenario_id=scenario_id,
            disturbance_desc=scenario.spec.description,
            num_affected=scenario.num_affected,
            num_total=len(scenario.baseline_assignments),
            frozen=frozen,
            decision_tree=dt_result,
            llm_react=llm,
        )


def _merge_assignments(
    frozen: dict[str, dict[str, Any]],
    new_assignments: dict[str, dict[str, Any]],
    reference_keys: list[str],
) -> list[dict[str, Any]]:
    """Merge frozen and new assignments into a complete list."""
    merged: dict[str, dict[str, Any]] = {}
    for hid, a in frozen.items():
        merged[hid] = dict(a)
    for hid, a in new_assignments.items():
        row = dict(a)
        if not reference_keys:
            merged[hid] = row
        else:
            out = {k: row.get(k) for k in reference_keys if k in row}
            merged[hid] = out
    return list(merged.values())
