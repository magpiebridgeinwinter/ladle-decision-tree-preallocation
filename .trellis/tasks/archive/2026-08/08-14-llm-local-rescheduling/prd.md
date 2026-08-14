# LLM 局部重调度

## Goal

在既有决策树预配包基础上，为生产扰动提供可审计的局部重调度闭环。系统必须先尝试决策树重排；只有在非紧急场景且决策树失败时，才调用 LLM 作为兜底。目标是减少 Frozen 和人工介入，同时不放宽既有硬约束。

## Background And Confirmed Facts

- 工作分支为 `feature-1.0`，从 `feature` 分出；现有提交 `2ccbbb5` 已新增扰动注入、分级响应、ReAct、批量实验和本地 RAG 的初版模块。
- 真实数据入口 `ladle_preallocation/real_data/pipeline.py` 仍以全量炉次回放执行，不维护已吹炼、已预配或未预配状态。
- `ladle_preallocation/response/controller.py` 已实现“决策树优先，紧急失败 Frozen，非紧急失败再调用 LLM”的基础路径；紧急判定当前直接以受影响炉次的 `window_end <= 90` 计算，未使用显式当前时间和剩余预算。
- `ladle_preallocation/llm/react_agent.py` 已有约束反馈循环，但轮数为固定 `max_rounds`，未按 `earliest_pour - now - 90s` 预算停止或分配单轮超时。
- `ladle_preallocation/experiment/batch_runner.py` 只注入行车离线，汇总指标不覆盖业务 PRD 定义的完整三路指标。
- `README.md` 仍将项目描述为仅含决策树，与当前分支新增的重调度能力不一致。

## In Scope

### R1. Sliding-window Preallocation

- 将真实数据流程从一次性全量分配改为 180 分钟滚动预配。
- 为炉次维护三个互斥状态：`unallocated`、`preallocated`、`locked`。已吹炼的炉次锁定，已预配但未吹炼的炉次可被扰动重新计算。
- 扰动只影响可重调度的局部范围；锁定炉次及其既有分配不得被重写。
- 输出审计记录必须可追溯每个炉次的状态、批次/时间窗以及分配变更。

### R2. Time-budgeted Tiered Response

- 以事件时刻和受影响炉次最早开浇时刻计算剩余预算：`earliest_pour - now - 90s`。
- 预算不大于零时：仅执行决策树快速重排；失败后返回 Frozen 与人工复核信号，不调用 LLM。
- 预算大于零时：先执行决策树；失败后运行 LLM ReAct，且每轮调用与总循环均不得超过剩余预算。
- 所有 LLM 输出必须继续通过现有硬约束校验；不得以 LLM 成功标记绕过校验。

### R3. LLM ReAct Contract

- 将决策树失败原因、受影响炉次、可用钢包、可用行车和格式化约束反馈传入 LLM。
- 接受结构化 `{heat_id, ladle_id, crane_id}` 映射；意图级输出仅能转换为同一受校验的候选映射后执行。
- 使用可配置的 OpenAI-compatible DeepSeek 接口；密钥不得写入代码、报告或审计文件。
- 默认模型值与业务 PRD 一致，并允许命令行或配置覆盖。

### R4. Disturbance And Experiment Coverage

- Demo 版本支持单一扰动和可复现随机时间点，至少涵盖行车不可用、钢包不可用、设施不可用和计划偏差四类事件的表示与影响范围处理。
- 批量实验必须对每个场景输出 Frozen、决策树和 LLM 三条路径，并保留事件、时间点、受影响炉次和决策路径。
- LLM 只在决策树失败的非紧急场景计入实际生产路径；为评估可单独配置强制运行实验分支，但不得改变生产路径语义。

### R5. Metrics, Reporting, And Documentation

- 三路报告按路径输出：`on_time_rate`、`priority_on_time`、`average_delay_seconds`、`max_delay_seconds`、`changed_heats`、`human_review_rate`、`rule_violations`、`decision_seconds`。
- 在决策树失败且 LLM 实际尝试的样本上计算 `dtree_fail_llm_success_rate`；在同一集合上计算 `frozen_avoidance_rate`。没有适用样本时必须明确报告为 N/A，而非伪造 0%。
- 更新 README，说明决策树仍是主路径、LLM 仅为非紧急兜底，列出 Demo 和真实数据入口。

### R6. Verification

- 为新增的时间预算、状态转换、锁定保护、四类扰动、LLM 超时/失败和指标公式补充确定性测试。
- 完整测试套件必须可通过项目声明的依赖安装命令运行。

## Out Of Scope

- 真实生产控制系统下发、排产平台集成或替代现场人工审批。
- 组合扰动、多站点资源优化和真实异常日志建模。
- 企业调度经验文档尚未提供前的生产级 RAG 摄取与检索质量评估。
- 以 LLM 替换决策树，或放宽安全、载重、运行区间、时间窗等硬约束。

## Acceptance Criteria

- [x] AC1: 给定真实 PLAN/CRANE 回放与固定事件时间，滑窗运行产生互斥的 `unallocated`、`preallocated`、`locked` 状态，并且锁定炉次不被后续扰动改写。
- [x] AC2: 当剩余预算小于或等于零且决策树无法分配时，结果为 Frozen + 人工复核，且 LLM 调用桩未被调用。
- [x] AC3: 当剩余预算大于零且决策树失败时，LLM 循环在预算内运行；任何非法、缺失或超时方案都不能成为有效分配。
- [x] AC4: 四种单一扰动均能构造可审计场景，随机实验在固定 seed 下可复现事件类型、时间点和结果。
- [x] AC5: 每份三路实验结果均包含 R5 全部指标；核心 LLM 指标只在适用分母存在时给出数值，否则标记 N/A。
- [x] AC6: README 与运行入口一致，说明决策树主路径、LLM 触发边界、必要输入和不含密钥的运行方式。
- [x] AC7: `python -m pytest -q` 在按 `requirements.txt` 安装依赖后的干净环境通过；离线测试不得访问外部 LLM API。

## Key Decisions

- 安全阈值固定为 90 秒；预配触发窗口固定为转炉开吹前 180 分钟。
- Demo 阶段使用单类型扰动和随机时间点；组合扰动延后。
- LLM 是决策树失败后的补充，不是与决策树竞争的默认算法。
- 真实数据和 API 可用性不足时，测试使用可注入的 LLM 调用桩，不使用真实密钥。

## Risks And Deferred Items

- 现有 `window_end` 是相对时间。实现预算前必须在场景层明确事件时刻与开浇时刻的同一时间基准，避免把绝对截止时间误作剩余秒数。
- 目前没有真实扰动日志；事件频率和生产收益只能作为模拟实验结论。
- 企业规则资料到位前，本地知识库只作可选提示上下文，不能成为硬约束的唯一来源。

## Open Questions

无。现有业务 PRD 已明确产品边界；实施前须按设计中的时间语义完成代码层验证。
