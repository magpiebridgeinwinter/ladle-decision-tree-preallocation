"""Run an auditable decision-tree failure and Codex fallback demonstration.

The Codex proposal in this file was authored in the interactive Codex session
that requested this demo. It is injected through the production controller's
LLM callable boundary; no external model API or credential is used.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ladle_preallocation.decision_tree import validate_output
from ladle_preallocation.disturbance import DisturbanceSpec, inject_disturbance
from ladle_preallocation.response import TieredResponseController


HEATS = [
    {
        "heat_id": "H-FLEX",
        "required_grade": "4",
        "target_age_seconds": 0.0,
        "window_start": 0.0,
        "window_end": 1000.0,
        "pour_at": 600.0,
        "priority": 2,
    },
    {
        "heat_id": "H-TIGHT",
        "required_grade": "5",
        "enforce_grade": True,
        "window_start": 0.0,
        "window_end": 10.0,
        "pour_at": 600.0,
        "priority": 1,
    },
]

LADLES = [
    {
        "ladle_id": "L-NEAR",
        "grade": "5",
        "state": "available",
        "position_m": 0.0,
        "weight_tonnes": 80.0,
        "empty_ladle_weight_tonnes": 140.0,
        "age_seconds": 1000.0,
        "max_age_seconds": 1000.0,
    },
    {
        "ladle_id": "L-FAR",
        "grade": "4",
        "state": "available",
        "position_m": 100.0,
        "weight_tonnes": 80.0,
        "empty_ladle_weight_tonnes": 140.0,
        "age_seconds": 0.0,
        "max_age_seconds": 1000.0,
    },
]

CRANES = [
    {
        "crane_id": "C0",
        "position_m": 50.0,
        "current_load_tonnes": 0.0,
        "max_load_tonnes": 300.0,
        "speed_mps": 1.0,
        "safe_distance_m": 0.0,
        "limit_0_m": 0.0,
        "limit_1_m": 150.0,
    },
    {
        "crane_id": "C1",
        "position_m": 0.0,
        "current_load_tonnes": 0.0,
        "max_load_tonnes": 300.0,
        "speed_mps": 1.0,
        "safe_distance_m": 0.0,
        "limit_0_m": 0.0,
        "limit_1_m": 100.0,
    },
    {
        "crane_id": "C2",
        "position_m": 100.0,
        "current_load_tonnes": 150.0,
        "max_load_tonnes": 300.0,
        "speed_mps": 1.0,
        "safe_distance_m": 0.0,
        "limit_0_m": 50.0,
        "limit_1_m": 150.0,
    },
]

BASELINE_ASSIGNMENTS = [
    {
        "heat_id": "H-FLEX",
        "ladle_id": "L-FAR",
        "crane_id": "C0",
        "action": "assign",
        "algorithm": "baseline",
        "grade_match": True,
        "expected_arrival_seconds": 50.0,
        "reason": "扰动前基线分配",
        "violations": (),
    },
    {
        "heat_id": "H-TIGHT",
        "ladle_id": "L-NEAR",
        "crane_id": "C0",
        "action": "assign",
        "algorithm": "baseline",
        "grade_match": True,
        "expected_arrival_seconds": 50.0,
        "reason": "扰动前基线分配",
        "violations": (),
    },
]

# Authored by Codex after considering both heats as one global assignment.
CODEX_PROPOSAL = [
    {
        "heat_id": "H-FLEX",
        "ladle_id": "L-FAR",
        "crane_id": "C2",
        "expected_arrival_seconds": 0.0,
        "reason": "Codex 全局分配：将 C1 保留给紧窗口炉次",
    },
    {
        "heat_id": "H-TIGHT",
        "ladle_id": "L-NEAR",
        "crane_id": "C1",
        "expected_arrival_seconds": 0.0,
        "reason": "Codex 全局分配：使用近端行车满足 10 秒窗口",
    },
]


class CodexProposalAdapter:
    """Expose this session's Codex proposal through the LLM callable contract."""

    def __init__(self) -> None:
        self.called = False
        self.remaining_budget_seconds: float | None = None
        self.failure_context: dict[str, Any] = {}

    def __call__(
        self,
        _heats: list[dict[str, Any]],
        _ladles: list[dict[str, Any]],
        _cranes: list[dict[str, Any]],
        *,
        remaining_budget_seconds: float | None = None,
        failure_context: dict[str, Any] | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        self.called = True
        self.remaining_budget_seconds = remaining_budget_seconds
        self.failure_context = deepcopy(failure_context or {})
        return True, deepcopy(CODEX_PROPOSAL)


def _result_payload(result: Any) -> dict[str, Any]:
    return {
        "path": result.path.value,
        "success": result.success,
        "num_assigned": result.num_assigned,
        "elapsed_seconds": result.elapsed_seconds,
        "reason": result.reason,
        "assignments": result.assignments,
        "remaining_budget_seconds": result.remaining_budget_seconds,
        "validation_feedback": result.validation_feedback,
    }


def run_demo() -> dict[str, Any]:
    spec = DisturbanceSpec(
        kind="crane_offline",
        resource_id="C0",
        description="基线行车 C0 突发离线",
        occurred_at=100.0,
    )
    scenario = inject_disturbance(
        spec,
        deepcopy(HEATS),
        deepcopy(LADLES),
        deepcopy(CRANES),
        deepcopy(BASELINE_ASSIGNMENTS),
    )
    adapter = CodexProposalAdapter()
    comparison = TieredResponseController(adapter).run_three_way(
        scenario,
        scenario_id="codex_llm_fallback_001",
    )
    proposal_validation = validate_output(
        scenario.heats_needing_reallocation,
        scenario.remaining_ladles,
        scenario.remaining_cranes,
        CODEX_PROPOSAL,
    )
    for row in proposal_validation:
        row["algorithm"] = "llm_react"

    assert scenario.remaining_budget_seconds == 410.0
    assert not comparison.decision_tree.success
    assert comparison.decision_tree.num_assigned == 1
    assert adapter.called
    assert comparison.llm_react is not None and comparison.llm_react.success
    assert comparison.llm_react.num_assigned == 2
    assert all(row["action"] == "assign" for row in proposal_validation)

    return {
        "schema_version": 1,
        "scenario_id": comparison.scenario_id,
        "scenario": {
            "event": scenario.audit["event"],
            "affected_heat_ids": scenario.affected_heat_ids,
            "earliest_pour_at": scenario.earliest_pour_at,
            "safety_buffer_seconds": 90.0,
            "remaining_budget_seconds": scenario.remaining_budget_seconds,
            "heats": scenario.heats_needing_reallocation,
            "remaining_ladles": scenario.remaining_ladles,
            "remaining_cranes": scenario.remaining_cranes,
        },
        "llm_invocation": {
            "provider": "Codex current interactive session",
            "transport": "Codex-authored proposal injected through TieredResponseController callable",
            "external_api_called": False,
            "controller_called_adapter": adapter.called,
            "budget_received_seconds": adapter.remaining_budget_seconds,
            "failure_context_received": adapter.failure_context,
            "proposal": CODEX_PROPOSAL,
        },
        "decision_tree": _result_payload(comparison.decision_tree),
        "codex_llm": _result_payload(comparison.llm_react),
        "proposal_validation": proposal_validation,
        "comparison": comparison.summary(),
        "conclusion": "决策树仅分配 1/2；Codex 全局方案分配 2/2，并通过相同硬约束终检。",
    }


def _markdown(report: dict[str, Any]) -> str:
    dt = report["decision_tree"]
    llm = report["codex_llm"]
    proposal = report["llm_invocation"]["proposal"]
    lines = [
        "# Codex LLM 兜底演练报告",
        "",
        "> 本报告中的方案由当前 Codex 会话生成，并通过控制器的 LLM callable 边界注入。未调用外部模型 API。",
        "",
        "## 场景",
        "",
        "- 扰动：基线行车 `C0` 在 `t=100s` 离线。",
        "- 受影响炉次：`H-FLEX`、`H-TIGHT`。",
        "- 最早开浇：`t=600s`；扣除 90 秒安全缓冲后，LLM 预算为 `410s`。",
        "- `H-TIGHT` 只有 10 秒运输窗口，必须使用近端 `L-NEAR/C1`。",
        "",
        "## 决策树失败",
        "",
        f"决策树结果为 `{dt['path']}`，只完成 `{dt['num_assigned']}/2` 个炉次。它先把 `L-FAR` 分给 `C1`，之后 `H-TIGHT` 因 `grade,time_window,x_limit` 无候选。",
        "",
        "## Codex 方案",
        "",
        "| 炉次 | 钢包 | 行车 | 选择原因 |",
        "| --- | --- | --- | --- |",
    ]
    for row in proposal:
        lines.append(f"| {row['heat_id']} | {row['ladle_id']} | {row['crane_id']} | {row['reason']} |")
    lines.extend([
        "",
        f"控制器实际进入 `{llm['path']}`，完成 `{llm['num_assigned']}/2`；完整性检查和共享 `validate_output` 硬约束终检均通过。",
        "",
        "## 结论",
        "",
        "这次演练证明了当前控制器能在决策树失败且预算充足时接收 Codex 方案，并由统一校验器决定是否采用。它验证的是接口与约束闭环，不等同于已接通生产环境中的 Codex API。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="outputs/codex_llm_fallback_demo",
        help="Directory for JSON and Markdown audit outputs",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = run_demo()
    (output_dir / "audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    print(json.dumps(report["comparison"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
