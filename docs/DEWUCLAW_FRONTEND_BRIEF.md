# DewuClaw Frontend Brief: 钢包扰动重调度演示

## 先读结论

前端只展示两个一级场景，不要再出现 Frozen、人工、决策树、LLM
四列并排的旧结构：

1. `decision_tree_control`：普通局部扰动，决策树在二十分钟窗口内完成重排，不调用 LLM。
2. `llm_fallback_stress`：严重扰动，决策树先尝试但未完成当前局部窗口，随后加载已经审计保存的 Codex 方案并完成该窗口。主场景为 `30/31 -> 31/31`，双炉压力场景为 `0/2` 或 `1/2 -> 2/2`。

默认进入第二类，首屏必须让观众在十秒内看懂“大模型只在规则方法失败后介入，并且输出还要经过硬约束终检”。

## 后端已经完成的内容

- SQLite：`outputs/offline_scenarios/ladle_scenarios.sqlite3`
- 摘要：`outputs/offline_scenarios/summary.json`
- 生成命令：`python3 tools/build_offline_scenario_db.py`
- 本地服务：`python3 tools/serve_visualization.py --port 4173`
- 真实源审计：`outputs/real_data_location_aware/decision_tree_audit.json`
- 真实工作簿：`data/PLAN(1)_预配包输入.xlsx`、`data/CRANE.xlsx`

当前库有 `21` 个场景：普通决策树 `1` 个，LLM 压力场景 `20` 个。
压力场景全部满足：决策树先失败、Codex adapter 被调用、Codex 完成当前窗口、统一硬约束和场景约束通过、`external_api_called=false`。

## API

### 摘要

`GET /api/scenarios/summary`

返回场景总数、两类数量、扰动分组和已验证 LLM 回退数量。

### 列表

`GET /api/scenarios`

可选过滤：

`GET /api/scenarios?category=llm_fallback_stress`

列表已经包含标题、扰动类型、分组、视觉提示、事件时间和两阶段成功状态，可直接生成场景选择器。

### 详情

`GET /api/scenarios/{scenario_id}`

详情包含：

- `events`：完整事件时间线；
- `assets`：真实炉次、钢包、行车源记录；
- `responses.decision_tree`：决策树路径、分配和原因；
- `responses.llm`：Codex 路径、分配、备用路线和原因；
- `validations`：完整性、硬约束、场景策略的逐条结果；
- `audit.controlled_inputs`：实际进入调度器的受控输入；
- `audit.controlled_overrides`：事故前后字段变化；
- `audit.evidence_boundary`：必须展示或可点开的证据边界。

旧的 `POST /api/simulate` 保留给未来未收录场景实时请求。离线演示不要调用它；没有 `LLM_API_KEY` 时它会如实失败并转人工，不能伪造成功。

## 二十类 LLM 压力场景

| 分组 | 扰动 | `visual_cue` | 后端实际改变 |
| --- | --- | --- | --- |
| 设备 | 行车突然离线 | `crane_power_off` | 原行车从候选集中移除 |
| 设备 | 行车速度下降 | `crane_slow` | 真实行车 1520 速度降为受控值 |
| 设备 | 行车限载 | `crane_load_alarm` | 真实行车 1520 最大载荷降为 120 t |
| 设备 | 行车作业范围受限 | `crane_range_block` | 真实行车 1520 可达边界收窄 |
| 物流安全 | 运输通道封锁 | `safety_barrier` | 行车活动位置触发安全距离冲突 |
| 钢包 | 钢包临时不可用 | `ladle_maintenance` | 原钢包 ST08 标记 unavailable |
| 钢包 | 钢包损坏 | `ladle_damage` | 原钢包 ST08 标记 scrapped |
| 钢包 | 钢包内衬报警 | `lining_temperature_alarm` | ST08 进入 maintenance 且记录内衬报警 |
| 钢包 | 钢包超龄 | `ladle_clock_alarm` | ST08 年龄超过受控上限并强制校验 |
| 钢包 | 钢包等级冲突 | `grade_conflict` | ST08 等级被受控改为冲突值 |
| 工艺设施 | 精炼设施停机 | `facility_offline` | A2 被封锁，Codex 为炉次选择允许的 A1 |
| 工艺设施 | 氩站不可用 | `argon_station_alarm` | R0 被封锁，Codex 为炉次选择允许的 R1 |
| 工艺设施 | 精炼路径临时变更 | `route_switch` | 两个炉次都必须提交新的允许路线 |
| 计划时序 | 生产计划偏差 | `timeline_shift` | 局部窗口整体偏移 120 秒 |
| 计划时序 | 转炉延迟 | `converter_delay` | 紧窗口炉次整体延迟 240 秒 |
| 计划时序 | 连铸机延迟 | `caster_delay` | 目标炉次开浇与窗口终点延迟 180 秒 |
| 计划时序 | 紧急炉次插入 | `urgent_heat` | 真实炉次标记紧急插入，优先级升为 100 |
| 计划时序 | 炉次优先级提升 | `priority_up` | 真实炉次优先级升为 50 |
| 数据控制 | 行车遥测陈旧 | `telemetry_warning` | 原陈旧快照被排除，只使用新鲜候选快照 |
| 复合 | 多资源复合扰动 | `compound_alarm` | 行车、钢包和路线约束同时生效 |

这是“本演示 v1 完整支持目录”，不是声称工作簿记录了宝钢历史上的每一次真实事故。事故是受控注入，资产编号和快照来自真实数据。

## 必须实现的主体验

### 1. 一个全局生产时间条

主时间条固定表现 `10:00-20:00`，但事件位置由详情中的 `events.offset_seconds` 驱动。需要有播放、暂停、上一步、下一步、复位和拖动。不要让播放停在 LLM 结果处，验证、下发、恢复生产和计划结束都必须继续推进。

事件顺序固定为：

`预配完成 -> 扰动发生 -> 打开二十分钟局部窗口 -> 决策树完成 -> LLM 上下文 -> Codex 方案 -> 硬约束终检 -> 调度下发`

普通场景没有 LLM 三步，决策树成功后直接下发。

### 2. 事故动画必须按类型变化

不要所有场景都画火苗。按照 `visual_cue` 做独立表现：行车离线是断电和停止；降速是运动速度下降；限载是载荷报警；范围受限和通道封锁是轨道禁区；钢包损坏是包体裂纹与隔离；内衬报警是包内高温警示；超龄是时钟；设施停机是站点熄灭；路线切换是路径改线；转炉和连铸延迟是对应工位时钟；遥测陈旧是信号断续；复合扰动同时叠加三种信号。

动画只说明状态，不代替文字证据。事故发生时同步突出受影响真实资源和二十分钟局部窗口。

### 3. 大模型作用必须成为视觉主线

LLM 场景中用一条清晰的四阶段链：

`决策树未完成当前窗口 -> 组装局部上下文 -> Codex 完成当前窗口 -> 硬约束全部通过`

点击每一阶段显示真实记录：

- 决策树为什么失败，看 `responses.decision_tree.assignments[].violations/reason`；
- Codex 改了什么，看 `responses.llm.assignments`；
- 为什么能下发，看 `validations.llm`；
- 真实数据来自哪里，看 `assets[].source_record`。

不要使用“AI 自动接管生产”之类表述。正确表述是“生成候选重排方案，经同一硬约束终检后下发”。

### 4. 真实实验结果必须可比较

首屏或主结果区只保留三个大数字：

- 决策树完成数；
- Codex 完成数；
- 硬约束通过数。

普通场景显示“窗口炉次全部完成 -> 未调用 LLM”。20 个压力场景中，15 个决策树完成 `1/2`，4 个完成 `0/2`，主行车离线场景完成 `30/31`；Codex 均完成对应窗口。不要把 20 次受控实验包装成 20 次生产事故。

### 5. 真实数据查看器

炉次 `AQ0640E1-300703`、`DU3851D1-300667`，替代钢包 `ST07`、`ST38`，原钢包 `ST08`，原行车 `1520`，候选行车 `2500`、`3170` 都来自源审计。点击资源后用紧凑抽屉展示源字段、事故后字段和差异，不要在主界面铺大段 JSON。

## 页面结构建议

顶部是紧凑控制栏和两段式场景切换；主体左侧为生产工序动画与全局时间条，右侧为四阶段决策链和三个核心结果；底部用可折叠区域承载真实数据、逐炉分配和审计证据。不要套娃卡片，不要大段说明文字，不要让 20 个场景同时占满页面。

场景选择器按七个 `disturbance_group` 分组，默认只展示名称和状态图标，搜索或下拉选择。切换场景后从 `GET /api/scenarios/{id}` 重新加载完整详情并复位时间条。

## 禁止项

- 不得写“Codex 已调用外部 API”：离线库明确是 `external_api_called=false`。
- 不得写“真实事故记录”：真实的是资产和快照，事故是受控模拟。
- 不得把 H-FLEX、H-TIGHT、C0 等虚构标签重新放回界面。
- 不得隐藏决策树先尝试这一阶段。
- 不得把 LLM 输出绕过校验直接标记为可下发。
- 不得把 API key、Authorization header、prompt 或环境变量写到浏览器、日志或数据库。
- 不得继续旧页面的信息堆叠和四列对比布局。

## 验收清单

- 两个一级场景清晰，默认聚焦 LLM 压力场景。
- 20 类事故均可切换，动画和受影响资源与类型一致。
- 时间条能自动播放、暂停、前后步进、复位和拖动，并能走到 20:00。
- 每个压力场景可看到决策树未完成、Codex 完成对应窗口、验证通过和下发。
- 可点击查看真实炉次、钢包、行车、路线和事故前后差异。
- 普通场景不显示伪造的 LLM 调用。
- 桌面和移动端无重叠、无超出、无控制项跳动，浏览器控制台无错误。
