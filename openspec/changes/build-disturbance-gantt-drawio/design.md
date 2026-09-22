## Context

当前真实压力场景 `real_window_1100_1120_codex_stress_001` 来自位置映射审计，包含 457 炉全量基线和 11:00–11:20 的 31 炉局部窗口。事故是 11:00 行车 `2500` 受控离线；决策树完成 30/31，Codex 完成 31/31，Codex 实际改配 3 炉。审计同时包含炉次窗口、钢包位置、天车分配和分支验证结果，但这些字段尚未转换为可视化的时间轴对象。

本变更只生成可编辑图形和图形数据，不把当前模型包装成真实 PLC 运动仿真。现有 `expected_arrival_seconds` 与计划窗口可以表达调度时序；没有取包点、落包点、任务持续时间和实测坐标时，图中“天车”只表示计划转运任务的资源分配。

## Goals / Non-Goals

**Goals:**

- 由场景审计生成稳定、可追溯的甘特图数据模型。
- 生成可由 draw.io 打开的未压缩 `.drawio` 源文件，便于后续人工编辑。
- 用总览时间轴展示事故时刻、局部窗口、受影响炉次和两条响应线路。
- 用局部明细展示炉次、AP 原计划钢包、AQ 决策树结果、AR Codex 结果和天车字段的对应关系。
- 对 31 个受影响炉次支持点击/定位式审计：每个图形元素包含场景 ID、炉次号、方案分支等元数据。
- 对真实数据、受控压力输入和模型假设做清晰区分。

**Non-Goals:**

- 不新增或修改预配包、决策树、Codex 求解逻辑。
- 不将钢包位置 `POS_X` 推断为完整三维位置，也不绘制未经数据支持的吊钩高度、桥架 Y 或连续运动曲线。
- 不把 `11:00 行车 2500 离线`表述为生产事故日志；图中必须标注“受控压力场景”。
- 不在同一页同时展示 457 炉的所有明细；全量数据通过 JSON/CSV 追溯，图中聚焦局部窗口。

## Decisions

### 1. 使用 Gantt + 局部流程双层结构

第一页采用 `diagram-design` 的 Gantt 规范展示行车离线前 31 个受影响炉次的 AP 原计划；第二页使用同一时间范围和炉次顺序展示离线后的最终重排结果。横轴取事故前一小时至全部受影响炉次结束后的整点，未受影响的 426 炉只保留一条上下文说明。

每行左侧显示炉次号、计划起止时间和钢包/行车，右侧彩色条显示完整计划窗口。离线后页叠加事故竖线、31 炉影响窗口和 Codex 改配标记；两页保持同一炉次颜色，方便逐行对照。

### 2. 建立中间图形数据契约

新增 `diagram_data.json`（或等价结构）包含：`scenario_id`、`source_audit`、`time_axis`、`event_marker`、`impact_window`、`heat_rows`、`branch_summary`、`assumptions`。每个 `heat_rows` 至少包含 `heat_id`、`plan_start`、`plan_end`、`baseline_ladle`、`baseline_crane`、`decision_tree_ladle`、`decision_tree_crane`、`codex_ladle`、`codex_crane`、`status`、`changed_by` 和 `validation_status`。

时间轴使用场景的 demo minute/相对秒字段；若源数据同时存在 epoch 时间，保留 `source_timestamp`，但不在图上混用两个时间坐标系。缺少真实取包/落包时间时，任务条命名为“计划窗口/响应阶段”，不得命名为“实际吊运”。

### 3. 图形元数据与 draw.io 格式

导出未压缩的 `mxfile` XML，页面命名固定为 `01-离线前受影响炉次`、`02-离线后受影响炉次`。每个与炉次相关的 `mxCell` 使用稳定 ID，并在 `value` 中保留短标签，在 `tooltip` 中保留来源字段摘要。长文本放入伴随 JSON，不堆入节点。

连线先绘制、节点后绘制；采用正交圆角连接、独立连接点和底部横向图例。强调色只用于事故和 Codex 介入/改配，决策树和未变更计划使用中性颜色，并用文字标签而非颜色单独表达状态。

### 4. 真实结果作为验收夹具

生成器默认读取 `outputs/real_data_codex_stress_demo/audit.json`，并验证：事故资源为 `2500`、窗口炉数为 31、决策树完成数为 30、Codex 完成数为 31、Codex 改配炉次包含 `DT0142D1-300759`、`DT0143D8-300767`、`DT0164D1-300776`。这些值只作为回归夹具，不写死到通用绘图逻辑。

### 5. 验证与交付

使用 `diagram-design` 提供的 `verify-drawio-import.py` 和 `test-verify-drawio-import.py` 检查 XML 可导入、页面可识别、关键文本存在；另用 Python 检查每个受影响炉次只出现一次、AP/AQ/AR 字段来源一致、事故时刻和局部窗口均在时间轴上。输出 `.drawio`、`diagram_data.json` 和简短 README。

## Risks / Trade-offs

- [Risk] 当前数据缺少真实吊运起止点和连续运动 → [Mitigation] 使用“计划服务/转运任务”标签，并在图例中明确模型边界；后续接入 PLC 后再增加运动层。
- [Risk] 31 炉逐项展示会导致 draw.io 页面拥挤 → [Mitigation] 总览页聚合，明细页保留代表性节点和可追溯 ID，完整逐炉数据放 JSON/CSV。
- [Risk] 相对秒和 epoch 时间混用造成误读 → [Mitigation] 统一图上时间坐标为 demo minute，原始时间戳只放 tooltip/数据文件。
- [Risk] draw.io 手工编辑后破坏稳定 ID → [Mitigation] 生成文件带版本和数据来源，回归校验只依赖关键 ID 前缀与数据文件，不依赖布局坐标。

## Migration Plan

1. 新增审计到图形数据的转换器和 draw.io 导出器。
2. 用真实压力场景生成并校验三页图。
3. 将 `.drawio` 与 JSON 放入 outputs 的可追溯目录，前端或汇报材料按需引用。
4. 若后续接入更多扰动类型，沿用同一数据契约增加场景，不修改既有页面命名和元素 ID 规则。

## Open Questions

- 若要绘制真实“取包点→目标炉位→落包点”的天车运动甘特，需要补充钢包实际所在位置、目标工位和任务开始/结束时间；本变更暂不虚构这些字段。
