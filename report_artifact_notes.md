# 周报文档制作记录

## 参考模板

- 主模板：`/Users/admin/Desktop/数据文件/2026-9-22 钢包重排可视化展示.docx`
- 内容参考：`/Users/admin/Desktop/数据文件/2026-9-10 钢包重排评价指标调研进展.docx`、`/Users/admin/Desktop/数据文件/2026-9-1 评价体系初步建立.docx`
- 主模板 SHA-256：`6e32b64c5a16e6eef2a3dbbfa4097e3ebcb16ae2ddd95f12ab10afb20314377e`

## 版式约定

- A4 纵向，沿用主模板页边距和单 section 设置。
- 正文和表格统一使用宋体，标题使用主模板的普通标题段落，章节使用 Heading 1。
- 结构采用“本周结论—方案—结果—边界与下一步”，结论先行，表格承担主要信息。

## 数据约定

- 真实数据：`data/PLAN(1)_预配包输入.xlsx`、`data/CRANE.xlsx`、位置映射和此前位置感知审计产物。
- 受控输入：20 类扰动状态及窗口/路线约束。
- 输出：`outputs/disturbance_solution_benchmark/benchmark.json` 及其 CSV/XLSX。
- Codex 结果为离线审计候选方案，`external_api_called=false`，不表述为现场实时 API 调用。
