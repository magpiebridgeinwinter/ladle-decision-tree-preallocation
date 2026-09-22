## Context

工作簿已经包含位置映射后的预配结果 `AP` 和扰动后的决策树结果 `AQ`，但 `AR` 仍可能来自另一套演示基线，无法形成可解释的 A/B 对比。本变更只服务于离线实验展示：决策树和当前 Codex 分别处理同一位置映射基线、同一事故快照和同一局部影响范围，结果经过同一校验器后写入工作簿。

当前 Codex 不配置外部 API。系统通过与实时 LLM 兼容的请求/响应数据结构保存一次 Codex 决策；本次由当前 Codex 生成结构化重排方案，方案作为 `AR` 和审计证据的来源。

## Goals / Non-Goals

**Goals:**

- 以 `AP` 对应的位置映射审计 `assignments` 作为唯一扰动前基线。
- 独立生成 `AQ` 决策树线路和 `AR` Codex 线路，Codex 不读取 AQ 的分配结果。
- 保持同一事故、同一 31 炉局部窗口、同一可用资源和同一硬约束。
- 对每个受影响炉次写入 `AS:AZ` 的可读评价，并给出炉次级推荐。
- 保存场景级完成率、按时率、延迟、违规和改配数量，支持整体结论。
- 使用当前 Codex 的结构化回答作为离线 AR 输出，不要求 API key，不伪装为外部 API 调用。

**Non-Goals:**

- 不改变 `AQ` 决策树结果或原始 PLAN/CRANE/位置数据。
- 不建立生产环境自动调用当前聊天 Codex 的网络通道。
- 不在本变更中调优决策树权重或拟合工厂历史方案。
- 不把自然语言回答直接写入 AR；AR 必须是经校验的结构化分配结果。

## Decisions

### 1. AP is the only baseline

读取位置映射审计中的 `scheduling_inputs`、`assignments` 和 `location` 元数据。工作簿中的 AP 必须由同一审计生成；压力场景不得再调用另一套 balanced baseline。这样 AP、AQ、AR 的资源、位置和时间口径一致。

### 2. Two independent solve branches

```text
AP + event snapshot -> decision tree -> shared validator -> AQ
AP + event snapshot -> Codex proposal -> shared validator -> AR
```

两条线路共享事故事件、受影响炉次、冻结集合、剩余钢包、剩余行车和约束版本，但互不读取对方的分配结果。Codex 请求可以带有决策树失败状态用于审计，但独立实验模式不把 AQ 方案作为 Codex 候选输入。

### 3. Codex adapter contract

定义一个无凭据的 Codex proposal adapter，输入为结构化 scenario request，输出为完整 `assignments` 数组。当前 Codex 负责生成该数组；adapter 记录 request、response、provider=`Codex current interactive session` 和 `external_api_called=false`。返回结果必须经过现有场景校验器，失败则不写入可用 AR 结果。

### 4. Row-level evaluation contract

仅对 31 个受影响炉次填充 AS:AZ，其他行留空。字段定义如下：

| 列 | 含义 |
|---|---|
| AS | 决策树校验：`通过` 或 `失败｜原因` |
| AT | Codex 校验：`通过` 或 `失败｜原因` |
| AU | 决策树按时：`是`、`否`、`未分配` |
| AV | Codex 按时：`是`、`否`、`未分配` |
| AW | 决策树是否改配：相对 AP 的 `是`/`否` |
| AX | Codex 是否改配：相对 AP 的 `是`/`否` |
| AY | 推荐方案：`决策树`、`Codex`、`持平`、`人工复核` |
| AZ | 生成推荐的可读原因 |

推荐采用硬约束优先的字典序：合法性、完整配包、按时率、平均延迟、最大延迟、改配炉次数、行车负载均衡。两条线路均失败时推荐人工复核；一方失败时推荐另一方；全部指标相同才推荐持平。

### 5. Scenario-level summary

在工作簿中增加紧凑的“对比汇总”工作表，按决策树/Codex 两列展示 31 炉场景的完成数、完成率、按时率、平均延迟、最大延迟、硬约束违规数、改配炉次数和最终推荐。该汇总与 AS:AZ 使用同一份审计结果生成。

## Risks / Trade-offs

- [Risk] 当前 Codex 会话不是可由本地 Python 直接调用的推理 API → [Mitigation] 使用无凭据 adapter 保存当前 Codex 结构化回答；保留请求契约，未来可替换为真实服务。
- [Risk] Codex 方案受决策树结果影响而失去独立性 → [Mitigation] 独立模式不把 AQ 分配作为输入，只共享 AP 和事故快照。
- [Risk] AP 与压力场景基线再次产生口径差异 → [Mitigation] 构建时强制从位置映射审计恢复 AP assignments，并检查来源路径、算法版本和 heat_id 集合。
- [Risk] 文字结果过长影响 Excel 浏览 → [Mitigation] AQ/AR 只保留短格式；详细理由和校验明细保存在 JSON 审计，AS:AZ 使用有限枚举值。

## Migration Plan

1. 从位置映射审计重新构建 31 炉场景，使用 AP 作为两条线路共同基线。
2. 运行决策树线路生成 AQ，调用当前 Codex 生成 AR，并分别校验。
3. 重新导出工作簿，保留 AP/AQ，覆盖 AR 并追加 AS:AZ 和对比汇总工作表。
4. 校验原始列、AP、AQ 未被改变，确认 31 个炉次逐行匹配且无凭据落盘。

## Open Questions

- 当前没有需要阻塞实现的业务问题；Codex 离线回答由本次 Codex 会话直接生成。
