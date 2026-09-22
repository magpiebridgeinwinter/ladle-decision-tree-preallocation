# 代码整理报告

- 项目: `/Users/admin/Desktop/钢包配包`
- 扫描文件: 59
- 检测语言: html, json, md, mjs, py, yaml
- 执行时间: (由调用方记录)

## 移动结果

- ✅ 成功移动: 45
- ⏭️ 跳过: 0
- ❌ 失败: 0

### 成功移动

| 原路径 | 新路径 | 分类 |
|--------|--------|------|
| `DEWUCLAW_FRONTEND_BRIEF.md` | `docs/DEWUCLAW_FRONTEND_BRIEF.md` | docs |
| `LLM局部重调度PRD.md` | `docs/LLM局部重调度PRD.md` | docs |
| `AGENTS.md` | `docs/AGENTS.md` | docs |
| `DEWUCLAW_FRONTEND_PROMPT.md` | `docs/DEWUCLAW_FRONTEND_PROMPT.md` | docs |
| `ladle_preallocation/__init__.py` | `backend/ladle_preallocation/__init__.py` | backend |
| `ladle_preallocation/rules.py` | `backend/ladle_preallocation/rules.py` | backend |
| `ladle_preallocation/demo.py` | `backend/ladle_preallocation/demo.py` | backend |
| `ladle_preallocation/offline_scenarios/__init__.py` | `backend/ladle_preallocation/offline_scenarios/__init__.py` | backend |
| `ladle_preallocation/offline_scenarios/builder.py` | `backend/ladle_preallocation/offline_scenarios/builder.py` | backend |
| `ladle_preallocation/offline_scenarios/repository.py` | `backend/ladle_preallocation/offline_scenarios/repository.py` | backend |
| `ladle_preallocation/offline_scenarios/validation.py` | `backend/ladle_preallocation/offline_scenarios/validation.py` | backend |
| `ladle_preallocation/llm/react_agent.py` | `backend/ladle_preallocation/llm/react_agent.py` | backend |
| `ladle_preallocation/llm/__init__.py` | `backend/ladle_preallocation/llm/__init__.py` | backend |
| `ladle_preallocation/llm/prompts.py` | `backend/ladle_preallocation/llm/prompts.py` | backend |
| `ladle_preallocation/response/controller.py` | `backend/ladle_preallocation/response/controller.py` | backend |
| `ladle_preallocation/response/__init__.py` | `backend/ladle_preallocation/response/__init__.py` | backend |
| `ladle_preallocation/disturbance/catalog.py` | `backend/ladle_preallocation/disturbance/catalog.py` | backend |
| `ladle_preallocation/disturbance/__init__.py` | `backend/ladle_preallocation/disturbance/__init__.py` | backend |
| `ladle_preallocation/disturbance/injector.py` | `backend/ladle_preallocation/disturbance/injector.py` | backend |
| `ladle_preallocation/real_data/__init__.py` | `backend/ladle_preallocation/real_data/__init__.py` | backend |
| `ladle_preallocation/real_data/reader.py` | `backend/ladle_preallocation/real_data/reader.py` | backend |
| `ladle_preallocation/real_data/lifecycle.py` | `backend/ladle_preallocation/real_data/lifecycle.py` | backend |
| `ladle_preallocation/real_data/pipeline.py` | `backend/ladle_preallocation/real_data/pipeline.py` | backend |
| `ladle_preallocation/real_data/scenario.py` | `backend/ladle_preallocation/real_data/scenario.py` | backend |
| `ladle_preallocation/real_data/xlsx_stream.py` | `backend/ladle_preallocation/real_data/xlsx_stream.py` | backend |
| `ladle_preallocation/decision_tree/config.py` | `backend/ladle_preallocation/decision_tree/config.py` | backend |
| `ladle_preallocation/decision_tree/scoring.py` | `backend/ladle_preallocation/decision_tree/scoring.py` | backend |
| `ladle_preallocation/decision_tree/__init__.py` | `backend/ladle_preallocation/decision_tree/__init__.py` | backend |
| `ladle_preallocation/decision_tree/constraints.py` | `backend/ladle_preallocation/decision_tree/constraints.py` | backend |
| `ladle_preallocation/decision_tree/allocator.py` | `backend/ladle_preallocation/decision_tree/allocator.py` | backend |
| `ladle_preallocation/decision_tree/validation.py` | `backend/ladle_preallocation/decision_tree/validation.py` | backend |
| `ladle_preallocation/data_modeling/grades.py` | `backend/ladle_preallocation/data_modeling/grades.py` | backend |
| `ladle_preallocation/data_modeling/alignment.py` | `backend/ladle_preallocation/data_modeling/alignment.py` | backend |
| `ladle_preallocation/data_modeling/__init__.py` | `backend/ladle_preallocation/data_modeling/__init__.py` | backend |
| `ladle_preallocation/data_modeling/features.py` | `backend/ladle_preallocation/data_modeling/features.py` | backend |
| `ladle_preallocation/data_modeling/positions.py` | `backend/ladle_preallocation/data_modeling/positions.py` | backend |
| `ladle_preallocation/data_modeling/assumptions.py` | `backend/ladle_preallocation/data_modeling/assumptions.py` | backend |
| `ladle_preallocation/rag/knowledge_base.py` | `backend/ladle_preallocation/rag/knowledge_base.py` | backend |
| `ladle_preallocation/rag/__init__.py` | `backend/ladle_preallocation/rag/__init__.py` | backend |
| `ladle_preallocation/evaluation/metrics.py` | `backend/ladle_preallocation/evaluation/metrics.py` | backend |
| `ladle_preallocation/experiment/batch_runner.py` | `backend/ladle_preallocation/experiment/batch_runner.py` | backend |
| `ladle_preallocation/experiment/__init__.py` | `backend/ladle_preallocation/experiment/__init__.py` | backend |
| `visualization/index.html` | `frontend/visualization/index.html` | frontend |
| `visualization/DEWUCLAW_HANDOFF.md` | `frontend/visualization/DEWUCLAW_HANDOFF.md` | frontend |
| `visualization/demo_catalog.json` | `frontend/visualization/demo_catalog.json` | frontend |

## .gitignore 更新

已追加以下条目:

- `# code-organizer: 生成产物/缓存目录`
- `outputs/`
- `dist/`
- `build/`
- `*.pyc`
- `venv/`
- `node_modules/`
- `.vscode/`

## ⚠️ Import 修正清单（需手动处理，脚本不自动修改）

以下引用可能因文件移动而断裂，请按建议手动修改：

| 文件 | 原引用 | 建议改为 |
|------|--------|---------|
| `tools/real_data_codex_stress_demo.py` | `ladle_preallocation.decision_tree.constraints` | `backend.ladle_preallocation.decision_tree.constraints` |
| `tools/real_data_codex_stress_demo.py` | `ladle_preallocation.decision_tree.validation` | `backend.ladle_preallocation.decision_tree.validation` |
| `tools/real_data_codex_stress_demo.py` | `ladle_preallocation.disturbance.injector` | `backend.ladle_preallocation.disturbance.injector` |
| `tools/real_data_codex_stress_demo.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `tools/build_offline_scenario_db.py` | `ladle_preallocation.offline_scenarios` | `backend.ladle_preallocation.offline_scenarios` |
| `tools/codex_llm_fallback_demo.py` | `ladle_preallocation.decision_tree` | `backend.ladle_preallocation.decision_tree` |
| `tools/codex_llm_fallback_demo.py` | `ladle_preallocation.disturbance` | `backend.ladle_preallocation.disturbance` |
| `tools/codex_llm_fallback_demo.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `tools/serve_visualization.py` | `ladle_preallocation.llm.react_agent` | `backend.ladle_preallocation.llm.react_agent` |
| `tools/serve_visualization.py` | `ladle_preallocation.offline_scenarios` | `backend.ladle_preallocation.offline_scenarios` |
| `tools/serve_visualization.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `tests/test_offline_scenarios.py` | `ladle_preallocation.disturbance.catalog` | `backend.ladle_preallocation.disturbance.catalog` |
| `tests/test_offline_scenarios.py` | `ladle_preallocation.offline_scenarios` | `backend.ladle_preallocation.offline_scenarios` |
| `tests/test_real_data.py` | `ladle_preallocation.real_data.pipeline` | `backend.ladle_preallocation.real_data.pipeline` |
| `tests/test_real_data.py` | `ladle_preallocation.real_data.xlsx_stream` | `backend.ladle_preallocation.real_data.xlsx_stream` |
| `tests/test_rescheduling_contracts.py` | `ladle_preallocation.disturbance` | `backend.ladle_preallocation.disturbance` |
| `tests/test_rescheduling_contracts.py` | `ladle_preallocation.real_data.lifecycle` | `backend.ladle_preallocation.real_data.lifecycle` |
| `tests/test_rescheduling_contracts.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `tests/test_decision_tree.py` | `ladle_preallocation.decision_tree` | `backend.ladle_preallocation.decision_tree` |
| `tests/test_rescheduling.py` | `ladle_preallocation.disturbance` | `backend.ladle_preallocation.disturbance` |
| `tests/test_rescheduling.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `tests/test_rescheduling.py` | `ladle_preallocation.llm` | `backend.ladle_preallocation.llm` |
| `tests/test_rescheduling.py` | `ladle_preallocation.experiment` | `backend.ladle_preallocation.experiment` |
| `tests/test_rescheduling.py` | `ladle_preallocation.rag` | `backend.ladle_preallocation.rag` |
| `tests/test_rescheduling.py` | `ladle_preallocation.llm.react_agent` | `backend.ladle_preallocation.llm.react_agent` |
| `tests/test_rescheduling.py` | `ladle_preallocation.llm.react_agent` | `backend.ladle_preallocation.llm.react_agent` |
| `tests/test_rescheduling.py` | `ladle_preallocation.llm.react_agent` | `backend.ladle_preallocation.llm.react_agent` |
| `tests/test_rescheduling.py` | `ladle_preallocation.rag.knowledge_base` | `backend.ladle_preallocation.rag.knowledge_base` |
| `backend/ladle_preallocation/rules.py` | `ladle_preallocation.data_modeling.grades` | `backend.ladle_preallocation.data_modeling.grades` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.decision_tree` | `backend.ladle_preallocation.decision_tree` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.decision_tree.config` | `backend.ladle_preallocation.decision_tree.config` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.disturbance` | `backend.ladle_preallocation.disturbance` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.llm` | `backend.ladle_preallocation.llm` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.experiment` | `backend.ladle_preallocation.experiment` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.rag` | `backend.ladle_preallocation.rag` |
| `backend/ladle_preallocation/demo.py` | `ladle_preallocation.real_data.pipeline` | `backend.ladle_preallocation.real_data.pipeline` |
| `backend/ladle_preallocation/offline_scenarios/__init__.py` | `ladle_preallocation.offline_scenarios.builder` | `backend.ladle_preallocation.offline_scenarios.builder` |
| `backend/ladle_preallocation/offline_scenarios/__init__.py` | `ladle_preallocation.offline_scenarios.repository` | `backend.ladle_preallocation.offline_scenarios.repository` |
| `backend/ladle_preallocation/offline_scenarios/builder.py` | `ladle_preallocation.decision_tree.constraints` | `backend.ladle_preallocation.decision_tree.constraints` |
| `backend/ladle_preallocation/offline_scenarios/builder.py` | `ladle_preallocation.disturbance.catalog` | `backend.ladle_preallocation.disturbance.catalog` |
| `backend/ladle_preallocation/offline_scenarios/builder.py` | `ladle_preallocation.disturbance.injector` | `backend.ladle_preallocation.disturbance.injector` |
| `backend/ladle_preallocation/offline_scenarios/builder.py` | `ladle_preallocation.offline_scenarios.validation` | `backend.ladle_preallocation.offline_scenarios.validation` |
| `backend/ladle_preallocation/offline_scenarios/builder.py` | `ladle_preallocation.response` | `backend.ladle_preallocation.response` |
| `backend/ladle_preallocation/offline_scenarios/repository.py` | `ladle_preallocation.disturbance.catalog` | `backend.ladle_preallocation.disturbance.catalog` |
| `backend/ladle_preallocation/offline_scenarios/validation.py` | `ladle_preallocation.decision_tree.validation` | `backend.ladle_preallocation.decision_tree.validation` |
| `backend/ladle_preallocation/llm/react_agent.py` | `ladle_preallocation.decision_tree.constraints` | `backend.ladle_preallocation.decision_tree.constraints` |
| `backend/ladle_preallocation/llm/react_agent.py` | `ladle_preallocation.rules` | `backend.ladle_preallocation.rules` |
| `backend/ladle_preallocation/llm/react_agent.py` | `ladle_preallocation.llm.prompts` | `backend.ladle_preallocation.llm.prompts` |
| `backend/ladle_preallocation/llm/__init__.py` | `ladle_preallocation.llm.react_agent` | `backend.ladle_preallocation.llm.react_agent` |
| `backend/ladle_preallocation/response/controller.py` | `ladle_preallocation.decision_tree.allocator` | `backend.ladle_preallocation.decision_tree.allocator` |
| `backend/ladle_preallocation/response/controller.py` | `ladle_preallocation.decision_tree.validation` | `backend.ladle_preallocation.decision_tree.validation` |
| `backend/ladle_preallocation/response/controller.py` | `ladle_preallocation.disturbance.injector` | `backend.ladle_preallocation.disturbance.injector` |
| `backend/ladle_preallocation/response/controller.py` | `ladle_preallocation.evaluation.metrics` | `backend.ladle_preallocation.evaluation.metrics` |
| `backend/ladle_preallocation/response/__init__.py` | `ladle_preallocation.response.controller` | `backend.ladle_preallocation.response.controller` |
| `backend/ladle_preallocation/disturbance/__init__.py` | `ladle_preallocation.disturbance.injector` | `backend.ladle_preallocation.disturbance.injector` |
| `backend/ladle_preallocation/disturbance/__init__.py` | `ladle_preallocation.disturbance.catalog` | `backend.ladle_preallocation.disturbance.catalog` |
| `backend/ladle_preallocation/disturbance/injector.py` | `ladle_preallocation.disturbance.catalog` | `backend.ladle_preallocation.disturbance.catalog` |
| `backend/ladle_preallocation/real_data/reader.py` | `ladle_preallocation.data_modeling.alignment` | `backend.ladle_preallocation.data_modeling.alignment` |
| `backend/ladle_preallocation/real_data/reader.py` | `ladle_preallocation.data_modeling.features` | `backend.ladle_preallocation.data_modeling.features` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.decision_tree` | `backend.ladle_preallocation.decision_tree` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.decision_tree.config` | `backend.ladle_preallocation.decision_tree.config` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.evaluation.metrics` | `backend.ladle_preallocation.evaluation.metrics` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.real_data.reader` | `backend.ladle_preallocation.real_data.reader` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.real_data.scenario` | `backend.ladle_preallocation.real_data.scenario` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.real_data.xlsx_stream` | `backend.ladle_preallocation.real_data.xlsx_stream` |
| `backend/ladle_preallocation/real_data/pipeline.py` | `ladle_preallocation.real_data.lifecycle` | `backend.ladle_preallocation.real_data.lifecycle` |
| `backend/ladle_preallocation/real_data/scenario.py` | `ladle_preallocation.data_modeling.features` | `backend.ladle_preallocation.data_modeling.features` |
| `backend/ladle_preallocation/real_data/scenario.py` | `ladle_preallocation.data_modeling.positions` | `backend.ladle_preallocation.data_modeling.positions` |
| `backend/ladle_preallocation/real_data/scenario.py` | `ladle_preallocation.data_modeling.assumptions` | `backend.ladle_preallocation.data_modeling.assumptions` |
| `backend/ladle_preallocation/real_data/scenario.py` | `ladle_preallocation.real_data.reader` | `backend.ladle_preallocation.real_data.reader` |
| `backend/ladle_preallocation/real_data/xlsx_stream.py` | `ladle_preallocation.data_modeling.alignment` | `backend.ladle_preallocation.data_modeling.alignment` |
| `backend/ladle_preallocation/real_data/xlsx_stream.py` | `ladle_preallocation.real_data.reader` | `backend.ladle_preallocation.real_data.reader` |
| `backend/ladle_preallocation/decision_tree/scoring.py` | `ladle_preallocation.data_modeling.grades` | `backend.ladle_preallocation.data_modeling.grades` |
| `backend/ladle_preallocation/decision_tree/scoring.py` | `ladle_preallocation.decision_tree.config` | `backend.ladle_preallocation.decision_tree.config` |
| `backend/ladle_preallocation/decision_tree/constraints.py` | `ladle_preallocation.data_modeling.assumptions` | `backend.ladle_preallocation.data_modeling.assumptions` |
| `backend/ladle_preallocation/decision_tree/constraints.py` | `ladle_preallocation.rules` | `backend.ladle_preallocation.rules` |
| `backend/ladle_preallocation/decision_tree/allocator.py` | `ladle_preallocation.data_modeling.grades` | `backend.ladle_preallocation.data_modeling.grades` |
| `backend/ladle_preallocation/decision_tree/allocator.py` | `ladle_preallocation.decision_tree.constraints` | `backend.ladle_preallocation.decision_tree.constraints` |
| `backend/ladle_preallocation/decision_tree/allocator.py` | `ladle_preallocation.decision_tree.scoring` | `backend.ladle_preallocation.decision_tree.scoring` |
| `backend/ladle_preallocation/decision_tree/allocator.py` | `ladle_preallocation.rules` | `backend.ladle_preallocation.rules` |
| `backend/ladle_preallocation/decision_tree/validation.py` | `ladle_preallocation.data_modeling.grades` | `backend.ladle_preallocation.data_modeling.grades` |
| `backend/ladle_preallocation/decision_tree/validation.py` | `ladle_preallocation.decision_tree.constraints` | `backend.ladle_preallocation.decision_tree.constraints` |
| `backend/ladle_preallocation/data_modeling/features.py` | `ladle_preallocation.data_modeling.assumptions` | `backend.ladle_preallocation.data_modeling.assumptions` |
| `backend/ladle_preallocation/rag/__init__.py` | `ladle_preallocation.rag.knowledge_base` | `backend.ladle_preallocation.rag.knowledge_base` |
| `backend/ladle_preallocation/experiment/batch_runner.py` | `ladle_preallocation.decision_tree.allocator` | `backend.ladle_preallocation.decision_tree.allocator` |
| `backend/ladle_preallocation/experiment/batch_runner.py` | `ladle_preallocation.decision_tree.validation` | `backend.ladle_preallocation.decision_tree.validation` |
| `backend/ladle_preallocation/experiment/batch_runner.py` | `ladle_preallocation.disturbance.injector` | `backend.ladle_preallocation.disturbance.injector` |
| `backend/ladle_preallocation/experiment/batch_runner.py` | `ladle_preallocation.response.controller` | `backend.ladle_preallocation.response.controller` |
| `backend/ladle_preallocation/experiment/__init__.py` | `ladle_preallocation.experiment.batch_runner` | `backend.ladle_preallocation.experiment.batch_runner` |

## 整理后目录树

```
backend/
  ladle_preallocation/
    data_modeling/
    decision_tree/
    disturbance/
    evaluation/
    experiment/
    llm/
    offline_scenarios/
    rag/
    real_data/
    response/
    __init__.py
    demo.py
    rules.py
data/
  CRANE.xlsx
  PLAN(1)_预配包输入.xlsx
  README.md
docs/
  AGENTS.md
  DEWUCLAW_FRONTEND_BRIEF.md
  DEWUCLAW_FRONTEND_PROMPT.md
  LLM局部重调度PRD.md
frontend/
  visualization/
    DEWUCLAW_HANDOFF.md
    demo_catalog.json
    index.html
ladle_preallocation/
  __pycache__/
    __init__.cpython-312.pyc
    rules.cpython-312.pyc
  data_modeling/
    __pycache__/
  decision_tree/
    __pycache__/
  disturbance/
    __pycache__/
  evaluation/
    __pycache__/
  experiment/
    __pycache__/
  llm/
    __pycache__/
  offline_scenarios/
    __pycache__/
  rag/
    __pycache__/
  real_data/
    __pycache__/
  response/
    __pycache__/
openspec/
  changes/
    archive/
  specs/
  config.yaml
outputs/
  codex_llm_fallback_demo/
    audit.json
    nature_style_report.md
    nature_style_report_zh.md
    report.md
  offline_scenarios/
    ladle_scenarios.sqlite3
    summary.json
  real_data_codex_stress_demo/
    audit.json
    report.md
  real_data_demo/
    decision_tree_audit.json
    result_summary.md
    three_way_comparison.json
    three_way_comparison.md
  real_data_sliding_window/
    decision_tree_audit.json
    result_summary.md
  real_data_validation/
    decision_tree_audit.json
    result_summary.md
    three_way_comparison.json
    three_way_comparison.md
  PLAN(1)_真实CRANE决策树配包结果.xlsx
  decision_tree_assignments.csv
  decision_tree_audit.json
  demo_catalog.json
  llm_local_rescheduling_validation_report.md
  result_summary.md
  three_way_comparison.json
  three_way_comparison.md
tests/
  __pycache__/
    test_decision_tree.cpython-312-pytest-9.1.1.pyc
    test_offline_scenarios.cpython-312-pytest-9.1.1.pyc
    test_real_data.cpython-312-pytest-9.1.1.pyc
    test_rescheduling.cpython-312-pytest-9.1.1.pyc
    test_rescheduling_contracts.cpython-312-pytest-9.1.1.pyc
    test_scenario_api.cpython-312-pytest-9.1.1.pyc
  test_decision_tree.py
  test_offline_scenarios.py
  test_real_data.py
  test_rescheduling.py
  test_rescheduling_contracts.py
  test_scenario_api.py
tools/
  __pycache__/
    codex_llm_fallback_demo.cpython-312.pyc
    real_data_codex_stress_demo.cpython-312.pyc
    serve_visualization.cpython-312.pyc
  build_demo_catalog.py
  build_offline_scenario_db.py
  build_outputs.mjs
  codex_llm_fallback_demo.py
  real_data_codex_stress_demo.py
  serve_visualization.py
README.md
requirements.txt
v5-desktop-full.png
v5-drawer.png
v5-ladle-damage.png
v5-mobile-full.png
v5-playing.png
```

## 建议后续操作

- 更新 README.md 中的目录说明
- 根据 import 修正清单手动修改引用
- 运行测试验证移动未破坏功能