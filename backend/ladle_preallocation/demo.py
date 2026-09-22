"""Demo: Full disturbance → tiered response → three-way comparison pipeline.

Usage:
    python -m ladle_preallocation.demo
    python -m ladle_preallocation.demo --num-heats 20 --num-scenarios 10
    python -m ladle_preallocation.demo --llm-api-key sk-xxx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ladle_preallocation.decision_tree import allocate, validate_output
from ladle_preallocation.decision_tree.config import TREE_VERSION
from ladle_preallocation.disturbance import inject_disturbance, DisturbanceSpec
from ladle_preallocation.response import TieredResponseController, ResponsePath
from ladle_preallocation.llm import ReActRescheduler
from ladle_preallocation.experiment import BatchRunner, BatchConfig
from ladle_preallocation.rag import KnowledgeBase
from ladle_preallocation.real_data.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="LLM 局部重调度 Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic demo with mock LLM (no API key needed)
  python -m ladle_preallocation.demo

  # With DeepSeek API
  python -m ladle_preallocation.demo --llm-api-key sk-your-key

  # Override defaults
  python -m ladle_preallocation.demo --num-scenarios 20 --dt-heat-limit 30
""",
    )
    parser.add_argument("--plan-path", default="data/PLAN(1)_预配包输入.xlsx")
    parser.add_argument("--crane-path", default="data/CRANE.xlsx")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--dt-heat-limit", type=int, default=20)
    parser.add_argument("--num-scenarios", type=int, default=10)
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--llm-api-base", default="https://api.deepseek.com")
    parser.add_argument("--llm-model", default="deepseek-v4-flash")
    parser.add_argument("--llm-max-rounds", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("LLM 局部重调度方案 Demo")
    print("=" * 60)

    # Step 0: Initialize RAG knowledge base
    print("\n[0/6] 初始化 RAG 知识库...")
    kb = KnowledgeBase()
    kb.seed_default_rules()
    print(f"  知识库已加载 {kb.size} 条调度规范")

    # Step 1: Run baseline decision tree
    print("\n[1/6] 运行预配包决策树（基线）...")
    try:
        baseline = run_pipeline(
            Path(args.plan_path),
            Path(args.crane_path),
            Path(args.output_dir),
        )
    except FileNotFoundError as e:
        print(f"  数据文件未找到: {e}")
        print("  提示：将 PLAN.xlsx 和 CRANE.xlsx 放入 data/ 目录，或用 --plan-path/--crane-path 指定")
        sys.exit(1)
    except Exception as e:
        print(f"  基线失败: {e}")
        sys.exit(1)

    n_heats = baseline["heats"]
    success = baseline["success"]
    print(f"  纳入炉次: {n_heats}, 成功分配: {success} ({success/n_heats*100:.1f}%)" if n_heats else "  无数据")
    print(f"  真实行车: {', '.join(baseline['real_crane_ids'])}")

    # Load audit data for assignment details
    audit_path = Path(args.output_dir) / "decision_tree_audit.json"
    with open(audit_path, encoding="utf-8") as f:
        audit = json.load(f)

    scheduling_inputs = audit["scheduling_inputs"]
    heats = scheduling_inputs["heats"]
    ladles = scheduling_inputs["ladles"]
    cranes = scheduling_inputs["cranes"]
    assignments = audit["assignments"]

    print(f"  场景: {len(heats)} 炉次, {len(ladles)} 钢包, {len(cranes)} 台行车")

    # Step 2: RAG search demo
    print("\n[2/6] RAG 知识检索演示...")
    query = "行车离线故障后如何重新调度"
    results = kb.search(query, top_k=3)
    rag_context = kb.build_context_for_llm(query, top_k=3)
    for r in results:
        print(f"  [{r['similarity']:.2f}] [{r['source']}] {r['text'][:60]}...")

    # Step 3: Single disturbance demo
    print("\n[3/6] 单个扰动场景演示...")
    assigned_cranes = [a["crane_id"] for a in assignments if a.get("crane_id")]
    if not assigned_cranes:
        print("  无可用行车，跳过节单个场景")
    else:
        offline = assigned_cranes[0]
        spec = DisturbanceSpec(
            kind="crane_offline",
            resource_id=offline,
            description=f"行车 {offline} 离线故障",
        )
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        print(f"  扰动: 行车 {offline} 离线")
        print(f"  受影响炉次: {scenario.num_affected}")
        print(f"  需重分配炉次: {scenario.num_needing_reallocation}")
        print(f"  最早开浇剩余: {scenario.earliest_casting_seconds:.1f}s")
        print(f"  是否紧急: {'是' if scenario.is_emergency else '否'}")

        # Setup LLM rescheduler if API key provided
        llm = None
        if args.llm_api_key and not args.skip_llm:
            llm = ReActRescheduler(
                api_base=args.llm_api_base,
                api_key=args.llm_api_key,
                model=args.llm_model,
                max_rounds=args.llm_max_rounds,
                verbose=True,
            )
            llm_fn = lambda h, l, c: (
                lambda r: (r.success, r.assignments)
            )(llm.reschedule(h, l, c))
        else:
            llm_fn = None
            if not args.skip_llm:
                print("  (未提供 LLM API Key，跳过 LLM ReAct)")

        # Run tiered response
        controller = TieredResponseController(llm or llm_fn, rag_context=rag_context)
        primary, llm_result = controller.handle_disturbance(scenario)

        print(f"\n  响应路径: {primary.path.value}")
        print(f"  原因: {primary.reason}")
        print(f"  耗时: {primary.elapsed_seconds:.4f}s")
        print(f"  成功分配: {primary.num_assigned}/{len(primary.assignments)}")

        # Step 4: Three-way comparison (single)
        print("\n[4/6] 单场景三路对比...")
        comparison = controller.run_three_way(scenario, "demo_001")
        print(f"  Frozen: {comparison.frozen.num_assigned} 炉次")
        print(f"  决策树重排: {comparison.decision_tree.num_assigned} 炉次 (路径: {comparison.decision_tree.path.value})")
        if comparison.llm_react:
            print(f"  LLM ReAct: {comparison.llm_react.num_assigned} 炉次 (路径: {comparison.llm_react.path.value})")
            print(f"  LLM 额外救回: {comparison.llm_saved} 炉次")
        else:
            print(f"  LLM ReAct: 未触发（决策树成功或无 LLM）")

        # Step 5: Batch experiment
        print(f"\n[5/6] 批量实验（{args.num_scenarios} 场景）...")
        batch_config = BatchConfig(
            num_scenarios=args.num_scenarios,
            seed=args.seed,
            output_dir=args.output_dir,
        )
        runner = BatchRunner(config=batch_config, llm_rescheduler=llm_fn)
        result = runner.run(heats, ladles, cranes, assignments)

        s = result.summary
        print(f"  场景总数: {s['total_scenarios']}")
        print(f"  总受波及炉次: {s['total_affected_heats']}")
        print(f"  决策树成功率: {s['dt_success_rate']:.1%}")
        print(f"  决策树救回: {s['dt_total_saved_over_frozen']} 炉次")
        if s.get("llm_attempted"):
            print(f"  LLM 尝试: {s['llm_attempted']} 次, 成功率: {s['llm_success_rate']:.1%}")
            print(f"  LLM 额外救回: {s['llm_total_saved_over_dt']} 炉次")
            print(f"  LLM 平均耗时: {s['llm_avg_elapsed_s']:.1f}s" if s["llm_avg_elapsed_s"] is not None else "  LLM 平均耗时: N/A")
        else:
            print(f"  LLM: 未触发（所有场景决策树均成功或 LLM 未配置）")

    # Step 6: Output report
    print(f"\n[6/6] 输出报告已生成")
    print(f"  三路对比报告: {args.output_dir}/three_way_comparison.md")
    print(f"  三路对比数据: {args.output_dir}/three_way_comparison.json")
    print(f"  决策树审计: {args.output_dir}/decision_tree_audit.json")
    print(f"  结果摘要: {args.output_dir}/result_summary.md")
    print("\n" + "=" * 60)
    print("Demo 完成")


if __name__ == "__main__":
    main()
