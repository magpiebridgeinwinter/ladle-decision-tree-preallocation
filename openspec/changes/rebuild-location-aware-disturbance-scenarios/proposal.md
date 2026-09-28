## Why

当前 20 类扰动基准中，第 1 类使用真实 31 炉窗口，而其余 19 类仍使用固定的两炉压力夹具；图集中的邻近炉次因此只是上下文，没有真正进入 AQ 决策树和 AR Codex 求解。这样无法证明不同扰动下局部重排范围和两条线路的真实效果。

本变更将统一使用真实 PLAN(1)、CRANE 和 loc_location 数据计算每类扰动的局部影响窗口，确保实验结果、审计记录和图集表达一致。

## What Changes

- 从 PLAN(1) 读取炉次顺序、计划时间、浇次时间、钢包和精炼路线。
- 从 CRANE 读取行车在线状态、位置、速度、载荷和作业边界。
- 从 loc_location 读取并校验炉次、钢包、行车和工艺位置映射。
- 按第一类真实窗口的归一化时间轴和扰动恢复窗口，动态计算每类场景的受影响炉次；不再固定为 2、20 或 31 炉。
- 将同一动态影响窗口分别提交给 AQ 决策树和 AR Codex，二者共享 AP 基线、位置数据和硬约束，但不互相读取对方结果。
- 记录每类场景的影响范围、位置约束、两条线路的逐炉分配、校验结果、Codex 调用元数据和推荐线路。
- 重建 20 类场景图集：窗口内炉次全部按 AQ/AR 结果着色，窗口外炉次仅作为蓝色上下文展示。
- 保留离线 Codex 审计边界；离线复现结果不得声明为外部 API 已调用。

## Capabilities

### New Capabilities

- `location-aware-disturbance-benchmark`: 基于 PLAN(1)、CRANE 和 loc_location 动态计算扰动影响窗口，并完成 AQ/AR 双线路审计。
- `disturbance-scenario-gallery`: 展示 20 类动态影响窗口及逐炉双线路结果，区分上下文炉次、相同结果、差异、决策树失败和 Codex 补全。

### Modified Capabilities

- None

## Impact

- `ladle_preallocation/offline_scenarios/builder.py` 和相关扰动范围逻辑。
- `ladle_preallocation/evaluation/benchmark.py` 的场景输入、结果契约和统计口径。
- 真实数据读取、位置映射和位置约束校验链路。
- `tools/build_disturbance_solution_benchmark.py`、场景图集生成器及其输出文件。
- 现有基准测试需要从“19 个两炉固定夹具”更新为“数据驱动的动态窗口”，主场景 31 炉结果必须保持不变。
