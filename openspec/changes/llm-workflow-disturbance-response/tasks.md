## 1. Workflow Contract

- [x] 1.1 Add an explicit disturbance Workflow state/result model with stage names, configuration source, budget status, and structured failure reasons.
- [x] 1.2 Change the production disturbance controller to enter LLM ReAct directly, while retaining the decision-tree rerank method for explicit offline baseline calls.
- [x] 1.3 Preserve locked heats, impact scope, unaffected assignments, and Frozen/人工降级 behavior across successful and failed Workflow paths.

## 2. LLM Boundary And Validation

- [x] 2.1 Update LLM prompts and context construction so they describe direct disturbance handling rather than assuming a prior decision-tree failure.
- [x] 2.2 Add explicit runtime configuration loading for CLI and environment sources without loading or persisting `.env.local` implicitly.
- [x] 2.3 Ensure accepted proposals retain shared hard-constraint validation, complete coverage checks, and non-sensitive audit metadata.

## 3. Integration Outputs

- [x] 3.1 Update the realtime simulation endpoint and demo output to expose Workflow stage/path, configuration state, and downgrade reason.
- [x] 3.2 Keep preallocation audit fields and document the PLAN/CRANE/location input contract and preallocation output contract.
- [x] 3.3 Synchronize the maintained backend mirror where its public behavior duplicates the root package.

## 4. Verification

- [x] 4.1 Add tests proving a configured non-emergency disturbance calls LLM without first invoking decision-tree rerank.
- [x] 4.2 Add tests for budget exhaustion, missing API key, invalid/partial proposal, locked-heat protection, and unaffected-scope protection.
- [x] 4.3 Update existing three-way and demo tests for the separation between production Workflow and explicit decision-tree baseline.
- [x] 4.4 Run the focused test suite, full project `tests/` pytest collection, OpenSpec validation, and `git diff --check`.
