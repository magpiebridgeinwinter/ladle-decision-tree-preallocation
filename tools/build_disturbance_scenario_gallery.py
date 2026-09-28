#!/usr/bin/env python3
"""Build a visual gallery for all audited disturbance scenarios."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "outputs/disturbance_solution_benchmark/benchmark.json"
DEFAULT_OUTPUT = ROOT / "outputs/disturbance_solution_benchmark/disturbance_scenario_gallery.html"
DEFAULT_PLAN_AUDIT = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"

GREEN, GREEN_TINT = "#3c7a57", "#eaf5ee"
YELLOW, YELLOW_TINT = "#c99700", "#fff8d8"
RED, RED_TINT = "#b94747", "#fff0f0"
ORANGE, ORANGE_TINT = "#eb6c36", "#fff0e8"
BLUE, BLUE_TINT = "#2e5aa8", "#eaf1ff"


def esc(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "-"), quote=True)


def assignment(row: dict[str, Any] | None) -> str:
    if not row or row.get("action") != "assign":
        return "未分配"
    return f"{row.get('ladle_id') or '-'} / {row.get('crane_id') or '-'} / 路线 {row.get('refining_route') or '-'}"


def metric_value(key: str, value: Any) -> str:
    if value is None:
        return "N/A"
    if key in {"completion_rate", "on_time_rate", "human_review_rate", "factory_ladle_agreement_rate"}:
        return f"{float(value) * 100:.1f}%"
    if key in {"average_delay_seconds", "max_delay_seconds", "decision_seconds"}:
        return f"{float(value):.1f}s"
    if key == "crane_load_dispersion":
        return f"{float(value):.2f}"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


METRIC_DEFINITIONS = (
    ("completion_rate", "完成率", "max"),
    ("on_time_rate", "准时率", "max"),
    ("average_delay_seconds", "平均延误", "min"),
    ("max_delay_seconds", "最大延误", "min"),
    ("changed_heat_count", "改动炉次", "min"),
    ("resource_change_count", "资源变更", "min"),
    ("route_change_count", "路线变更", "min"),
    ("hard_constraint_violation_count", "硬约束违规", "min"),
    ("crane_load_dispersion", "天车负载离散度", "min"),
    ("factory_ladle_agreement_rate", "工厂钢包匹配率", "max"),
)


def metric_winner(left: Any, right: Any, direction: str) -> str:
    if left is None or right is None:
        return "不可比"
    left, right = float(left), float(right)
    if abs(left - right) <= 1e-9:
        return "持平"
    if direction == "max":
        return "AQ" if left > right else "AR"
    return "AQ" if left < right else "AR"


def metric_table(aq: dict[str, Any], ar: dict[str, Any]) -> str:
    aq_metrics, ar_metrics = aq.get("metrics") or {}, ar.get("metrics") or {}
    rows = []
    for key, label, direction in METRIC_DEFINITIONS:
        left, right = aq_metrics.get(key), ar_metrics.get(key)
        winner = metric_winner(left, right, direction)
        winner_class = {"AQ": "aq-win", "AR": "ar-win", "持平": "tie", "不可比": "na"}[winner]
        rows.append(
            f'<tr><th>{label}</th><td class="{winner_class}">{esc(metric_value(key, left))}</td>'
            f'<td class="{winner_class}">{esc(metric_value(key, right))}</td>'
            f'<td class="winner {winner_class}">{winner}</td></tr>'
        )
    return (
        '<div class="metric-panel"><div class="metric-heading"><b>评价指标</b>'
        '<span>高亮表示该项更优；综合推荐先看硬约束和完整性，再按指标顺序比较</span></div>'
        '<table class="metrics"><thead><tr><th>指标</th><th>AQ 决策树</th><th>AR Codex</th><th>更优</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )


def scenario_svg(index: int, scenario: dict[str, Any], context_rows: list[dict[str, Any]] | None = None) -> str:
    heats = scenario.get("heat_results") or []
    branches = scenario.get("branches") or {}
    aq_branch = branches.get("decision_tree") or {}
    ar_branch = branches.get("codex") or {}
    aq_rows = aq_branch.get("assignments") or {}
    ar_rows = ar_branch.get("assignments") or {}
    affected_by_id = {str(row.get("heat_id")): row for row in heats}
    rows = context_rows or [{"heat_id": row.get("heat_id"), "affected": True} for row in heats]
    height = 90 + max(1, len(rows)) * 31
    out = [
        f'<svg class="scenario-svg" viewBox="0 0 1160 {height}" role="img" aria-label="扰动方案对比图">',
        '<rect width="1160" height="100%" fill="#fff"/>',
        '<rect x="28" y="20" width="270" height="30" rx="4" fill="#f7f9fc" stroke="#d9dce3"/>',
        f'<rect x="330" y="20" width="390" height="30" rx="4" fill="{RED_TINT}" stroke="{RED}"/>',
        f'<rect x="758" y="20" width="374" height="30" rx="4" fill="{ORANGE_TINT}" stroke="{ORANGE}"/>',
        '<text x="40" y="40" class="header">受影响炉次</text>',
        f'<text x="342" y="40" class="header">AQ 决策树 · {"通过" if aq_branch.get("executable") else "未通过"}</text>',
        f'<text x="770" y="40" class="header">AR Codex · {"通过" if ar_branch.get("executable") else "未通过"}</text>',
    ]
    for row_index, heat in enumerate(rows):
        y = 60 + row_index * 31
        heat_id = str(heat.get("heat_id") or "-")
        affected = bool(heat.get("affected"))
        source = affected_by_id.get(heat_id)
        aq, ar = aq_rows.get(heat_id), ar_rows.get(heat_id)
        if not affected:
            ap = heat.get("assignment") or {}
            aq = ar = ap
        equal = assignment(aq) == assignment(ar)
        base_color, base_tint = (GREEN, GREEN_TINT) if equal else (YELLOW, YELLOW_TINT)
        if not affected:
            base_color, base_tint = BLUE, BLUE_TINT
        aq_color, aq_tint = (RED, RED_TINT) if aq and aq.get("action") != "assign" else (base_color, base_tint)
        ar_color, ar_tint = (ORANGE, ORANGE_TINT) if aq and aq.get("action") != "assign" and ar and ar.get("action") == "assign" else (base_color, base_tint)
        out.extend([
            f'<rect x="28" y="{y}" width="270" height="24" rx="3" fill="#fff" stroke="#d9dce3"/>',
            f'<text x="38" y="{y + 16}" class="heat">{esc(heat_id)}</text>',
            f'<rect x="330" y="{y}" width="390" height="24" rx="3" fill="{aq_tint}" stroke="{aq_color}"/>',
            f'<text x="340" y="{y + 16}" class="value">{esc(assignment(aq))}</text>',
            f'<rect x="758" y="{y}" width="374" height="24" rx="3" fill="{ar_tint}" stroke="{ar_color}"/>',
            f'<text x="768" y="{y + 16}" class="value">{esc(assignment(ar))}</text>',
        ])
    out.append('</svg>')
    return ''.join(out)


def build_html(data: dict[str, Any], context_windows: dict[str, list[dict[str, Any]]] | None = None) -> str:
    scenarios = data.get("scenarios") or []
    summary = data.get("summary") or {}
    cards: list[str] = []
    for index, scenario in enumerate(scenarios, 1):
        branches = scenario.get("branches") or {}
        aq, ar = branches.get("decision_tree") or {}, branches.get("codex") or {}
        recommendation = scenario.get("recommendation_label") or "未决"
        cards.append(
            f'<article class="scenario" id="scenario-{index}">'
            f'<div class="scenario-meta"><span class="number">{index:02d}</span><div><h2>{esc(scenario.get("title"))}</h2><p>{esc(scenario.get("disturbance_kind"))} · {scenario.get("affected_heat_count", 0)} 炉 · {esc(scenario.get("disturbance_group"))}</p></div>'
            f'<span class="recommendation">综合推荐：{esc(recommendation)}</span><span class="result aq">AQ {"通过" if aq.get("executable") else "未通过"}</span><span class="result ar">AR {"通过" if ar.get("executable") else "未通过"}</span></div>'
            f'{scenario_svg(index, scenario, (context_windows or {}).get(str(scenario.get("scenario_id"))))}'
        f'{metric_table(aq, ar)}</article>'
        )
    css = """
* { box-sizing: border-box; }
body { margin: 0; background: #eef1f5; color: #2d3142; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }
main { max-width: 1220px; margin: 0 auto; padding: 28px; }
.hero, .scenario { background: #fff; border: 1px solid #d9dce3; border-radius: 8px; margin-bottom: 22px; }
.hero { padding: 26px 30px; } h1 { margin: 0 0 12px; font-size: 28px; }
.hero p { margin: 8px 0; color: #4f5d75; line-height: 1.65; }
.stats { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }
.stat { padding: 12px 18px; border-radius: 6px; background: #f7f9fc; border-left: 4px solid #4f5d75; }
.stat b { display: block; font-size: 20px; } .legend { display: flex; gap: 18px; flex-wrap: wrap; margin-top: 16px; color: #4f5d75; }
.legend span:before { content: ""; display: inline-block; width: 13px; height: 13px; margin-right: 5px; vertical-align: -2px; border: 1px solid currentColor; background: currentColor; }
.same { color: #3c7a57; } .diff { color: #c99700; } .context { color: #2e5aa8; } .fail { color: #b94747; } .codex { color: #eb6c36; }
.scenario { overflow: hidden; } .scenario-meta { display: flex; align-items: center; gap: 14px; padding: 18px 22px; border-bottom: 1px solid #d9dce3; }
.number { font-size: 22px; font-weight: 700; color: #4f5d75; } .scenario-meta h2 { margin: 0; font-size: 19px; }
.scenario-meta p { margin: 5px 0 0; color: #4f5d75; } .result { margin-left: 0; padding: 7px 11px; border-radius: 4px; font-weight: 700; font-size: 12px; }
.result + .result { margin-left: 0; } .result.aq { color: #b94747; background: #fff0f0; } .result.ar { color: #eb6c36; background: #fff0e8; }
.recommendation { margin-left: auto; padding: 7px 11px; border-radius: 4px; color: #2e7d5b; background: #eaf5ee; font-weight: 700; font-size: 12px; }
.scenario-svg { display: block; width: 100%; height: auto; } .header { font-size: 12px; font-weight: 700; fill: #2d3142; }
.heat, .value { font-size: 11px; fill: #2d3142; } .value { font-weight: 600; }
.metric-panel { padding: 14px 22px 18px; border-top: 1px solid #d9dce3; } .metric-heading { display: flex; align-items: baseline; gap: 12px; margin-bottom: 8px; }
.metric-heading b { font-size: 14px; } .metric-heading span { color: #6b7280; font-size: 11px; }
.metrics { width: 100%; border-collapse: collapse; font-size: 12px; } .metrics th, .metrics td { padding: 7px 10px; border-bottom: 1px solid #edf0f4; text-align: right; }
.metrics th:first-child, .metrics td:first-child { text-align: left; } .metrics thead th { color: #4f5d75; font-weight: 700; background: #f7f9fc; }
.metrics .winner { font-weight: 700; } .metrics .aq-win { color: #b94747; background: #fff6f5; } .metrics .ar-win { color: #eb6c36; background: #fff7f1; }
.metrics .winner.aq-win { color: #b94747; } .metrics .winner.ar-win { color: #eb6c36; } .metrics .tie, .metrics .na { color: #6b7280; }
@media print { body { background: #fff; } main { padding: 0; } .hero, .scenario { break-inside: avoid; } }
"""
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>20 类钢包扰动双线路场景图集</title><style>{css}</style></head><body><main><section class="hero"><h1>批量扰动双线路实验：20 类场景</h1><p>每张图代表一个独立扰动场景。场景从同一份扰动前预配结果出发，左侧是 AQ 决策树，右侧是 AR Codex；两条线路对同一动态影响窗口独立求解。</p><div class="stats"><div class="stat"><b>{len(scenarios)}</b>类场景</div><div class="stat"><b>{summary.get("decision_tree_executable_count", 0)}/{len(scenarios)}</b>AQ 完整通过</div><div class="stat"><b>{summary.get("codex_executable_count", 0)}/{len(scenarios)}</b>AR 完整通过</div><div class="stat"><b>{summary.get("primary_31_heat_scenario_count", 0)}</b>个 31 炉主场景</div><div class="stat"><b>{summary.get("dynamic_local_window_scenario_count", 0)}</b>个动态局部窗口</div></div><div class="legend"><span class="context">蓝色：窗口外上下文炉次</span><span class="same">绿色：受扰动炉次且 AQ 与 AR 相同</span><span class="diff">黄色：受扰动炉次且 AQ 与 AR 不同</span><span class="fail">红色：AQ 未分配/未通过</span><span class="codex">橙色：AR 对 AQ 缺口完成补全</span></div><p>注意：这 20 类是基于真实 PLAN(1)、CRANE 和位置数据构造的可复现压力场景，不等于工厂历史事故统计。</p></section>{"".join(cards)}</main></body></html>'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") or []
    if len(scenarios) != 20:
        raise SystemExit(f"expected 20 scenarios, got {len(scenarios)}")
    audit = json.loads(DEFAULT_PLAN_AUDIT.read_text(encoding="utf-8"))
    baseline_rows = audit.get("assignments") or []
    heat_routes = {
        str(row.get("heat_id")): row.get("refining_route")
        for row in (audit.get("scheduling_inputs", {}).get("heats") or [])
        if row.get("heat_id")
    }
    baseline_by_id = {
        str(row.get("heat_id")): {
            **row,
            "refining_route": row.get("refining_route") or heat_routes.get(str(row.get("heat_id")), ""),
        }
        for row in baseline_rows
    }
    ordered_ids = [str(row.get("heat_id")) for row in baseline_rows if row.get("heat_id")]
    context_windows: dict[str, list[dict[str, Any]]] = {}
    for scenario in scenarios:
        affected_ids = [str(row.get("heat_id")) for row in scenario.get("heat_results") or []]
        positions = [ordered_ids.index(item) for item in affected_ids if item in ordered_ids]
        if not positions:
            context_windows[str(scenario.get("scenario_id"))] = [{"heat_id": item, "affected": True} for item in affected_ids]
            continue
        if len(affected_ids) >= 20:
            selected = affected_ids
        else:
            center = (min(positions) + max(positions)) // 2
            start = max(0, min(center - 9, len(ordered_ids) - 20))
            selected = ordered_ids[start:start + min(20, len(ordered_ids))]
        context_windows[str(scenario.get("scenario_id"))] = [
            {"heat_id": heat_id, "affected": heat_id in affected_ids, "assignment": baseline_by_id.get(heat_id)}
            for heat_id in selected
        ]
    figure_dir = args.output.parent / "scenario_figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    for index, scenario in enumerate(scenarios, 1):
        (figure_dir / f"scenario_{index:02d}.svg").write_text(scenario_svg(index, scenario, context_windows.get(str(scenario.get("scenario_id")))), encoding="utf-8")
    args.output.write_text(build_html(data, context_windows), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "figure_dir": str(figure_dir), "scenarios": 20}, ensure_ascii=False))


if __name__ == "__main__":
    main()
