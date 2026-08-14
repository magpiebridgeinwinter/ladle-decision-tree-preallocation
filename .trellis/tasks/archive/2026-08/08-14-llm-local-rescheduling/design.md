# Technical Design: LLM 局部重调度

## Architecture

将流程拆为四个明确边界：

1. `real_data` 将 PLAN/CRANE 归一化为带绝对时刻和相对调度字段的场景。
2. 新的滑窗状态管理器按事件时间推进炉次状态，并仅向决策树暴露当前可预配或需重调度的局部集合。
3. `disturbance` 以事件模型计算受影响资源与炉次；`response` 以显式预算选择决策树、LLM 或 Frozen。
4. `experiment` 以同一个不可变 baseline 分别评估 Frozen、决策树和 LLM，并通过共享指标模块生成报告。

## Data Contracts

### Heat Lifecycle

每个炉次状态包含 `heat_id`、`state`、`preallocated_at`、`locked_at`、`assignment` 和 `revision`。

- `unallocated -> preallocated`: 炉次进入 180 分钟窗口并通过决策树得到分配。
- `preallocated -> locked`: 到达开吹/锁定时刻，保留当前分配。
- `preallocated -> preallocated`: 扰动重调度成功，替换分配并增加 `revision`。
- `preallocated -> unallocated`: Frozen 或无法分配时仅记录失败，不修改已锁定炉次。

状态迁移必须集中在一个模块中，不得在 pipeline、injector 和 controller 各自维护状态副本。

### Disturbance Event

事件包含 `kind`、`resource_id`、`occurred_at`、`metadata` 和可读描述。影响分析以生命周期状态为输入：锁定炉次不进入 `heats_needing_reallocation`，但仍保留在审计中。

`earliest_pour_at` 必须是与 `occurred_at` 相同基准的绝对时刻或明确相对时刻。控制器只接受已计算的 `remaining_budget_seconds`，避免再解释时间字段。

### Response Result

保持已有 `ResponseResult`，新增或标准化：`remaining_budget_seconds`、`human_review_required`、`failure_reasons`、`validation_feedback` 和可序列化的 audit metadata。成功只代表所有受影响的可重调度炉次经硬约束校验；部分成功必须显式失败或按定义产生人工复核。

### Metrics

按路径接收 `baseline_assignments`、`response_assignments`、heats 和响应元数据，返回统一的数值或 `None`。

- 按时与延迟基于 `expected_arrival_seconds <= window_end`。
- `changed_heats` 仅比较可重调度炉次的钢包/行车映射。
- `human_review_rate` 依据人工复核或 Frozen 信号。
- LLM 核心指标仅对决策树失败且 LLM 被尝试的场景聚合。

## LLM Time Budget

控制器计算 `budget = earliest_pour_at - now - 90`。预算大于零才创建 LLM 调用；ReAct 每轮使用不超过剩余预算的 HTTP timeout，并在下一轮前重新读取时钟。预算耗尽后返回失败，让控制器产生 Frozen + 人工复核结果。

LLM 的 JSON 解析、方案完整性验证、资源唯一性和既有 `validate_assignment` 都必须完成后才视为成功。RAG 上下文可附加到 prompt，但不参与硬约束判断。

## Experiment Design

批量运行器生成可序列化的事件时间和类型，固定 seed 下保持可复现。生产路径始终遵守“决策树优先”；`force_llm_on_success` 只允许生成额外实验记录，不能替换有效响应。报告同时写 Markdown 与 JSON，使用同一指标 payload。

## Compatibility And Rollback

- 保留 `run_pipeline` 的现有默认行为，通过显式滑窗选项或新的入口启用生命周期执行，先以兼容模式保护现有 416 炉次审计。
- 保留 `DisturbanceSpec` 现有字段，新增字段给默认值。
- LLM 配置默认关闭或无密钥即失败到 Frozen，不影响离线决策树运行。
- 如果滑窗输出与旧全量结果出现不可解释偏差，可通过兼容模式回退到原 `run_pipeline`，并保留审计差异供分析。

## Primary Files

- `ladle_preallocation/real_data/pipeline.py`: 真实数据入口和兼容模式。
- `ladle_preallocation/disturbance/injector.py`: 事件模型、受影响范围与时间语义。
- `ladle_preallocation/response/controller.py`: 分级响应和预算门控。
- `ladle_preallocation/llm/react_agent.py`、`prompts.py`: ReAct 调用、预算与反馈输入。
- `ladle_preallocation/experiment/batch_runner.py`、`evaluation/metrics.py`: 多路径评估与指标。
- `ladle_preallocation/demo.py`、`README.md`、`tests/`: 可运行 Demo、文档和回归测试。
