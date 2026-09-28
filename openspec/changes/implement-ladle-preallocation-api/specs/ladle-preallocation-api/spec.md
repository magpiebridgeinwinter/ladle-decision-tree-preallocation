## ADDED Requirements

### Requirement: Normal preallocation endpoint accepts upstream plans
服务 MUST 提供 `POST /api/v1/ladle-preallocation/allocate`，并接收 JSON 格式的上游炉次计划、钢包资源、行车快照和可选位置映射。服务 MUST 将上游炉次计划视为输入，不得在接口内重新编排、补造或改写炉次计划。

#### Scenario: Valid preallocation request
- **WHEN** 调用方以 `application/json` 提交包含 `request_id`、至少一条 `heats`、`ladles` 和 `cranes` 的请求
- **THEN** 服务 MUST 返回 HTTP `200` 或表示业务不可行的 HTTP `422`，且响应 MUST 包含同一个 `request_id`

#### Scenario: Malformed request body
- **WHEN** 请求体不是合法 JSON，或缺少 `request_id`、`heats`、`ladles` 或 `cranes`
- **THEN** 服务 MUST 返回 HTTP `400` 和结构化 `OutputErrorResponse`，不得调用决策树

### Requirement: Input fields are normalized before allocation
服务 MUST 在调用决策树前校验和标准化炉次、钢包、行车和位置字段。时间字段 MUST 使用可解析的 RFC 3339/date-time 值，资源编号 MUST 非空且在同一请求中唯一，位置映射冲突 MUST 被拒绝。

#### Scenario: Normalize scheduling inputs
- **WHEN** 请求包含合法的炉次时间、吨位、坐标、运行区间和资源状态
- **THEN** 服务 MUST 构造与离线 pipeline 兼容的 `heats`、`ladles` 和 `cranes`，并保留原始主键用于响应映射

#### Scenario: Conflicting resource snapshot
- **WHEN** 两条钢包记录使用同一个 `ladle_id`，或两条行车记录使用同一个 `crane_id`
- **THEN** 服务 MUST 返回 HTTP `409`，并说明冲突资源，不得产生部分分配结果

### Requirement: Normal preallocation uses the decision tree
正常预配包接口 MUST 调用现有决策树和共享硬约束终检，不得调用 LLM 作为正常路径的一部分。每个输入炉次 MUST 最终有一条结果记录。

#### Scenario: Complete assignment
- **WHEN** 决策树为所有输入炉次找到通过硬约束的钢包和行车
- **THEN** 服务 MUST 返回 `status=completed`，并为每条炉次返回 `ladle_id`、`crane_id`、预计到达或等待信息、等级匹配和决策路径

#### Scenario: Partial assignment
- **WHEN** 至少一条炉次无法找到通过硬约束的候选资源
- **THEN** 服务 MUST 返回 HTTP `422` 或 `status=partial`，未分配炉次 MUST 包含原因和 violations，且不得将其标记为已分配

### Requirement: Response distinguishes output sections
成功或业务失败响应 MUST 明确区分逐炉次 `results`、汇总 `metrics` 和审计 `audit`。每条结果 MUST 包含 `plan_key`、`heat_id`、`algorithm` 和状态；算法值 MUST 为 `decision_tree`。

#### Scenario: Inspect allocation response
- **WHEN** 调用方读取 HTTP 响应
- **THEN** 响应 MUST 包含 `request_id`、顶层 `status`、`algorithm`、`results`、`metrics`，并在可用时包含 `audit`

#### Scenario: Audit without secrets
- **WHEN** 服务写入或返回审计摘要
- **THEN** 审计 MUST 记录输入来源、算法版本、排除数量和标准化统计，但 MUST NOT 包含 `LLM_API_KEY`、Authorization header 或完整请求密钥

### Requirement: Existing disturbance APIs remain compatible
新增正常预配包接口 MUST 不改变 `GET /api/scenarios/summary`、`GET /api/scenarios`、`GET /api/scenarios/{scenario_id}` 和 `POST /api/simulate` 的路径、请求语义和响应状态。

#### Scenario: Existing disturbance simulation
- **WHEN** 客户端继续调用 `POST /api/simulate`
- **THEN** 服务 MUST 继续返回当前扰动 Workflow 的成功、Frozen 或人工复核结果，不得路由到正常预配包算法
