## ADDED Requirements

### Requirement: Normal allocation creates a versioned baseline
正常预配接口成功或部分完成时 MUST 返回稳定的 `plan_version`、`snapshot_version` 和 `allocation_version` 字段，或返回可供服务登记基线的等价标识。版本值 MUST 能够唯一关联本次请求的输入快照和配包结果。

#### Scenario: Complete allocation baseline
- **WHEN** `POST /api/v1/ladle-preallocation/allocate` 完成决策树预配
- **THEN** 响应 MUST 包含版本字段，且后续扰动可以引用该 `allocation_version`

### Requirement: Baseline preserves upstream plan ownership
版本化基线 MUST 保留上游炉次计划作为只读事实输入。生成版本或后续扰动不得在配包服务内部补造、删除或重排上游炉次计划。

#### Scenario: Disturbance references plan baseline
- **WHEN** 扰动请求引用一个有效的 `plan_version`
- **THEN** 服务 MUST 使用该版本中的炉次作为事实基线，并只生成局部配包 revision

### Requirement: Baseline output remains compatible
增加版本字段 MUST 保留现有正常预配响应中的 `request_id`、`status`、`results`、`metrics` 和 `audit` 字段，现有调用方可以继续解析原有配包结果。

#### Scenario: Existing client reads allocation
- **WHEN** 旧客户端调用正常预配接口
- **THEN** 服务 MUST 继续返回原有结果字段，同时附加版本和基线信息，不得把正常请求路由到 LLM
