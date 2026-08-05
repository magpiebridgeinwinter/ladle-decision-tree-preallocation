# 钢包决策树预配包

本项目只保留一种方法：基于真实 `PLAN` 炉次计划和 `CRANE` 行车快照的可解释规则决策树。不再包含启发式、遗传算法、DQN/DRL 或 LLM 重调度实现。

## 从哪里开始

| 需要查看的内容 | 文件/目录 |
| --- | --- |
| 唯一运行入口 | `ladle_preallocation/real_data/pipeline.py` |
| 决策树主逻辑 | `ladle_preallocation/decision_tree/allocator.py` |
| 硬约束 | `ladle_preallocation/decision_tree/constraints.py` |
| 候选评分和权重 | `ladle_preallocation/decision_tree/scoring.py` 和 `config.py` |
| PLAN/CRANE 数据处理 | `ladle_preallocation/real_data/` |
| 输入数据 | `data/` |
| 最终结果 | `outputs/` |
| 验证用例 | `tests/` |

## 运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m ladle_preallocation.real_data.pipeline
```

运行入口会重新生成 `outputs/decision_tree_audit.json` 和 `outputs/result_summary.md`。`tools/build_outputs.mjs` 用于将审计结果生成 Excel/CSV 交付表。

## 决策流程

1. 从 PLAN 剔除主键、时间或位置无效的炉次，并与 CRANE 时间范围对齐。
2. 对每个炉次生成钢包-行车候选组合。
3. 先检查钢包状态、载重、行车运行区间、时间窗和安全间距等硬约束。
4. 对可行候选按真实行车距离、等待时间、作业均衡、钢包等级建议进行评分。
5. 选择得分最高的可行组合，终检后输出钢包号、真实行车号和决策路径。
6. 按当前业务约定，本次转运完成后钢包立即释放，可参与下一炉次预分配。

## 当前全量结果

- 纳入炉次：416 条。
- 成功分配：416/416，配包成功率 100.00%。
- 硬约束违反：0。
- 平均预计等待：0.088 秒。
- 等级匹配率：82.93%；按当前要求，等级只用于软评分，不作为配包硬约束。
- 结果为处理后数据的离线回放，不代表现场实时生产验收。
