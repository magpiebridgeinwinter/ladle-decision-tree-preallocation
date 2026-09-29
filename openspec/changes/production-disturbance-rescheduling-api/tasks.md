## 1. Domain Contracts And Persistence

- [x] 1.1 Add typed production disturbance, baseline, job, revision, snapshot and audit models with stable status/event enums.
- [x] 1.2 Add a SQLite repository with transactional tables for baselines, disturbance events, jobs, revisions and audit events.
- [x] 1.3 Implement idempotency lookup, baseline parent/version validation, JSON redaction and legal state-transition guards.

## 2. Versioned Normal Allocation Baseline

- [x] 2.1 Extend normal allocation response generation with `plan_version`, `snapshot_version` and `allocation_version` while preserving existing fields.
- [x] 2.2 Register a successful or partial allocation as an immutable baseline without persisting secrets or the complete request body.
- [x] 2.3 Add unit tests for stable version linkage, duplicate baseline rejection and legacy response compatibility.

## 3. Production Disturbance Workflow

- [x] 3.1 Validate disturbance envelopes, supported event types, current snapshots, freshness and event/resource consistency.
- [x] 3.2 Compute affected, locked and unchanged heats plus available resources and remaining safety budget from the baseline and snapshot.
- [x] 3.3 Adapt the bounded local context to the existing LLM Workflow and enforce deterministic coverage, lock, scope and hard-constraint validation.
- [x] 3.4 Persist workflow stages, candidate revisions, failure reasons and Frozen/manual-review degradation paths.

## 4. HTTP API And State Machine

- [x] 4.1 Add `POST /api/v1/ladle-preallocation/disturbances` with idempotent event creation and synchronous job execution response.
- [x] 4.2 Add job and revision query endpoints with audit-safe output.
- [x] 4.3 Add revision confirm/reject and publish endpoints with version revalidation and publish credentials.
- [x] 4.4 Return consistent `400`, `404`, `409`, `422`, `423` and `503` responses for malformed input, missing resources, conflicts and frozen states.

## 5. Contract Documentation And Verification

- [x] 5.1 Update OpenAPI and the Markdown interface document with production disturbance request, response, version and state-transition contracts.
- [x] 5.2 Add route, idempotency, stale-version, invalid-proposal, confirmation and publication tests.
- [x] 5.3 Run the full relevant test suite, OpenSpec validation and `git diff --check`; record any remaining deployment limitations.
