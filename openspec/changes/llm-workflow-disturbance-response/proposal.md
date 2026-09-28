## Why

正常钢包预配包已经有稳定的决策树主路径，但扰动响应仍把同一个决策树作为第一层重排器，导致“突发情况由 LLM 处理”的产品边界不清晰。现在需要把炉次计划作为明确的上游输入，把预配包和扰动重调度拆成两个阶段，并让扰动阶段通过可审计的 LLM Workflow 直接处理复杂事件，同时保留确定性约束校验和人工降级。

## What Changes

- 保留决策树作为正常预配包和滑窗预配的唯一生产主路径。
- 将扰动响应的生产路径改为：事件快照 → 局部上下文 → LLM Workflow → 硬约束校验 → 可执行方案或人工复核。
- **BREAKING** 移除扰动生产路径中“先运行决策树局部重排、失败后才调用 LLM”的默认顺序。
- 保留决策树局部重排接口作为离线基线和对比实验能力，不再由默认扰动响应自动调用。
- 为 LLM Workflow 增加明确的阶段状态、失败原因、时间预算、校验反馈和审计字段。
- 保证 LLM 输出不能绕过钢包状态、载重、运行区间、时间窗、安全距离、锁定炉次和影响范围校验。
- 保留紧急场景的安全降级：LLM 在剩余预算不足或调用失败时返回 Frozen/人工复核，不产生未经校验的下发结果。
- 明确配置契约：CLI 参数和进程环境变量继续支持 LLM 配置；不假设 `.env.local` 会被自动加载。
- 更新文档、测试和演示，使上游炉次计划、预配包输出、扰动输入和 Workflow 输出边界可追踪。

## Capabilities

### New Capabilities

- `llm-disturbance-workflow`: 定义突发事件进入 LLM Workflow、状态转换、校验、降级和审计契约。
- `ladle-preallocation-flow`: 定义上游炉次计划、CRANE/位置数据、决策树预配包及其输出审计契约。

### Modified Capabilities
<!-- 当前仓库没有 openspec/specs 主规格，因此不创建 delta spec。 -->

## Impact

- 影响 `ladle_preallocation/response/controller.py`、`ladle_preallocation/llm/react_agent.py`、LLM prompt、扰动场景模型和相关测试。
- 影响 Demo、可视化实时接口、三路离线评估的路径标签和文档说明。
- 不修改原始 PLAN、CRANE、位置映射文件，不增加新的外部运行时依赖。
- 现有离线数据库和审计格式需要向后兼容，并增加 Workflow 状态与配置来源字段。
