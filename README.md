# 钢包决策树预配包与局部重调度

系统以真实 `PLAN` 炉次计划和 `CRANE` 行车快照驱动可解释决策树预配包。决策树始终是生产主路径；仅当非紧急扰动下决策树局部重排失败时，才允许 LLM ReAct 在既有硬约束校验内尝试兜底。

## 运行入口

| 用途 | 命令 |
| --- | --- |
| 兼容全量回放 | `python -m ladle_preallocation.real_data.pipeline` |
| 180 分钟滑窗预配 | `python -m ladle_preallocation.real_data.pipeline --sliding-window` |
| 离线重调度 Demo | `python -m ladle_preallocation.demo --skip-llm --num-scenarios 10` |
| 使用 LLM 的 Demo | `python -m ladle_preallocation.demo --llm-api-key "$DEEPSEEK_API_KEY"` |
| 测试 | `python -m pytest -q` |

先创建环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

真实数据入口会写入 `outputs/decision_tree_audit.json` 和 `outputs/result_summary.md`。启用滑窗时，审计文件还会保留每个炉次的 `unallocated`、`preallocated`、`locked` 生命周期记录。

## 扰动响应

1. 在转炉开吹前 180 分钟进入预配窗口；已经吹炼的炉次锁定，不能被扰动重写。
2. 行车不可用、钢包不可用、设施不可用或计划偏差只影响仍可重调度的局部炉次。
3. 以 `最早开浇时刻 - 事件时刻 - 90 秒` 计算预算。预算耗尽时只执行决策树；失败后 Frozen 并要求人工复核。
4. 预算充足时先执行决策树，失败后才调用 LLM。任何 LLM 输出都必须通过同一套钢包状态、载重、运行区间、时间窗和安全间距校验。

LLM API 密钥只通过命令行或环境变量提供，绝不写入代码、审计或报告。离线测试和 `--skip-llm` Demo 不会访问外部网络。

## 结果与边界

批量实验为 Frozen、决策树和 LLM 路径分别输出按时率、优先级加权按时率、延迟、变更炉次、人工复核率、规则违反数和决策耗时；LLM 核心指标只在“决策树失败且实际尝试 LLM”的样本上计算。

这是处理后历史数据的离线回放与 Demo，不代表现场生产控制验收，也不替代人工审批或现场安全机制。
