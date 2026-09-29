## Why

当前服务可以生成正常预配包，也可以对固定离线场景运行扰动 Workflow，但真实生产扰动没有可接入的事件边界。上游炉次计划、行车、钢包和工艺状态变化后，系统无法可靠地识别基线版本、计算局部影响范围、避免重复处理，或追踪候选方案到人工确认和发布的完整链路。

需要增加面向生产的版本化扰动重调度能力，使每次重调度都基于明确的计划和配包结果版本，保留确定性硬约束校验，并在 LLM 不可用、超时或方案不合法时稳定降级到 Frozen/人工复核。

## What Changes

- 增加生产扰动事件接收接口，支持行车、钢包、设施、工艺路线、计划时间和复合扰动。
- 为计划、资源快照、初始配包、扰动事件和重调度结果建立版本与父子关系。
- 校验扰动幂等性和基线版本，拒绝重复事件、过期结果和不一致快照。
- 根据扰动事件和配包基线计算受影响炉次、锁定炉次、可用资源和时间预算。
- 将受影响局部场景送入现有 LLM Workflow；LLM 结果必须经过共享硬约束和影响范围校验。
- 增加重调度任务状态、结果查询、人工确认和结果发布接口；生成方案和下发方案保持分离。
- 持久化事件、Workflow 状态、校验结果、人工操作和版本审计，支持恢复和追溯。
- 保持正常预配包继续由决策树执行，保留现有离线场景查询和 `/api/simulate` 演示接口。
- **BREAKING** 生产扰动调用方必须提交 `plan_version`、`allocation_version`、`disturbance_id` 和当前快照版本；旧的固定 `scenario_id` 语义不作为生产扰动协议。

## Capabilities

### New Capabilities

- `production-disturbance-events`: 接收、校验、去重并持久化生产扰动事件和资源快照。
- `versioned-rescheduling-workflow`: 基于配包版本计算影响范围，执行 LLM Workflow、硬约束校验和失败降级。
- `rescheduling-review-and-publication`: 提供重调度任务查询、候选结果查询、人工确认和结果发布状态机。
- `versioned-preallocation-baseline`: 扩展正常预配输出的版本字段，并定义其作为后续扰动重调度的基线。

### Modified Capabilities

无。正常预配的版本化输出在本变更中作为新增的生产基线契约定义。

## Impact

- HTTP 路由和 OpenAPI：新增生产扰动、任务状态、结果、确认和发布接口。
- Python 服务层：扩展 `tools/serve_visualization.py` 的 API 分发，并增加事件、版本、任务和状态模型。
- 领域层：复用 `ladle_preallocation.disturbance`、`response.controller` 和硬约束验证器，增加影响范围和版本冲突校验。
- 存储层：增加本地可替换的持久化接口和默认 SQLite 实现，保存事件、快照摘要、Workflow 记录和审计。
- 配置与安全：LLM 密钥继续只从进程环境读取；请求、响应和审计不得包含密钥、完整 prompt 或认证头。
- 测试与文档：增加契约、幂等、版本冲突、状态迁移、人工确认和发布安全门测试，并同步 Swagger 和接口文档。
