# Offline Ladle Disturbance Scenario Backend

## Goal

Complete the backend evidence layer for an interactive steel-ladle scheduling
demo. The backend must expose only two scenario categories: ordinary
decision-tree local rescheduling and controlled severe disturbances where the
decision tree is incomplete and an LLM-authored proposal is used.

## Requirements

- Use the audited `PLAN(1)` and `CRANE` scheduling inputs as the source of heat,
  ladle, crane, route, position, load, and time identifiers.
- Keep exactly two top-level categories:
  `decision_tree_control` and `llm_fallback_stress`.
- Include one ordinary, local decision-tree control and a broad v1 catalog of
  equipment, ladle, process/facility, plan/timing, logistics/safety, telemetry,
  and compound disturbances.
- Every LLM stress result must prove that the decision tree was attempted
  first and was incomplete, the saved Codex proposal was invoked, the proposal
  was complete, and shared hard constraints plus scenario policy passed.
- Persist reproducible scenario inputs, events, assets, stage results,
  assignments, validations, and evidence metadata in an offline SQLite file.
- Expose read-only summary/list/detail endpoints for the later frontend while
  retaining the environment-keyed realtime LLM endpoint for unseen scenarios.
- Write a DewuClaw handoff document that defines database/API contracts,
  interaction expectations, visual cues, and evidence wording.

## Evidence Boundary

- The source audit is `outputs/real_data_validation/decision_tree_audit.json`,
  generated from `data/PLAN(1)_预配包输入.xlsx` and `data/CRANE.xlsx`.
- Real identifiers and snapshots are source evidence. Injected failures,
  compressed windows, route alternatives, and restricted candidate pools are
  controlled stress inputs, not production incident logs.
- Saved Codex proposals are offline, reviewed fixtures executed through the
  response-controller adapter. They must not be described as external API
  calls.
- The v1 disturbance catalog is the complete set supported by this demo, not a
  claim that every possible Baosteel operational incident has been observed in
  the supplied workbooks.

## Acceptance Criteria

- The generated database contains only the two allowed categories.
- Every stored scenario references real PLAN/CRANE source assets.
- Every `llm_fallback_stress` row has decision-tree failure, adapter invocation,
  LLM success, complete assignments, and passing validation records.
- The ordinary control has decision-tree success and no LLM attempt.
- Database rebuilds are deterministic apart from SQLite file-layout details;
  logical exports and summary counts are stable.
- API keys, prompts containing credentials, and secret environment values are
  absent from SQLite, JSON outputs, logs, and tests.
- Unit tests, Python compilation, database integrity checks, and `git diff
  --check` pass.
