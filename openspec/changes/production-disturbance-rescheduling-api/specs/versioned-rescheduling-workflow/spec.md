## ADDED Requirements

### Requirement: Workflow derives a bounded impact scope
服务 MUST 基于扰动事件、配包基线和当前快照确定 `affected_heat_ids`、`locked_heat_ids`、可用资源和时间预算。LLM 上下文 MUST 只包含影响范围内数据和必要约束。

#### Scenario: Crane outage affects local heats
- **WHEN** 一台行车离线且只有两条未执行炉次使用该行车
- **THEN** Workflow MUST 将这两条炉次列为 affected，已开始执行的炉次列为 locked，并排除离线行车

### Requirement: Disturbance workflow uses the LLM path
包含可重调度炉次且剩余时间预算大于零的生产扰动 MUST 进入现有 LLM Workflow；正常预配使用的决策树 MUST 不作为生产扰动的隐式前置调度器。

#### Scenario: Non-emergency disturbance
- **WHEN** 影响范围非空、LLM 已配置且距离安全截止时间仍有预算
- **THEN** Workflow MUST 进入 LLM 提案阶段，并记录模型配置来源、阶段转换和预算

#### Scenario: No remaining budget
- **WHEN** 距最早开浇时间小于等于安全阈值
- **THEN** Workflow MUST 跳过 LLM 调用，返回 Frozen/人工复核结果并记录 `budget_exhausted`

### Requirement: LLM proposals pass deterministic acceptance
服务 MUST 仅接受完整覆盖受影响可重调度炉次、资源唯一、满足载重/位置/时间窗/等级/路线约束且不修改锁定或影响范围外炉次的 LLM 方案。

#### Scenario: Valid local proposal
- **WHEN** LLM 为所有 affected 炉次返回合法且唯一的钢包-行车映射
- **THEN** 服务 MUST 生成候选 revision，保存逐炉变更、校验结果和非敏感 Workflow 审计

#### Scenario: Proposal changes locked heat
- **WHEN** LLM 修改已锁定炉次或影响范围外炉次
- **THEN** 服务 MUST 拒绝该提案，并在剩余预算内反馈修正或降级人工复核

### Requirement: Workflow failure is explicit and recoverable
LLM 未配置、调用异常、超时、多轮修正失败或提案非法时 MUST 返回结构化失败原因和 `Frozen`/`human_review` 状态，不得伪造成功分配。

#### Scenario: LLM unavailable
- **WHEN** LLM API Key 未配置或外部调用超时
- **THEN** 服务 MUST 生成 Frozen/人工复核结果，`api_configured` MUST 为 false 或记录超时原因

### Requirement: Workflow state is persisted
服务 MUST 持久化事件、任务、阶段、候选 revision、校验结果、错误原因和父版本关系，使进程重启后可以恢复查询，不得只保存在内存中。

#### Scenario: Recover a running job
- **WHEN** 服务在任务已创建后重启
- **THEN** `GET /api/v1/ladle-preallocation/jobs/{job_id}` MUST 返回最后一个已持久化状态和可继续处理的标识
