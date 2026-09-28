## ADDED Requirements

### Requirement: Disturbance enters the LLM workflow
系统 MUST 将每个包含可重调度炉次的突发场景送入显式 LLM Workflow；生产路径 MUST 不再先调用决策树局部重排作为 LLM 前置条件。

#### Scenario: Non-emergency disturbance with configured LLM
- **WHEN** 场景包含待重分配炉次、LLM 已配置且剩余预算大于零
- **THEN** Workflow MUST 直接构造局部上下文并调用 LLM ReAct，且结果路径不得标记为 `decision_tree_success` 或 `decision_tree_failure`

#### Scenario: Emergency or exhausted-budget disturbance
- **WHEN** 场景进入 Workflow 但剩余预算小于等于零
- **THEN** Workflow MUST 记录预算门结果，不等待外部 LLM，并返回 Frozen/人工复核结果

### Requirement: Workflow context is bounded and traceable
Workflow MUST 将受影响炉次、锁定排除炉次、可用钢包、可用行车、事件状态差异、时间预算和失败上下文传给 LLM，并 MUST 记录非敏感的输入摘要。

#### Scenario: Context construction
- **WHEN** Workflow 到达 LLM 提案阶段
- **THEN** 上下文 MUST 只包含当前局部场景资源和约束，不得包含 API 密钥、Authorization header 或未参与场景的资源

### Requirement: LLM proposals require deterministic acceptance
Workflow MUST 只有在方案完整覆盖待重分配炉次、通过共享硬约束校验且未修改影响范围外炉次时才接受 LLM 结果。

#### Scenario: Valid proposal
- **WHEN** LLM 返回唯一且完整的炉次-钢包-行车映射，并通过载重、位置、时间窗、安全距离和锁定保护校验
- **THEN** Workflow MUST 返回可执行的 LLM 结果并保留校验反馈与审计信息

#### Scenario: Invalid or partial proposal
- **WHEN** LLM 返回缺失、重复、未知资源或违反任一硬约束的方案
- **THEN** Workflow MUST 将结果标记为失败，不得将其作为有效分配，并 MUST 返回人工降级或继续在剩余预算内反馈修正

### Requirement: Failure degradation is explicit
Workflow MUST 在 LLM 未配置、调用异常、超时、预算耗尽或多轮修正仍失败时返回 Frozen/人工复核信号，并说明失败原因。

#### Scenario: Missing configuration
- **WHEN** LLM API key 未配置
- **THEN** Workflow MUST 不伪造成功结果，返回人工复核所需的结构化错误和 `api_configured=false`

### Requirement: Offline deterministic baseline remains available
系统 MUST 保留决策树局部重排的显式调用能力，用于离线三路比较和回归评估，但该能力不得被默认扰动生产 Workflow 自动调用。

#### Scenario: Benchmark invocation
- **WHEN** 离线评估显式请求决策树路径
- **THEN** 系统 MUST 运行决策树并将其标记为基线结果，与 LLM Workflow 结果分开审计
