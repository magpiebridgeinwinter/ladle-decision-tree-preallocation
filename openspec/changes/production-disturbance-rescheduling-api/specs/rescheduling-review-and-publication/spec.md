## ADDED Requirements

### Requirement: Job and revision status are queryable
服务 MUST 提供 `GET /api/v1/ladle-preallocation/jobs/{job_id}` 和 `GET /api/v1/ladle-preallocation/revisions/{revision_id}`，返回任务状态、基线版本、影响范围、结果状态、校验摘要和下一步动作。

#### Scenario: Query candidate revision
- **WHEN** 调用方查询一个已生成但尚未确认的 revision
- **THEN** 服务 MUST 返回 `pending_confirmation`、逐炉变更、校验结果和对应的 `parent_revision_id`

#### Scenario: Query unknown job
- **WHEN** 请求的 `job_id` 不存在
- **THEN** 服务 MUST 返回 HTTP `404` 和结构化错误

### Requirement: Candidate results require confirmation before publication
服务 MUST 提供 `POST /api/v1/ladle-preallocation/revisions/{revision_id}/confirm`。只有通过硬约束校验且基线未变化的候选 revision 才能被确认；确认请求 MUST 记录操作者、时间和决定。

#### Scenario: Confirm a valid candidate
- **WHEN** 操作者确认一个未过期且校验通过的候选 revision
- **THEN** 服务 MUST 将其状态改为 `confirmed` 并允许后续发布

#### Scenario: Reject a candidate
- **WHEN** 操作者驳回候选 revision 并提供原因
- **THEN** 服务 MUST 将其状态改为 `rejected`，不得发布该 revision

### Requirement: Publishing is a separate safety gate
服务 MUST 提供 `POST /api/v1/ladle-preallocation/revisions/{revision_id}/publish`。发布前 MUST 重新检查父版本、当前资源快照、候选校验结果和确认状态；Frozen、rejected、过期或未确认的 revision MUST 不得发布。

#### Scenario: Publish confirmed revision
- **WHEN** revision 已确认且父版本仍为当前有效版本
- **THEN** 服务 MUST 将 revision 标记为 `published` 并返回发布凭证和新 allocation version

#### Scenario: Publish after resource change
- **WHEN** 确认后资源快照版本发生变化
- **THEN** 服务 MUST 返回 HTTP `409`，保持原 revision 不变并要求重新生成方案

### Requirement: State transitions are constrained
服务 MUST 只允许合法状态迁移：`received -> scoped -> running -> pending_confirmation -> confirmed -> published`，失败分支进入 `frozen`、`human_review` 或 `rejected`。非法状态迁移 MUST 返回 HTTP `409`。

#### Scenario: Publish unconfirmed revision
- **WHEN** 调用方尝试直接发布 `pending_confirmation` revision
- **THEN** 服务 MUST 返回 HTTP `409`，状态保持不变

### Requirement: Responses expose audit-safe traceability
任务和 revision 响应 MUST 返回 `disturbance_id`、`plan_version`、`allocation_version`、`snapshot_version`、`revision_id`、`parent_revision_id`、算法路径、影响范围和校验摘要，但 MUST NOT 返回密钥、认证头或完整 LLM prompt。

#### Scenario: Inspect published result
- **WHEN** 调用方读取已发布 revision
- **THEN** 响应 MUST 能追溯其扰动、基线、父版本、确认记录和发布凭证
