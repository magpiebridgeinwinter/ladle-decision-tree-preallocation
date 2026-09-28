## ADDED Requirements

### Requirement: Upstream heat plan is an input contract
预配包系统 MUST 将上游炉次计划作为输入，不得在预配包模块内隐式生成、改写或补造炉次计划。

#### Scenario: Load production inputs
- **WHEN** 系统启动正常预配包
- **THEN** 系统 MUST 从 PLAN 读取炉次、等级、路线、时间、优先级和已有钢包字段，并从 CRANE 与位置映射读取资源状态和坐标约束

### Requirement: Decision tree owns normal preallocation
正常预配包和 180 分钟滑窗预配 MUST 使用决策树完成钢包与行车候选分配，并保留锁定、预配和未预配生命周期。

#### Scenario: Preallocation succeeds
- **WHEN** 炉次进入预配窗口且存在通过约束的候选资源
- **THEN** 系统 MUST 输出炉次对应的钢包、行车、预计到达时间、等级匹配和决策路径

### Requirement: Preallocation output is auditable
预配包输出 MUST 包含逐炉结果、未纳入原因、位置映射统计、资源快照、约束假设、指标和标准化调度输入。

#### Scenario: Audit output
- **WHEN** 预配包运行完成
- **THEN** 系统 MUST 写出包含 `scheduling_inputs`、`assignments`、`assignment_rows`、`plan_output_rows` 和 `metrics` 的审计结果，并生成摘要文件

### Requirement: Disturbance consumes the preallocation snapshot
扰动 Workflow MUST 使用预配包快照和上游计划派生的局部场景作为输入，不能把 LLM 输出回写为新的上游炉次计划。

#### Scenario: Local disturbance snapshot
- **WHEN** 行车、钢包、设施或计划状态发生扰动
- **THEN** 系统 MUST 根据事件和预配基线计算受影响炉次、锁定排除炉次、剩余资源和剩余时间预算
