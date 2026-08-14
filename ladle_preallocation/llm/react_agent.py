"""LLM ReAct rescheduling engine.

Not for: replacing the decision tree.
Role: backup when the decision tree cannot handle a disturbance.

Architecture:
- ReAct loop: LLM proposes → Validator checks → Feedback → Revise
- Max rounds: configurable (default 5)
- Safety: always validates against hard constraints before accepting
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ladle_preallocation.decision_tree.constraints import validate_assignment
from ladle_preallocation.rules import evaluate_ladle_rules

from ladle_preallocation.llm.prompts import (
    RESCHEDULING_SYSTEM_PROMPT,
    build_problem_description,
    build_feedback_prompt,
    build_final_format_prompt,
)


_MAX_JSON_ATTEMPTS = 3


@dataclass
class ReActTrace:
    """Audit trail for each ReAct round."""

    round: int
    proposal_raw: str
    parsed_assignments: list[dict[str, Any]]
    violations: dict[str, list[str]]  # heat_id → violation list
    success: bool
    elapsed_seconds: float


@dataclass
class ReActResult:
    """Complete ReAct execution result."""

    success: bool
    assignments: list[dict[str, Any]]
    traces: list[ReActTrace] = field(default_factory=list)
    total_elapsed: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_rounds": len(self.traces),
            "elapsed_seconds": round(self.total_elapsed, 3),
            "reason": self.reason,
            "traces": [
                {
                    "round": t.round,
                    "success": t.success,
                    "elapsed_s": round(t.elapsed_seconds, 3),
                    "num_violations": sum(len(v) for v in t.violations.values()),
                }
                for t in self.traces
            ],
        }


def _call_llm(
    messages: list[dict[str, str]],
    api_base: str,
    api_key: str,
    model: str,
    timeout_seconds: float = 120.0,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Call the LLM API using the OpenAI-compatible interface."""
    import urllib.request
    import urllib.error

    url = f"{api_base.rstrip('/')}/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=max(0.001, timeout_seconds)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM API error {e.code}: {e.read().decode()}")
    except Exception as e:
        raise RuntimeError(f"LLM API call failed: {e}")


def _parse_json_from_response(response: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, trying multiple strategies."""
    # Strategy 1: match ```json ... ``` blocks
    match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 2: match {...} blocks with assignments key
    match = re.search(r'\{[^{}]*"assignments"\s*:\s*\[.*?\][^{}]*\}', response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 3: try parsing the entire response as JSON
    try:
        return json.loads(response.strip())
    except json.JSONDecodeError:
        pass

    return None


def _validate_proposal(
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Validate all proposed assignments against hard constraints."""
    violations: dict[str, list[str]] = {}
    heat_map = {str(h["heat_id"]): h for h in heats}
    ladle_map = {str(l["ladle_id"]): l for l in ladles}
    crane_map = {str(c["crane_id"]): c for c in cranes}
    crane_loads: dict[str, float] = {str(c["crane_id"]): float(c.get("current_load_tonnes", 0) or 0) for c in cranes}
    used_ladles: set[str] = set()

    returned_heat_ids = [str(p.get("heat_id", "")) for p in proposals]
    expected_heat_ids = set(heat_map)
    if len(returned_heat_ids) != len(set(returned_heat_ids)):
        violations["_proposal"] = ["duplicate_heat"]
    missing = expected_heat_ids - set(returned_heat_ids)
    if missing:
        violations["_proposal"] = violations.get("_proposal", []) + ["missing_heat"]
    for p in proposals:
        heat_id = str(p.get("heat_id", "unknown"))
        ladle_id = str(p.get("ladle_id", ""))
        crane_id = str(p.get("crane_id", ""))

        heat_issues: list[str] = []

        # Check heat exists
        if heat_id not in heat_map:
            heat_issues.append("unknown_heat")
            violations[heat_id] = heat_issues
            continue

        heat = heat_map[heat_id]

        # Check ladle exists
        if ladle_id not in ladle_map:
            heat_issues.append("unknown_ladle")
        else:
            ladle = ladle_map[ladle_id]
            # Check ladle already used
            if ladle_id in used_ladles:
                heat_issues.append("ladle_already_used")
            else:
                used_ladles.add(ladle_id)
                # Run rule evaluation
                rule = evaluate_ladle_rules(heat, ladle)
                heat_issues.extend(rule.violations)

        # Check crane exists and run constraints
        if crane_id in crane_map:
            if ladle_id in ladle_map and "ladle_already_used" not in heat_issues:
                ladle = ladle_map[ladle_id]
                constraint_errors = validate_assignment(heat, ladle, crane_map[crane_id], crane_loads)
                heat_issues.extend(constraint_errors)
                # Update crane load for subsequent validation
                crane_loads[crane_id] += float(ladle.get("weight_tonnes", 0) or 0)
        else:
            heat_issues.append("unknown_crane")

        if heat_issues:
            violations[heat_id] = heat_issues

    return violations


class ReActRescheduler:
    """LLM-based rescheduler using ReAct agent pattern.

    The agent iterates:
    1. Observes the disturbed state and available resources
    2. Proposes a reallocation
    3. Validator checks for hard-constraint violations
    4. If violations: feedback → agent revises
    5. If clean: accept and return
    """

    def __init__(
        self,
        api_base: str = "https://api.deepseek.com",
        api_key: str | None = None,
        model: str = "deepseek-v4-flash",
        max_rounds: int = 5,
        temperature: float = 0.3,
        verbose: bool = False,
        llm_call: Any = _call_llm,
        clock: Any = time.perf_counter,
    ):
        self.api_base = api_base
        self.api_key = api_key or ""
        self.model = model
        self.max_rounds = max_rounds
        self.temperature = temperature
        self.verbose = verbose
        self._llm_call = llm_call
        self._clock = clock

    def reschedule(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        remaining_budget_seconds: float | None = None,
        failure_context: dict[str, Any] | None = None,
        rag_context: str | None = None,
    ) -> ReActResult:
        """Execute ReAct loop to reschedule affected heats.

        Args:
            heats: Heats that need reallocation.
            ladles: Available ladles.
            cranes: Available cranes.

        Returns:
            ReActResult with final assignments and execution trace.
        """
        t_start = self._clock()
        traces: list[ReActTrace] = []

        # Check preconditions
        if not self.api_key:
            return ReActResult(
                success=False,
                assignments=[],
                reason="API key 未配置，无法调用 LLM",
            )

        if not heats:
            return ReActResult(
                success=True,
                assignments=[],
                reason="无需要重分配的炉次",
            )

        # Build base messages
        messages: list[dict[str, str]] = [
            {"role": "system", "content": RESCHEDULING_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_problem_description(heats, ladles, cranes, failure_context, rag_context),
            },
        ]

        for round_num in range(1, self.max_rounds + 1):
            elapsed_total = self._clock() - t_start
            budget_left = None if remaining_budget_seconds is None else remaining_budget_seconds - elapsed_total
            if budget_left is not None and budget_left <= 0:
                return ReActResult(False, [], traces, elapsed_total, "LLM 时间预算耗尽")
            t0 = self._clock()
            try:
                response = self._llm_call(
                    messages,
                    api_base=self.api_base,
                    api_key=self.api_key,
                    model=self.model,
                    temperature=self.temperature,
                    timeout_seconds=budget_left if budget_left is not None else 120.0,
                )
            except Exception as exc:
                return ReActResult(
                    success=False,
                    assignments=[],
                    traces=traces,
                    total_elapsed=self._clock() - t_start,
                    reason=f"LLM 调用失败 (round {round_num}): {exc}",
                )

            elapsed = self._clock() - t0
            if remaining_budget_seconds is not None and self._clock() - t_start > remaining_budget_seconds:
                return ReActResult(False, [], traces, self._clock() - t_start, "LLM 调用超出时间预算")

            # Parse proposal
            parsed = _parse_json_from_response(response)
            if parsed is None:
                # Try to extract JSON again with explicit instruction
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": build_final_format_prompt()})
                continue

            proposals = parsed.get("assignments", [])
            if not isinstance(proposals, list):
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "输出格式错误：缺少 assignments 数组。请严格按照 JSON 格式输出。"})
                continue

            # Validate
            violations = _validate_proposal(heats, ladles, cranes, proposals)
            success = not violations

            trace = ReActTrace(
                round=round_num,
                proposal_raw=response,
                parsed_assignments=proposals,
                violations=violations,
                success=success,
                elapsed_seconds=elapsed,
            )
            traces.append(trace)

            if success:
                return ReActResult(
                    success=True,
                    assignments=_build_final_assignments(heats, proposals),
                    traces=traces,
                    total_elapsed=self._clock() - t_start,
                    reason=f"ReAct 第 {round_num} 轮通过校验",
                )

            # Build feedback for next round
            feedback = build_feedback_prompt(violations, round_num, self.max_rounds)
            messages.append({"role": "assistant", "content": response})
            messages.append({"role": "user", "content": feedback})

        # Max rounds exceeded
        return ReActResult(
            success=False,
            assignments=_build_final_assignments(heats, []),
            traces=traces,
            total_elapsed=self._clock() - t_start,
            reason=f"ReAct 超过最大轮次 {self.max_rounds}，未通过校验",
        )


def _build_final_assignments(
    heats: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build final assignment records from proposals."""
    prop_map = {str(p["heat_id"]): p for p in proposals}
    result = []
    for heat in heats:
        hid = str(heat["heat_id"])
        if hid in prop_map:
            p = prop_map[hid]
            result.append({
                "algorithm": "llm_react",
                "heat_id": hid,
                "ladle_id": str(p.get("ladle_id", "")),
                "crane_id": str(p.get("crane_id", "")),
                "action": "assign",
                "reason": p.get("reason", "LLM ReAct 分配"),
                "violations": (),
                "grade_match": p.get("grade_match", True),
                "expected_arrival_seconds": p.get("expected_arrival_seconds"),
            })
        else:
            result.append({
                "algorithm": "llm_react",
                "heat_id": hid,
                "ladle_id": None,
                "crane_id": None,
                "action": "unassigned",
                "reason": "LLM 未返回该炉次方案",
                "violations": ("llm_missed",),
                "grade_match": False,
                "expected_arrival_seconds": None,
            })
    return result
