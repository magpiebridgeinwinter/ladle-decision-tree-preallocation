## Context

当前服务由 `tools/serve_visualization.py` 提供标准库 HTTP 服务，已经有离线场景查询和 `POST /api/simulate` 扰动模拟。正常预配包的核心能力已经存在于 `ladle_preallocation.real_data`、`ladle_preallocation.decision_tree` 和 `ladle_preallocation.evaluation`，但没有 HTTP 适配层，因此 OpenAPI 中的 `/api/v1/ladle-preallocation/allocate` 返回 404。

请求方是上游炉次计划系统或测试客户端。它提交已经安排好的炉次计划以及当时的钢包、行车和位置快照；本接口只执行配包，不重新编排炉次计划。正常预配包使用决策树，LLM 配置只服务于独立的扰动 Workflow。

## Goals / Non-Goals

**Goals:**

- 增加与 OpenAPI 文档一致的 `POST /api/v1/ladle-preallocation/allocate` 路由。
- 将 JSON 输入转换成现有决策树所需的标准化 `heats`、`ladles`、`cranes`。
- 复用 `allocate` 和 `validate_output`，保证 API 结果与离线预配结果使用同一套硬约束。
- 返回稳定的逐炉次结果、汇总指标和审计摘要，并区分完整成功、部分结果和人工复核。
- 保持现有场景 API 和扰动 LLM Workflow 的兼容性。

**Non-Goals:**

- 不在本变更中实现新的炉次计划编排算法。
- 不把 LLM 引入正常预配包路径。
- 不把 API 密钥放入请求、响应、日志或审计文件。
- 不改变现有离线 SQLite 场景库的 schema。

## Decisions

### 1. 复用标准库服务并增加路由分支

在现有 `DemoHandler.do_POST` 中增加目标路径分支，并把业务处理抽到可单测的纯函数。这样不需要引入 FastAPI 或新的运行时，现有服务启动命令、静态页面和场景 API 保持不变。

备选方案是迁移到 FastAPI 并让框架生成 Swagger UI。该方案更适合长期生产化，但会引入依赖、改变启动方式，并超出本次把既有决策树暴露为接口的范围。

### 2. API 层负责适配，不修改决策树输入契约

API 层校验字段、解析 ISO 8601 时间、规范化状态和数值，然后构造决策树内部对象。决策树和现有 validator 继续作为分配和硬约束的唯一执行来源，避免 API 路径复制评分或校验逻辑。

### 3. 输出采用逐炉次结果加汇总审计

响应包含 `results`、`metrics` 和 `audit` 三部分。`results` 对每个输入炉次返回 `assigned`、`unassigned`、`manual_review` 或 `excluded`；`metrics` 保留成功率和规则违反数；`audit` 保留输入来源、排除数量、算法版本和必要的生命周期摘要，但不保存密钥。

### 4. 错误按请求层和业务层区分

- JSON 无法解析、缺少必填字段或类型错误返回 `400`。
- 资源编号重复、位置映射冲突或快照互相矛盾返回 `409`。
- 请求可解析但无法为全部炉次生成可行方案时返回 `422`，响应仍保留逐炉次结果和人工复核原因。
- 完整处理返回 `200`，由响应 `status` 表示 `completed`、`partial` 或 `manual_review`。

### 5. LLM 配置保持进程环境边界

`.env.local` 只通过 shell `source` 导出 `LLM_API_KEY`、`LLM_API_BASE` 和 `LLM_MODEL`。正常预配包接口不读取或调用 LLM；扰动接口继续使用同一配置加载器。真实 `.env.local` 继续被 Git 忽略。

## Risks / Trade-offs

- [Risk] API 输入时间和单位与真实 PLAN/CRANE 数据不一致，导致结果偏差 → 在请求校验中强制 RFC 3339 时间、吨位和米制字段，并在审计中记录标准化假设。
- [Risk] 请求包含重复炉次或资源编号，可能破坏分配唯一性 → 在调用决策树前拒绝重复主键和重复资源快照。
- [Risk] 输入资源池为空或约束过严时无法完整分配 → 返回 `422` 和逐炉次失败原因，不伪造成功。
- [Risk] API 响应字段与 Swagger 文档再次漂移 → 为成功、部分失败、非法输入和资源冲突增加契约测试，并在 CI 中解析 OpenAPI YAML。
- [Risk] 直接在标准库 handler 中增加业务逻辑会变得难测 → 业务转换和响应组装使用独立函数，handler 只负责读取 body、选择路由和写 HTTP 响应。

## Migration Plan

1. 增加请求适配、响应映射和路由测试。
2. 本地启动服务，使用 OpenAPI 示例 curl 验证 `200` 和 `422` 路径。
3. 保留旧接口并发布新版本路径；不需要迁移既有客户端。
4. 若新路由出现问题，停止使用 `/api/v1/ladle-preallocation/allocate` 即可回退；现有场景查询和 `/api/simulate` 不受影响。

## Open Questions

- 上游最终是否直接发送标准化 JSON，还是需要服务端继续接收 PLAN/CRANE Excel 文件并转换？本变更按标准化 JSON 设计，Excel 读取仍由离线 pipeline 负责。
- 生产环境是否需要鉴权、限流和请求幂等存储？这些属于部署层能力，本变更只保留 `request_id` 作为审计和幂等扩展字段。
