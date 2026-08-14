# Implementation Plan: LLM 局部重调度

## 1. Establish Shared Scheduling State

- [x] Add a lifecycle/state module with explicit state transitions and immutable audit snapshots.
- [x] Preserve backward-compatible full replay behavior in `run_pipeline`; introduce an explicit sliding-window execution path with a 180-minute default.
- [x] Add deterministic tests for entering the window, locking, reallocation and locked-assignment preservation.

## 2. Normalize Time And Disturbances

- [x] Extend disturbance events with `occurred_at` and represent all four PRD event kinds.
- [x] Calculate earliest pour and remaining budget using a single time basis.
- [x] Restrict impact scope to preallocated, non-locked heats and include exclusions in the audit trail.
- [x] Test each event type, fixed seed reproducibility and emergency boundaries at 90 seconds.

## 3. Enforce Budgeted Tiered Response

- [x] Update the controller to accept explicit budget context and retain decision-tree-first behavior.
- [x] Prevent LLM creation/calls for exhausted budgets; emit Frozen plus a machine-readable human-review signal after deterministic failure.
- [x] Update ReAct to use remaining total budget and per-round request timeout, while preserving hard-constraint validation and offline test injection.
- [x] Test emergency no-LLM, non-emergency LLM fallback, timeout, invalid JSON, partial proposal and hard-constraint rejection paths.

## 4. Complete Experiments And Metrics

- [x] Generate all supported single-event scenarios over reproducible event times.
- [x] Make the batch runner evaluate Frozen, deterministic and LLM results with common baseline inputs.
- [x] Add shared path metrics and the two LLM-specific metrics with N/A handling for empty denominators.
- [x] Produce JSON and Markdown reports from the same result structure and test their required fields.

## 5. Finish Integration

- [x] Wire optional RAG context into the LLM prompt without making it a validator dependency.
- [x] Update README and Demo flags to document the primary path, LLM boundary, API-key handling and both execution modes.
- [x] Add `pytest` to the development/test dependency path and run `python -m pytest -q` in a clean environment.
- [x] Run the real-data decision-tree regression, inspect generated audits, and compare compatibility-mode output before enabling sliding-window output by default.

## Validation Commands

```bash
python -m pytest -q
python -m ladle_preallocation.real_data.pipeline
python -m ladle_preallocation.demo --skip-llm --num-scenarios 10
```

The real-data commands require the configured PLAN and CRANE workbooks. Tests must use local fixtures and injected LLM responses only.

## Risky Areas And Rollback

- Time coordinates: reject mixed absolute/relative values at the scenario boundary; use the existing full replay path as rollback.
- LLM availability: missing key, HTTP failure or timeout must degrade to Frozen + review, never to unchecked assignments.
- Output compatibility: do not replace the decision-tree audit schema without a versioned compatibility path.
- Metrics: avoid treating a non-attempted LLM path as a failed LLM attempt.
