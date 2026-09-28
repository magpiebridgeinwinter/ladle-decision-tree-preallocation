# Directory Structure

## Runtime layout

The repository is a single Python project. The runtime package is `ladle_preallocation/`.
The parallel `backend/ladle_preallocation/` tree is a historical organization mirror; it is
not a second implementation target. New runtime code belongs in the root package unless a
migration task explicitly synchronizes both trees.

```text
ladle_preallocation/
├── data_modeling/       # input normalization and derived features
├── decision_tree/       # deterministic allocation, scoring, constraints, validation
├── disturbance/         # controlled disturbance catalog and injectors
├── evaluation/          # metrics and benchmark calculations
├── experiment/          # batch orchestration and reports
├── llm/                 # optional ReAct fallback and runtime configuration
├── offline_scenarios/   # SQLite evidence and read-only repository
├── rag/                 # knowledge retrieval used by the fallback workflow
├── real_data/           # PLAN/CRANE/location ingestion and lifecycle state
├── response/            # tiered disturbance controller and workflow state
├── preallocation_api.py # pure HTTP request adapter for normal preallocation
└── rules.py             # shared domain rules

tools/                   # CLI entry points, report builders, local HTTP server
tests/                   # unit, integration, API and contract tests
docs/                    # OpenAPI, product and implementation documentation
data/                    # local source workbooks and sample documents
outputs/                 # generated reports, SQLite and audit artifacts
```

## Module boundaries

- Domain logic must stay in the package and remain callable without an HTTP server.
- `tools/serve_visualization.py` owns HTTP routing and serialization only.
- `preallocation_api.py` owns public request validation and response mapping; it delegates allocation to the existing decision tree.
- `offline_scenarios/repository.py` is read-only at runtime. Database writes belong to builder scripts.
- Tests import public package functions rather than reaching into handler internals when possible.

## Naming

- Modules and functions use `snake_case`; classes use `PascalCase`; constants use `UPPER_SNAKE_CASE`.
- Public API schemas use `Input...` and `Output...` prefixes.
- IDs preserve upstream names (`heat_id`, `ladle_id`, `crane_id`, `scenario_id`); do not silently rename them at boundaries.
