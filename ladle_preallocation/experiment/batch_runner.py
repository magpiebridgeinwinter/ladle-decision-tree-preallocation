"""Batch experiment framework for three-way comparison.

Runs multiple disturbance scenarios and compares:
1. Frozen (no reallocation)
2. Decision Tree rerank
3. LLM ReAct rescheduling

Quantifies how many heats LLM can save over decision tree.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ladle_preallocation.decision_tree.allocator import allocate as dt_allocate
from ladle_preallocation.decision_tree.validation import validate_output
from ladle_preallocation.disturbance.injector import (
    DisturbanceSpec,
    inject_disturbance,
)
from ladle_preallocation.response.controller import (
    ThreeWayComparison,
    TieredResponseController,
)


@dataclass
class BatchConfig:
    """Configuration for a batch experiment run."""

    num_scenarios: int = 20
    disturbance_probability: float = 0.3
    seed: int | None = 42
    output_dir: str = "outputs"
    scenario_prefix: str = "scenario"

    # If True, run all scenarios even if DT already succeeded
    force_llm_on_success: bool = False

    # If True, include detailed scenario JSON in output
    verbose: bool = False


@dataclass
class BatchResult:
    """Aggregate results from a batch experiment."""

    config: BatchConfig
    comparisons: list[ThreeWayComparison]
    summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self._compute_summary()

    def _compute_summary(self) -> None:
        n = len(self.comparisons)
        if n == 0:
            self.summary = {"error": "no scenarios generated"}
            return

        dt_success = sum(1 for c in self.comparisons if c.decision_tree.success)
        dt_total_saved = sum(c.dt_saved for c in self.comparisons)

        llm_results = [c for c in self.comparisons if c.llm_react is not None]
        llm_success = sum(1 for c in llm_results if c.llm_react.success) if llm_results else 0
        llm_total_saved = sum(c.llm_saved for c in llm_results if c.llm_saved is not None) if llm_results else 0
        llm_total_saved_from_frozen = sum(c.llm_delta_from_frozen for c in llm_results if c.llm_delta_from_frozen is not None) if llm_results else 0

        self.summary = {
            "total_scenarios": n,
            "total_affected_heats": sum(c.num_affected for c in self.comparisons),
            "dt_success_rate": dt_success / n if n else 0,
            "dt_total_saved_over_frozen": dt_total_saved,
            "llm_attempted": len(llm_results),
            "llm_success_rate": llm_success / len(llm_results) if llm_results else 0,
            "llm_total_saved_over_dt": llm_total_saved,
            "llm_total_saved_over_frozen": llm_total_saved_from_frozen,
            "dt_avg_elapsed_ms": _safe_mean([c.decision_tree.elapsed_seconds * 1000 for c in self.comparisons]),
            "llm_avg_elapsed_s": _safe_mean([c.llm_react.elapsed_seconds for c in llm_results]) if llm_results else None,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "num_scenarios": self.config.num_scenarios,
                "seed": self.config.seed,
            },
            "summary": self.summary,
            "scenarios": [c.summary() for c in self.comparisons],
        }

    def markdown_report(self) -> str:
        s = self.summary
        lines = [
            "# 三路对比实验结果",
            "",
            f"- 场景总数：{s['total_scenarios']}",
            f"- 涉及受影响炉次：{s['total_affected_heats']}",
            "",
            "## 决策树重排",
            f"- 成功率：{s['dt_success_rate']:.1%}",
            f"- Fronzen 之上救回炉次：{s['dt_total_saved_over_frozen']}",
            f"- 平均耗时：{s['dt_avg_elapsed_ms']:.1f} ms",
        ]
        if s["llm_attempted"] > 0:
            lines.extend([
                "",
                "## LLM ReAct 重调度",
                f"- 尝试次数：{s['llm_attempted']}（决策树失败后启动）",
                f"- 成功率：{s['llm_success_rate']:.1%}",
                f"- 决策树之上救回炉次：{s['llm_total_saved_over_dt']}",
                f"- Froze以上救回炉次：{s['llm_total_saved_over_frozen']}",
                f"- 平均耗时：{s['llm_avg_elapsed_s']:.1f} s" if s["llm_avg_elapsed_s"] is not None else "- 平均耗时：N/A",
                "",
                "## 量化结论",
                f"LLM 在决策树失败的场景中，额外救回率：{s['llm_success_rate']:.1%}，"
                f"共额外救回 {s['llm_total_saved_over_dt']} 炉次。",
            ])
        else:
            lines.extend([
                "",
                "## LLM ReAct 重调度",
                "- 未触发（所有场景决策树均成功或 LLM 未配置）",
            ])
        return "\n".join(lines)


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class BatchRunner:
    """Run batch experiments for three-way comparison."""

    def __init__(
        self,
        config: BatchConfig | None = None,
        llm_rescheduler: Any = None,
    ):
        self.config = config or BatchConfig()
        self.controller = TieredResponseController(llm_rescheduler)

    def run(
        self,
        heats: list[dict[str, Any]],
        ladles: list[dict[str, Any]],
        cranes: list[dict[str, Any]],
        allocations: list[dict[str, Any]],
    ) -> BatchResult:
        """Run batch experiment on a baseline scenario.

        Args:
            heats: All heats in the scenario.
            ladles: All available ladles.
            cranes: All available cranes.
            allocations: Baseline decision tree assignments (100% success).

        Returns:
            BatchResult with all comparisons and aggregate summary.
        """
        rng = random.Random(self.config.seed)
        comparisons: list[ThreeWayComparison] = []

        for i in range(self.config.num_scenarios):
            scenario_seed = rng.randint(0, 2**31 - 1)

            # Generate disturbance: pick a random assigned crane
            assigned_cranes = list({
                str(a.get("crane_id", ""))
                for a in allocations
                if a.get("crane_id")
            })
            if not assigned_cranes:
                continue

            offline_crane = rng.choice(assigned_cranes)
            spec = DisturbanceSpec(
                kind="crane_offline",
                resource_id=offline_crane,
                description=f"行车 {offline_crane} 离线故障",
            )

            scenario = inject_disturbance(spec, heats, ladles, cranes, allocations)

            if not scenario.heats_needing_reallocation:
                continue

            comparison = self.controller.run_three_way(
                scenario,
                scenario_id=f"{self.config.scenario_prefix}_{i+1:03d}",
            )
            comparisons.append(comparison)

        result = BatchResult(config=self.config, comparisons=comparisons)

        # Save output
        out_dir = Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / "three_way_comparison.md"
        report_path.write_text(result.markdown_report(), encoding="utf-8")

        data_path = out_dir / "three_way_comparison.json"
        data_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return result
