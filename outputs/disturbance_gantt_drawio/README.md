# 扰动响应甘特图

- 场景：`real_window_1100_1120_codex_stress_001`
- 数据来源：`outputs/real_data_codex_stress_demo/audit.json`
- 全量计划来源：`outputs/real_data_location_aware/decision_tree_audit.json`
- 页面：`01-离线前受影响炉次`、`02-离线后受影响炉次`
- 只展开受影响炉次：`31`；其余 `426` 炉压缩为上下文说明。
- 语义：AP/AQ/AR 分别表示原计划、决策树重排和 Codex 重排；炉次到钢包是预配包，转运任务到天车是资源调度。
- 横轴：统一使用 10:00–20:00 演示生产时间；事故固定为 11:00，炉次持续时长与相对先后取自源数据。
- 时间审计：源 occurred_at 和源炉次时间保留在 diagram_data.json 与图形 tooltip，不与可见演示时间混用。
- 视觉区分：蓝色标签表示受扰动但保持计划；红色整行、粗框与 CODEX 改配标签表示模型改配。
- 边界：当前源数据没有取包点、落包点、任务持续时间或 PLC 连续坐标，因此图中天车不是实测运动轨迹。
