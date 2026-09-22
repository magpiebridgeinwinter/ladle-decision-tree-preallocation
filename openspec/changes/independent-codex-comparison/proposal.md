## Why

当前工作簿中的决策树重排和 Codex 重排没有严格共享同一位置映射基线，导致两条结果无法公平比较。需要让 `AQ` 和 `AR` 从同一个 `AP` 扰动前方案、同一个事故快照和同一套硬约束独立求解，并把逐炉次评价写入 Excel，直观展示哪条线路更好。

本次 Codex 方案由当前 Codex 直接生成，不配置外部 LLM API；生成请求、回答摘要和校验结果必须可审计。

## What Changes

- 以 `AP` 位置映射预配结果作为唯一扰动前基线。
- 建立决策树独立重排线路，结果写入 `AQ`。
- 建立当前 Codex 独立重排线路，结果写入 `AR`；Codex 不读取 `AQ` 结果。
- 保证两条线路使用同一个扰动事件、影响范围、可用钢包、可用行车、位置、时间窗和硬约束。
- 对两条线路分别执行完整性、等级、位置、行车、安全距离、时间窗和工艺路线校验。
- 在 `AS:AZ` 增加逐炉次评价列，包含校验状态、按时状态、是否改配、推荐方案和评价依据。
- 对非受影响炉次保持 `AQ:AR` 和 `AS:AZ` 为空，避免把未参与重排的炉次误认为比较样本。
- 保存场景级汇总指标，包括完成率、按时率、平均/最大延迟、约束违规数、改配炉次数和最终推荐。
- 保留 Codex 请求与回答的离线审计信息，不写入 API key 或 Authorization；本次不接入外部 API。

## Capabilities

### New Capabilities

- `independent-codex-comparison`: 基于同一位置映射扰动基线，独立执行决策树和当前 Codex 重排，并将评价结果写入 Excel。

### Modified Capabilities

无。

## Impact

- 修改真实数据压力场景构建和 Codex 方案生成逻辑。
- 修改 Excel 导出脚本，维护 `AP`、`AQ`、`AR` 并追加 `AS:AZ`。
- 复用现有 `TieredResponseController`、`ScenarioValidator` 和位置映射审计数据。
- 增加逐炉次和场景级比较结果的审计字段及测试。
- 不修改原始 `PLAN(1).xlsx`、`CRANE.xlsx`、`loc_location.xlsx`。
- 不配置、不请求外部 LLM 服务，不持久化任何凭据。
