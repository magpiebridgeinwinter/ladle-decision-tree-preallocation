"""Tiered response controller: decision-tree rerank → LLM ReAct → Frozen.

Implements the disturbance response flow from the report:
- Emergency (earliest_casting <= 90s): decision tree fast rerank,
  failure → Frozen + call human.
- Non-emergency (earliest_casting > 90s): decision tree rerank first,
  failure → LLM ReAct, failure → Frozen + alarm.
"""

from __future__ import annotations

import time
import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ladle_preallocation.decision_tree.allocator import allocate as dt_allocate
from ladle_preallocation.decision_tree.validation import validate_output
from ladle_preallocation.disturbance.injector import DisturbedScenario
from ladle_preallocation.evaluation.metrics import evaluate_path


class ResponsePath(str, Enum):
    """Which path the response took."""

    DECISION_TREE_SUCCESS = "decision_tree_success"
    DECISION_TREE_FAILURE = "decision_tree_failure"
    LLM_REACT_SUCCESS = "llm_react_success"
    LLM_REACT_FAILURE = "llm_react_failure"
    FROZEN = "frozen"
    CALL_HUMAN = "call_human"


class WorkflowStage(str, Enum):
    """Stages in the production disturbance workflow."""

    SNAPSHOT = "snapshot"
    SCOPE = "scope"
    CONTEXT = "context"
    LLM_PROPOSE = "llm_propose"
    VALIDATE = "validate"
    COMPLETED = "completed"
    DEGRADED = "degraded"


@dataclass
class WorkflowState:
    """Auditable state for one production disturbance response."""

    stage: WorkflowStage = WorkflowStage.SNAPSHOT
    configuration_source: str = "unconfigured"
    budget_status: str = "unknown"
    failure_reasons: list[str] = field(default_factory=list)
    transitions: list[str] = field(default_factory=lambda: [WorkflowStage.SNAPSHOT.value])

    def advance(self, stage: WorkflowStage) -> None:
        self.stage = stage
        self.transitions.append(stage.value)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage.value,
            "configuration_source": self.configuration_source,
            "budget_status": self.budget_status,
            "failure_reasons": list(self.failure_reasons),
            "transitions": list(self.transitions),
        }


@dataclass
class ResponseResult:
    """Result of a single response attempt."""

    path: ResponsePath
    assignments: list[dict[str, Any]]
    success: bool
    elapsed_seconds: float
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    remaining_budget_seconds: float | None = None
    human_review_required: bool = False
    failure_reasons: list[str] = field(default_factory=list)
    validation_feedback: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    workflow: WorkflowState | None = None

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
            "event": self.frozen.extra.get("event", {}),
            "frozen_metrics": self.frozen.metrics,
            "decision_tree_metrics": self.decision_tree.metrics,
            "llm_metrics": self.llm_react.metrics if self.llm_react else None,
            "workflow": self.llm_react.workflow.as_dict() if self.llm_react and self.llm_react.workflow else None,
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

    def __init__(
        self,
        llm_rescheduler: Callable | None = None,
        clock: Callable[[], float] = time.perf_counter,
        rag_context: str | None = None,
        validator: Callable[[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[Any]], list[dict[str, Any]]] = validate_output,
    ):
        """Initialize with optional LLM rescheduler function.

        Args:
            llm_rescheduler: Callable that takes (heats, ladles, cranes) and
                returns (success: bool, assignments: list[dict]).
        """
        self._llm = llm_rescheduler
        self._clock = clock
        self._rag_context = rag_context or ""
        self._validator = validator

    def _run_decision_tree(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        path_label: str,
    ) -> ResponseResult:
        """Run decision tree allocation and return result."""
        t0 = self._clock()
        try:
            raw = dt_allocate(heats, ladles, cranes)
            validated = self._validator(heats, ladles, cranes, raw)
        except Exception as exc:
            elapsed = self._clock() - t0
            return ResponseResult(
                path=ResponsePath.DECISION_TREE_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=elapsed,
                reason=f"决策树异常: {exc}",
            )
        elapsed = self._clock() - t0
        expected_ids = {str(heat["heat_id"]) for heat in heats}
        validated_ids = [str(row.get("heat_id", "")) for row in validated]
        complete = (
            len(validated_ids) == len(expected_ids)
            and set(validated_ids) == expected_ids
            and len(set(validated_ids)) == len(validated_ids)
        )
        success = complete and all(a.get("action") == "assign" for a in validated)
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
        remaining_budget_seconds: float,
        failure_context: dict[str, Any],
    ) -> ResponseResult:
        """Run LLM ReAct rescheduling."""
        if self._llm is None:
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=0.0,
                reason="LLM 重调度器未配置",
                remaining_budget_seconds=remaining_budget_seconds,
            )
        if remaining_budget_seconds <= 0:
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=0.0,
                reason="LLM 时间预算耗尽",
                remaining_budget_seconds=remaining_budget_seconds,
                failure_reasons=["budget_exhausted"],
            )
        t0 = self._clock()
        try:
            result = self._invoke_llm(heats, ladles, cranes, remaining_budget_seconds, failure_context)
        except Exception as exc:
            elapsed = self._clock() - t0
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=elapsed,
                reason=f"LLM ReAct 异常: {exc}",
                remaining_budget_seconds=max(0.0, remaining_budget_seconds - elapsed),
                failure_reasons=["llm_exception"],
            )
        elapsed = self._clock() - t0
        if elapsed > remaining_budget_seconds:
            return ResponseResult(
                path=ResponsePath.LLM_REACT_FAILURE,
                assignments=[],
                success=False,
                elapsed_seconds=elapsed,
                reason="LLM 调用超出剩余时间预算",
                remaining_budget_seconds=0.0,
                failure_reasons=["budget_timeout"],
            )
        success, assignments, feedback = self._normalise_llm_result(result, heats, ladles, cranes)
        return ResponseResult(
            path=ResponsePath.LLM_REACT_SUCCESS if success else ResponsePath.LLM_REACT_FAILURE,
            assignments=assignments,
            success=success,
            elapsed_seconds=elapsed,
            reason="LLM ReAct 重调度成功" if success else "LLM ReAct 未能解决所有冲突或硬约束终检失败",
            extra={"algorithm": "llm_react", "failure_context": failure_context},
            remaining_budget_seconds=max(0.0, remaining_budget_seconds - elapsed),
            failure_reasons=[] if success else ["invalid_or_incomplete_llm_proposal"],
            validation_feedback=feedback,
        )

    def _configuration_source(self) -> str:
        if self._llm is None:
            return "unconfigured"
        configured_source = getattr(self._llm, "configuration_source", None)
        if configured_source:
            return str(configured_source)
        if getattr(self._llm, "api_key", None):
            return "explicit_api_key"
        if hasattr(self._llm, "api_key"):
            return "missing_api_key"
        return "injected_rescheduler"

    @staticmethod
    def _available_ladles(scenario: DisturbedScenario) -> list[dict[str, Any]]:
        """Exclude ladles already held by unaffected/frozen assignments."""
        reserved = {
            str(row.get("ladle_id"))
            for row in scenario.frozen_assignments.values()
            if row.get("action") == "assign" and row.get("ladle_id")
        }
        return [row for row in scenario.remaining_ladles if str(row.get("ladle_id")) not in reserved]

    def _invoke_llm(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        budget: float,
        failure_context: dict[str, Any],
    ) -> Any:
        target = self._llm.reschedule if hasattr(self._llm, "reschedule") else self._llm
        parameters = inspect.signature(target).parameters
        accepts_kwargs = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
        kwargs: dict[str, Any] = {}
        if "remaining_budget_seconds" in parameters or accepts_kwargs:
            kwargs["remaining_budget_seconds"] = budget
        if "failure_context" in parameters or accepts_kwargs:
            kwargs["failure_context"] = failure_context
        if ("rag_context" in parameters or accepts_kwargs) and self._rag_context:
            kwargs["rag_context"] = self._rag_context
        return target(heats, ladles, cranes, **kwargs)

    def _normalise_llm_result(
        self,
        result: Any,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
    ) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
        if hasattr(result, "success"):
            declared_success, assignments = bool(result.success), list(result.assignments)
            feedback = {"agent_reason": getattr(result, "reason", ""), "trace": result.as_dict() if hasattr(result, "as_dict") else {}}
        else:
            declared_success, assignments = result
            feedback = {}
        heat_ids = [str(heat["heat_id"]) for heat in heats]
        returned_ids = [str(row.get("heat_id", "")) for row in assignments]
        complete = len(returned_ids) == len(heat_ids) and set(returned_ids) == set(heat_ids) and len(set(returned_ids)) == len(returned_ids)
        validated = self._validator(heats, ladles, cranes, assignments)
        valid = complete and all(row.get("action") == "assign" for row in validated)
        for row in validated:
            row["algorithm"] = "llm_react"
        feedback["complete"] = complete
        feedback["validated_actions"] = {str(row["heat_id"]): row["action"] for row in validated}
        return bool(declared_success) and valid, validated, feedback

    def _failure_context(
        self,
        scenario: DisturbedScenario,
        decision_tree: ResponseResult,
        budget: float | None,
    ) -> dict[str, Any]:
        """Build the bounded, credential-free context passed to LLM adapters."""
        return {
            "workflow_entry_reason": decision_tree.reason,
            # Keep legacy aliases for consumers that parse old audit files.
            "decision_tree_failure": decision_tree.reason,
            "baseline_actions": {
                str(row.get("heat_id", "")): row.get("action")
                for row in decision_tree.assignments
            },
            "decision_tree_actions": {},
            "affected_heat_ids": list(scenario.affected_heat_ids),
            "excluded_locked_heat_ids": list(scenario.excluded_heat_ids),
            "remaining_budget_seconds": budget,
            "event": scenario.audit.get("event", {}),
            "event_state_deltas": scenario.audit.get("event_state_deltas", []),
            "local_constraints": {
                "heats": [
                    {
                        key: heat.get(key)
                        for key in ("heat_id", "required_grade", "window_start", "window_end", "pour_at", "priority", "refining_route")
                    }
                    for heat in scenario.heats_needing_reallocation
                ],
                "ladles": [
                    {
                        key: ladle.get(key)
                        for key in ("ladle_id", "grade", "position_m", "position_code", "location_mapping_status", "weight_tonnes", "age_seconds", "max_age_seconds")
                    }
                    for ladle in self._available_ladles(scenario)
                ],
                "cranes": [
                    {
                        key: crane.get(key)
                        for key in ("crane_id", "position_m", "speed_mps", "max_load_tonnes", "current_load_tonnes", "safe_distance_m", "limit_0_m", "limit_1_m")
                    }
                    for crane in scenario.remaining_cranes
                ],
            },
        }

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
            human_review_required=True,
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
        workflow = WorkflowState(configuration_source=self._configuration_source())
        workflow.advance(WorkflowStage.SCOPE)
        workflow.budget_status = (
            "unbounded" if scenario.remaining_budget_seconds is None
            else "available" if scenario.remaining_budget_seconds > 0
            else "exhausted"
        )

        if not remaining_heats:
            # No heats to reallocate, keep baseline
            result = ResponseResult(
                    path=ResponsePath.FROZEN,
                    assignments=scenario.baseline_assignments,
                    success=True,
                    elapsed_seconds=0.0,
                    reason="无受波及炉次",
                    extra={"algorithm": "frozen"},
                    workflow=workflow,
                )
            workflow.advance(WorkflowStage.COMPLETED)
            self._attach_metrics(result, scenario)
            return result, None

        workflow.advance(WorkflowStage.CONTEXT)
        budget = scenario.remaining_budget_seconds
        available_ladles = self._available_ladles(scenario)
        # The production path enters the LLM workflow directly. A zero budget
        # remains a hard safety gate and is degraded without making a network call.
        if scenario.is_emergency or (budget is not None and budget <= 0.0):
            workflow.failure_reasons.append("budget_exhausted")
            workflow.advance(WorkflowStage.DEGRADED)
            frozen = self._frozen_result(
                scenario.baseline_assignments,
                scenario.affected_heat_ids,
            )
            frozen.reason = "突发场景未能在安全预算内进入 LLM，Frozen + 呼叫人工"
            frozen.remaining_budget_seconds = budget
            frozen.failure_reasons = ["direct_llm_workflow_budget_exhausted", "budget_exhausted"]
            frozen.workflow = workflow
            self._attach_metrics(frozen, scenario)
            return frozen, None

        workflow.advance(WorkflowStage.LLM_PROPOSE)
        direct_context = ResponseResult(
            path=ResponsePath.DECISION_TREE_FAILURE,
            assignments=[],
            success=False,
            elapsed_seconds=0.0,
            reason="突发场景直接进入 LLM Workflow，未执行决策树重排",
        )
        llm_result = self._run_llm_react(
            remaining_heats,
            available_ladles,
            scenario.remaining_cranes,
            budget if budget is not None else float("inf"),
            self._failure_context(scenario, direct_context, budget),
        )
        llm_result.workflow = workflow
        workflow.advance(WorkflowStage.VALIDATE)

        if llm_result.success:
            merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in llm_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            llm_result.assignments = merged
            if _preserves_unaffected(merged, scenario.baseline_assignments, scenario.affected_heat_ids):
                workflow.advance(WorkflowStage.COMPLETED)
                self._attach_metrics(llm_result, scenario)
                return llm_result, llm_result
            llm_result.success = False
            llm_result.path = ResponsePath.LLM_REACT_FAILURE
            llm_result.reason = "LLM 合并结果修改了影响范围外炉次"
            llm_result.failure_reasons = ["unaffected_assignment_changed"]
            workflow.failure_reasons.append("unaffected_assignment_changed")

        workflow.failure_reasons.extend(llm_result.failure_reasons or [llm_result.reason])
        workflow.advance(WorkflowStage.DEGRADED)
        frozen = self._frozen_result(
            scenario.baseline_assignments,
            scenario.affected_heat_ids,
        )
        frozen.reason = "LLM Workflow 失败，Frozen + 告警等人工"
        frozen.remaining_budget_seconds = llm_result.remaining_budget_seconds
        frozen.failure_reasons = ["llm_workflow_failed", llm_result.reason]
        frozen.workflow = workflow
        self._attach_metrics(frozen, scenario)
        return frozen, llm_result

    def run_three_way(
        self,
        scenario: DisturbedScenario,
        scenario_id: str = "1",
        force_llm_on_success: bool = False,
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
        available_ladles = self._available_ladles(scenario)
        if remaining_heats:
            dt_result = self._run_decision_tree(
                remaining_heats,
                available_ladles,
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
        budget = scenario.remaining_budget_seconds
        if budget is not None:
            budget = max(0.0, budget - dt_result.elapsed_seconds)
        if self._llm is not None and remaining_heats and not scenario.is_emergency and (budget is None or budget > 0.0) and (not dt_result.success or force_llm_on_success):
            llm_result = self._run_llm_react(
                remaining_heats,
                available_ladles,
                scenario.remaining_cranes,
                budget if budget is not None else float("inf"),
                {**self._failure_context(scenario, dt_result, budget), "experimental_forced": force_llm_on_success and dt_result.success},
            )
            llm_merged = _merge_assignments(
                scenario.frozen_assignments,
                {str(a["heat_id"]): a for a in llm_result.assignments},
                list(scenario.baseline_assignments[0].keys()) if scenario.baseline_assignments else [],
            )
            llm_result.assignments = llm_merged
            if not _preserves_unaffected(llm_merged, scenario.baseline_assignments, scenario.affected_heat_ids):
                llm_result.success = False
                llm_result.path = ResponsePath.LLM_REACT_FAILURE
                llm_result.reason = "LLM 合并结果修改了影响范围外炉次"
                llm_result.failure_reasons = ["unaffected_assignment_changed"]
            llm = llm_result

        for result in (frozen, dt_result, llm):
            if result is not None:
                result.extra.setdefault("event", scenario.audit.get("event", {}))
                self._attach_metrics(result, scenario)

        return ThreeWayComparison(
            scenario_id=scenario_id,
            disturbance_desc=scenario.spec.description,
            num_affected=scenario.num_affected,
            num_total=len(scenario.baseline_assignments),
            frozen=frozen,
            decision_tree=dt_result,
            llm_react=llm,
        )

    @staticmethod
    def _attach_metrics(result: ResponseResult, scenario: DisturbedScenario) -> None:
        result.metrics = evaluate_path(
            scenario.baseline_heats,
            scenario.baseline_assignments,
            result.assignments,
            scenario.affected_heat_ids,
            result.human_review_required,
            result.elapsed_seconds,
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
        # Preserve validated extension fields such as refining routes. The old
        # projection silently discarded decisions absent from the baseline.
        merged[hid] = dict(a)
    return list(merged.values())


def _preserves_unaffected(
    merged: list[dict[str, Any]],
    baseline: list[dict[str, Any]],
    affected_heat_ids: list[str],
) -> bool:
    """Check that local response merging did not alter frozen resources."""
    affected = set(affected_heat_ids)
    by_heat = {str(row.get("heat_id", "")): row for row in merged}
    protected_fields = ("ladle_id", "crane_id", "refining_route", "action")
    reserved_ladles: set[str] = set()
    for original in baseline:
        heat_id = str(original.get("heat_id", ""))
        if heat_id in affected:
            continue
        candidate = by_heat.get(heat_id)
        if candidate is None or any(candidate.get(field) != original.get(field) for field in protected_fields):
            return False
        ladle_id = str(candidate.get("ladle_id") or "")
        if candidate.get("action") == "assign" and ladle_id:
            reserved_ladles.add(ladle_id)
    for heat_id, candidate in by_heat.items():
        if heat_id not in affected:
            continue
        ladle_id = str(candidate.get("ladle_id") or "")
        if candidate.get("action") != "assign" or not ladle_id:
            continue
        if ladle_id in reserved_ladles:
            return False
    return True
