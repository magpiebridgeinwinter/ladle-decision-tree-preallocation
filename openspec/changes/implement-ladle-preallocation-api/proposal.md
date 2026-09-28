## Why

当前 OpenAPI 文档已经定义了正常预配包的请求和响应格式，但本地服务没有实现对应的 HTTP 路由。调用方只能使用扰动模拟接口，无法把上游炉次计划、钢包资源和行车快照提交给配包引擎并获得标准化结果。现在需要把已有决策树和审计输出接入一个稳定的 API 边界，形成可由上游系统直接调用、由 curl/Swagger UI 验证的完整链路。

## What Changes

- 新增 `POST /api/v1/ladle-preallocation/allocate` 正常预配包接口。
- 接收结构化的上游炉次计划、钢包资源、行车快照和位置映射输入。
- 将 API 输入适配为现有决策树内部数据结构，并复用现有硬约束终检。
- 返回逐炉次配包结果、汇总指标、输入来源和审计摘要。
- 对 JSON 格式错误、资源冲突和无完整可行方案返回结构化错误或部分结果。
- 保留现有 `GET /api/scenarios/*` 和 `POST /api/simulate` 扰动接口，不改变其路径和语义。
- 更新 API 文档、curl 示例、服务启动说明和接口测试。
- 统一使用 `.env.local` 经 `source` 注入的环境变量配置 LLM；正常预配包接口不调用 LLM。

## Capabilities

### New Capabilities

- `ladle-preallocation-api`: 为上游炉次计划提供正常预配包 HTTP 接口，定义请求输入、决策树执行、响应输出、错误语义和审计字段。

### Modified Capabilities

- 无

## Impact

- `tools/serve_visualization.py`：增加正常预配包路由和请求处理。
- `ladle_preallocation/real_data`、`ladle_preallocation/decision_tree`：复用输入标准化、分配和校验能力。
- `docs/ladle-preallocation-openapi.yaml`：从目标契约变为与实际路由一致的接口文档。
- `README.md`、`.env.local.example`：补充服务启动、配置和 curl 调用说明。
- `tests/`：增加请求校验、成功分配、部分失败、资源冲突和审计输出测试。
- 不新增外部 LLM 依赖；不修改上游炉次计划，不把 LLM 输出写回正常预配包结果。
