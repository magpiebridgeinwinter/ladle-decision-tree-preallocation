## ADDED Requirements

### Requirement: Production disturbance endpoint accepts versioned events
服务 MUST 提供 `POST /api/v1/ladle-preallocation/disturbances`，接收生产扰动事件、基线版本和当前资源快照。请求 MUST 包含 `disturbance_id`、`event_type`、`occurred_at`、`plan_version`、`allocation_version` 和 `snapshot_version`。

#### Scenario: Accept a crane disturbance
- **WHEN** 调用方提交合法的行车离线事件和与当前配包匹配的版本字段
- **THEN** 服务 MUST 创建扰动任务，保存事件摘要，并返回 `disturbance_id`、`job_id` 和任务状态

#### Scenario: Reject malformed event
- **WHEN** 请求缺少事件编号、事件类型、发生时间或任一基线版本
- **THEN** 服务 MUST 返回 HTTP `400`，且不得启动 Workflow

### Requirement: Disturbance events are idempotent
服务 MUST 以 `disturbance_id` 和幂等键保证同一事件最多创建一个任务。重复请求 MUST 返回原任务标识和当前状态，不得重复调用 LLM 或产生新的 revision。

#### Scenario: Retry the same event
- **WHEN** 调用方使用相同 `disturbance_id` 重试已经接收的事件
- **THEN** 服务 MUST 返回原 `job_id` 和 `revision_id`（若已生成），并标记请求为重复请求

### Requirement: Baseline versions are checked before processing
服务 MUST 校验扰动引用的 `plan_version`、`allocation_version` 和 `snapshot_version` 存在、相互关联且仍是可重调度基线。版本不匹配时 MUST 返回 `409`，不得使用服务端最新版本隐式替换请求版本。

#### Scenario: Stale allocation version
- **WHEN** 扰动引用的配包版本已经被另一条 revision 发布
- **THEN** 服务 MUST 返回 HTTP `409`，并返回当前有效版本标识和冲突原因

### Requirement: Current snapshots are validated and redacted
服务 MUST 校验当前快照中的炉次、钢包、行车、位置和设施字段，拒绝重复资源、非法状态、过期遥测和与事件声明不一致的资源变化。服务 MUST 只保存非敏感摘要，不得保存 API Key、Authorization、完整 prompt 或完整请求头。

#### Scenario: Crane state matches event
- **WHEN** 事件声明行车 `2500` 离线且当前快照也标记其为 offline
- **THEN** 服务 MUST 允许进入影响范围计算，并在审计中记录该资源状态差异

#### Scenario: Snapshot contradicts event
- **WHEN** 事件声明行车离线但当前快照仍为 online 且没有更新时刻可解释该差异
- **THEN** 服务 MUST 返回 HTTP `409` 或 `422`，并要求调用方刷新快照

### Requirement: Event types cover production change sources
服务 MUST 支持至少以下事件分组：上游炉次计划、行车、钢包、设施/工艺路线、时间节拍和复合扰动。未知 `event_type` MUST 被拒绝，不能静默按普通事件处理。

#### Scenario: Plan change event
- **WHEN** 上游提交新增、删除、时间变化或优先级变化的炉次计划事件
- **THEN** 服务 MUST 保存计划差异，并将受影响炉次纳入后续影响范围计算
