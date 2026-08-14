# Codebase Evidence Inventory

## Existing implementation

- `ladle_preallocation/real_data/pipeline.py` performs one full allocation at line 111 and writes decision-tree-only audit/report outputs at lines 169-220.
- `ladle_preallocation/disturbance/injector.py` supports crane-offline and ladle-unavailable resource removal at lines 124-133; the deadline is currently derived from `window_end` at lines 83-96.
- `ladle_preallocation/response/controller.py` already prefers deterministic allocation and routes emergency deterministic failure to Frozen at lines 233-299.
- `ladle_preallocation/llm/react_agent.py` runs a fixed `max_rounds` loop at line 249 and validates proposals before returning success at lines 295-331.
- `ladle_preallocation/experiment/batch_runner.py` injects only `crane_offline` at lines 171-187 and reports a narrow metric set at lines 65-84.
- `ladle_preallocation/evaluation/metrics.py` reports decision-tree metrics only.

## Verification baseline

- `python3 -m unittest discover -s tests -v` passes eight legacy tests, but cannot import `tests/test_rescheduling.py` because `pytest` is absent.
- `pytest` is not listed in `requirements.txt`.
- `README.md` claims the project does not include LLM rescheduling, despite the current branch adding it.

## Scope implication

The task is an integration and completion effort, not a greenfield ReAct implementation. The highest-risk contracts are shared time semantics, lifecycle state ownership, and the definition of LLM-specific metrics.
