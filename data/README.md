# 本地输入数据

此目录在本机包含两个公司生产数据文件，不上传 GitHub：

- `PLAN(1)_预配包输入.xlsx`
- `CRANE.xlsx`

运行时请保持上述文件名，或通过 `--plan-path` 和 `--crane-path` 指定其他路径。
# 数据说明

`desktop_data/` 保存本次调研使用的桌面数据文件与报告模板，来源为
`/Users/admin/Desktop/数据文件`。仓库远端为私有仓库；其中包含生产计划、天车
记录、位置映射和报告文档。

- `PLAN(1).xlsx`：原始炉次计划
- `CRANE.xlsx`：天车记录
- `loc_location.xlsx`：位置映射
- `PLAN_TAPPING_clean.xlsx`：清洗后的计划数据
- `*.docx`：调研报告、设计规格书和问题记录

根目录下的 `CRANE.xlsx` 与 `PLAN(1)_预配包输入.xlsx` 是程序运行所用的工作副本；
`desktop_data/` 是桌面原始文件的完整归档。
