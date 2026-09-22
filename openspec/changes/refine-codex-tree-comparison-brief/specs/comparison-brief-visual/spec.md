## ADDED Requirements

### Requirement: 双线路主图必须突出共同基线与独立求解

主图 MUST 以 AP 作为唯一共同基线，并清楚显示 AQ 决策树和 AR Codex 两条独立线路；主图 MUST 标明 Codex 不读取 AQ，且两条线路使用同一扰动窗口、资源快照和终检。

#### Scenario: 观众查看主流程
- **WHEN** 观众打开汇报主图
- **THEN** 可在 10 秒内识别 AP、AQ、AR 三者关系，并看到“决策树失败后 Codex 介入”的路径

#### Scenario: 验证线路独立性
- **WHEN** 观众查看 AQ 和 AR 的输入说明
- **THEN** 图中明确两条线路均从 AP 和同一事件窗口出发，且 Codex 不读取 AQ 分配结果

### Requirement: 主图节点与连接线不得发生视觉重叠

主图 MUST 使用不超过 9 个核心节点和 12 条连接线；连接线 MUST 使用正交或同轴路径；箭头标签 MUST 与线和节点保持可见间距；节点、标签和结果数字 MUST 在 16:9 截图中完整显示。

#### Scenario: 导出 16:9 截图
- **WHEN** 主图按 1600×900 导出为 PNG
- **THEN** 节点文字、箭头标签、结果条和图例均不重叠、不截断、不越界

#### Scenario: 图形规范检查
- **WHEN** 运行 diagram-design 的几何、无障碍和调色板检查
- **THEN** 主图通过检查，且 SVG 具有与文件 slug 匹配的 title/desc 无障碍标识

### Requirement: 主图文案必须服务于汇报结论

主图 MUST 只保留共同输入、扰动窗口、AQ、AR、统一终检和选择结果等关键文案；不得把 Frozen、20 类场景清单或长段背景说明放入主图主体。

#### Scenario: 首屏阅读
- **WHEN** 管理者只查看主图和结果条
- **THEN** 可读到 AQ `30/31`、AR `31/31`、改配 3 炉/保留 AP 28 炉和规则违反 0

#### Scenario: 读取实验边界
- **WHEN** 观众查看图下注释或报告说明
- **THEN** 可看到扰动是基于真实快照构造的受控压力输入，Codex 结果为离线审计结果
