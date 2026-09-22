## Why

当前扰动演示使用的是未接入 `loc_location.xlsx` 的旧决策树基线，无法验证真实位置坐标对行车可行性、运输时间和局部重排结果的影响。需要把位置映射后的新预配结果正式接入扰动响应链路，保证事故发生时决策树和 LLM 都基于同一套真实位置、钢包和行车状态进行处理，并延续既有的“决策树优先、LLM 兜底、失败则 Frozen/人工”的逻辑。

## What Changes

- 以位置映射后的决策树全量预配结果作为扰动前基线，不再使用未映射的旧 `AO` 结果作为新场景基线。
- 在真实 PLAN/CRANE/位置映射场景上注入现有支持的扰动类型，包括行车不可用、钢包不可用、设施不可用和计划偏差。
- 根据扰动资源、生产时间和生命周期计算局部影响范围；已执行/锁定炉次不得被重排，远期和已完成炉次不受影响。
- 对受影响且可重排的炉次先执行决策树局部重排。
- 决策树局部重排失败且剩余时间预算大于 90 秒安全阈值时，调用 LLM ReAct 进行局部重调度；LLM 输出必须通过完整性、位置、钢包、行车、时间窗、安全距离和事件特定约束校验。
- 时间预算耗尽、LLM 调用失败或 LLM 方案校验失败时，保留 Frozen 结果并标记人工复核。
- 保存 Frozen、位置映射决策树、LLM 三路结果、变更炉次、影响范围、决策路径、验证反馈和时间预算审计。
- 生成可复现的离线扰动场景数据，保留实时 LLM 接口能力；离线 Codex 方案必须明确标记为审计夹具，不伪称为外部 API 请求。
- 更新结果工作簿或场景导出，使观测者能够区分位置映射基线、决策树重排和 LLM 最终方案。

## Capabilities

### New Capabilities

- `location-aware-disturbance-rescheduling`: 基于位置映射预配基线执行真实数据扰动、决策树局部重排、LLM 兜底和三路审计。

### Modified Capabilities

无。

## Impact

- 影响 `ladle_preallocation/disturbance`、`ladle_preallocation/response` 和 `ladle_preallocation/real_data` 的数据流与场景构建。
- 影响 `tools/real_data_codex_stress_demo.py`、离线场景构建和 SQLite/JSON 审计输出。
- 可能影响后端场景 API 的基线字段和响应结果字段，但不改变已有 API 密钥传入方式。
- 需要同时引用真实 `PLAN(1).xlsx`、`CRANE.xlsx`、`loc_location.xlsx` 和位置映射后的决策树审计。
- 不修改原始桌面数据，不将 API key、Authorization、prompt 中的凭据写入审计或离线数据库。
