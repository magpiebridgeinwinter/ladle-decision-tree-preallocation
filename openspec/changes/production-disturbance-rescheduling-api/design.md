## Context

当前 HTTP 服务由 `tools/serve_visualization.py` 提供，正常预配接口已经把上游炉次计划、钢包、行车和位置映射转换为决策树结果；`ladle_preallocation.response.controller` 已经具备扰动 Workflow、时间预算、硬约束校验和 Frozen/人工复核降级能力。现有 `/api/simulate` 只接收一个固定离线场景编号，不能承载真实现场事件，也没有持久化版本链路。

真实流程需要把一次正常配包结果作为不可变基线。后续扰动引用该基线，服务比较事件前后的资源快照，得到局部影响范围，再运行 Workflow 生成候选 revision。候选结果需要经过人工确认后才能发布；服务重启后仍应能查询事件和任务状态。

## Goals / Non-Goals

**Goals:**

- 增加版本化的生产扰动事件 API，覆盖事件接收、幂等、基线校验和当前快照记录。
- 将正常预配输出登记为 `plan_version`、`snapshot_version` 和 `allocation_version` 基线。
- 计算受影响、锁定和未受影响炉次，并将局部上下文交给现有 LLM Workflow。
- 用持久化任务状态记录 `received`、`scoped`、`running`、`pending_confirmation`、`frozen`、`published` 等状态。
- 提供候选结果查询、人工确认、驳回和发布接口；发布前必须再次执行版本和硬约束校验。
- 保留旧的正常预配、场景查询和 `/api/simulate` 演示语义。

**Non-Goals:**

- 不修改上游炉次计划，不让 LLM 生成炉次、重排计划顺序或改变锁定炉次。
- 不直接接入 PLC、行车控制器或现场 MES；本变更只提供已确认结果的发布边界。
- 不引入 FastAPI、LangGraph、Temporal、消息队列或外部数据库依赖。
- 不在本变更中实现复杂的多租户鉴权、限流和跨服务分布式事务。

## Decisions

### 1. 用独立生产扰动接口，不扩展 `/api/simulate`

新增资源路径 `/api/v1/ladle-preallocation/disturbances`。`/api/simulate` 继续作为固定场景演示入口，避免把演示数据约束带入生产协议。生产接口请求必须包含 `disturbance_id`、`plan_version`、`allocation_version`、`snapshot_version` 和当前快照。

### 2. 用不可变基线和父子 revision 管理版本

正常配包成功后登记一个不可变 `AllocationBaseline`。每次扰动产生一个 `ReschedulingJob` 和一个候选 `Revision`，并通过 `parent_revision_id` 指向基线或上一版已发布结果。事件重复提交返回同一个任务；基线版本不匹配返回 `409`，不得偷偷以最新数据重算。

### 3. 首期采用同步执行、持久化结果

HTTP 接收扰动后在一个请求内执行局部范围计算和 Workflow，返回 `202`（已创建任务）或 `200`（已完成候选结果）。任务、事件和结果在 SQLite 中保存；接口同时提供状态查询，因此后续可以在不改变契约的情况下把 Workflow 执行移到后台 worker。LLM 的时间预算仍由领域控制器负责。

### 4. 复用现有领域控制器和确定性校验

API 层只负责协议校验、版本和快照管理、影响范围编排及响应映射。扰动类型复用 `disturbance.catalog`；Workflow 复用 `TieredResponseController`/`ReActRescheduler` 的状态、预算和校验器。任何 LLM 方案必须覆盖全部可重调度炉次、只使用快照中的资源且不修改锁定/影响范围外炉次。

### 5. 明确结果状态机和发布安全门

```text
RECEIVED -> SCOPED -> RUNNING -> PENDING_CONFIRMATION
                         |                 |
                         v                 v
                    FROZEN/REVIEW      REJECTED
                                           |
                                  PENDING_CONFIRMATION
                                           |
                                           v
                                      PUBLISHED
```

`confirm` 只把通过校验的候选结果变为 `confirmed`；`publish` 必须检查当前基线仍匹配、候选未过期且校验通过，成功后才变为 `published`。Frozen 或人工复核结果不能直接发布。

### 6. SQLite 仓储抽象

定义小型 repository 接口，默认实现使用单个 SQLite 文件保存 JSON 摘要：`baselines`、`disturbance_events`、`rescheduling_jobs`、`revisions` 和 `audit_events`。写入采用事务和唯一键约束：`disturbance_id` 唯一，`(plan_version, allocation_version)` 唯一，revision 状态迁移由服务层白名单控制。完整请求、API Key、Authorization 和 prompt 不持久化。

### 7. API 资源

- `POST /api/v1/ladle-preallocation/allocate`：现有接口增加版本字段和可选基线登记。
- `POST /api/v1/ladle-preallocation/disturbances`：接收生产扰动并创建重调度任务。
- `GET /api/v1/ladle-preallocation/jobs/{job_id}`：查询任务状态、影响范围和非敏感审计。
- `GET /api/v1/ladle-preallocation/revisions/{revision_id}`：查询候选/已确认/已发布结果。
- `POST /api/v1/ladle-preallocation/revisions/{revision_id}/confirm`：人工确认或驳回候选结果。
- `POST /api/v1/ladle-preallocation/revisions/{revision_id}/publish`：发布已确认结果，返回发布凭证。

### 8. 兼容和错误语义

保留已有 `200/400/409/422/503` 语义。新增接口使用 `202` 表示任务已创建但仍在 Workflow 中；`409` 表示版本冲突、重复事件或非法状态迁移；`422` 表示输入合法但无法生成可执行候选；`423` 表示结果被冻结或仍需人工处理。所有错误返回 `error`、相关资源标识和可重试提示，不返回敏感输入。

## Risks / Trade-offs

- [Risk] 当前标准库 HTTP 服务不是长期后台任务框架 → 首期同步执行并持久化，保留 job 查询契约，后续可替换为 worker。
- [Risk] SQLite 单文件不适合多实例并发写入 → 通过事务、短写锁和 repository 抽象限制首期部署为单实例；生产扩展时替换存储实现。
- [Risk] 事件快照可能不完整或晚于截止时间 → 在 Workflow 前做字段和新鲜度校验，返回 Frozen/人工复核，不伪造可执行结果。
- [Risk] LLM 方案可能越权修改未受影响炉次 → 校验候选覆盖集、锁定集合和影响范围差异，任何越权方案拒绝。
- [Risk] 人工确认后资源再次变化 → 发布时重新读取基线和快照版本，发现冲突返回 `409`，要求重新生成 revision。

## Migration Plan

1. 为正常预配响应增加稳定版本字段并登记基线；旧客户端仍可读取原字段。
2. 增加 SQLite repository、生产扰动请求模型、影响范围计算和 API 路由。
3. 将现有扰动 Workflow 接到生产事件上下文，覆盖成功、Frozen、人工复核和非法提案。
4. 增加任务查询、revision 查询、确认/驳回和发布安全门。
5. 同步 OpenAPI、Markdown 文档和契约测试；使用旧接口回归验证兼容性。
6. 回滚时停止新扰动路由并继续使用正常预配和 `/api/simulate`；已有数据库记录保留，不影响离线场景库。

## Open Questions

- 现场对“已锁定炉次”的最终定义是已开吹、已起吊、已到工位，还是由上游显式传递状态；首期允许请求携带 `locked_heat_ids`，默认只锁定已开始执行的炉次。
- 确认后的发布结果由哪个下游系统接收以及是否需要签名回执，待现场控制系统协议确定后接入。
- 多个扰动在同一快照窗口内是否合并为一个事件；首期按 `disturbance_id` 单事件处理，调用方可提交复合事件类型。
