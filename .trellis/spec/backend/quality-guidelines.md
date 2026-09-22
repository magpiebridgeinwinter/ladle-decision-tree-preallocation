# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Scenario: Local Rescheduling Contracts

### 1. Scope / Trigger

- Trigger: a production disturbance crosses real-data normalization, lifecycle state, response control, LLM invocation, metrics, and reports.
- Keep scheduling time semantics in one coordinate system. `DisturbanceSpec.occurred_at` and heat `pour_at` are comparable seconds; do not compare an absolute timestamp to legacy `window_end` without normalization.

### 2. Signatures

```python
run_pipeline(..., sliding_window: bool = False, window_minutes: float = 180.0)
inject_disturbance(spec, heats, ladles, cranes, assignments, frozen_heat_ids=None, locked_heat_ids=None)
ReActRescheduler.reschedule(..., remaining_budget_seconds=None, failure_context=None, rag_context=None)
TieredResponseController(..., validator=validate_output)
```

`LifecycleManager` is the sole owner of `unallocated -> preallocated -> locked` transitions. A locked assignment must not be overwritten.

### 3. Contracts

- `DisturbanceSpec.kind` must exist in `disturbance.catalog.DISTURBANCE_KINDS`.
  The generic random injector intentionally transforms only its four legacy
  kinds; controlled v1 catalog events are built by `offline_scenarios.builder`
  with explicit before/after state deltas.
- LLM budget is `earliest_pour_at - occurred_at - 90`. A non-positive budget forbids LLM calls.
- An LLM assignment is successful only when it returns every affected heat exactly once and passes the controller's injected validator; the default is `validate_output`. An LLM success flag alone is insufficient.
- Facility and route disturbances must preserve the selected `refining_route`
  in merged assignments and validate it against explicit allowed/blocked route
  policy. A ladle/crane-only result cannot claim a facility outage was solved.
- Saved Codex fixtures are offline reviewed proposals with
  `external_api_called=false`; never describe them as external API requests.
- API keys are passed at runtime only and must not appear in prompts persisted to audit output, reports, or tests.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Locked heat appears in an event impact set | Exclude it from reallocation and retain the original assignment |
| Budget is exhausted after decision tree failure | Frozen result with `human_review_required=True`; do not invoke LLM |
| LLM omits, duplicates, or invents a heat/resource | Reject proposal and return LLM failure/Frozen |
| LLM timeout or transport error | Return failure without unchecked assignments |
| No LLM-eligible scenarios in an experiment | Report LLM core rates as `None`/N/A, not `0%` |
| Saved stress result lacks an event-state delta/route policy or source asset | Reject the offline build |
| Route proposal omits or selects a blocked route | Mark it unassigned in scenario validation |

### 5. Good / Base / Bad Cases

- Good: an event at `occurred_at=100` for a heat with `pour_at=300` has 110 seconds of LLM budget after the 90-second safety buffer.
- Base: a legacy fixture without `occurred_at` retains its relative `window_end <= 90` emergency behavior.
- Bad: treating `window_end` as "remaining seconds" when the event provides an absolute time coordinate.

### 6. Tests Required

- Lifecycle test: locking preserves the original assignment and audit record.
- Controller test: exhausted budget prevents an injected LLM callable from running.
- Disturbance test: each supported event kind produces an auditable impact scope.
- Offline catalog test: every v1 kind proves DT incomplete, Codex adapter called,
  LLM complete, and all final checks passing.
- Route test: alternate route survives controller merge and SQLite round-trip.
- ReAct test: invalid JSON, missing heat, duplicate heat, hard-constraint violation, timeout, and valid full proposal.
- Report test: all path metrics exist and LLM-specific rates are N/A without an eligible denominator.

### 7. Wrong vs Correct

#### Wrong

```python
if llm_result.success:
    return llm_result.assignments
```

#### Correct

```python
validated = validate_output(heats, ladles, cranes, llm_result.assignments)
success = complete_proposal and all(row["action"] == "assign" for row in validated)
```

## Scenario: Audited Window Replay

### 1. Scope / Trigger

Use this contract when a browser demo replays a real-data time window after a
controlled disturbance.

### 2. Signatures

```python
allocate(heats, ladles, cranes, weights=None) -> list[DecisionTreeAssignment]
```

`weights` is an optional, normalized scoring override used only when an audit
explicitly records the controlled replay strategy. The default production
scoring weights remain unchanged.

### 3. Contracts

- The source audit still contains the full eligible PLAN population (457 in the
  supplied snapshot); a window projection must retain the source heat IDs and
  real crane IDs.
- The primary 11:00-11:20 replay contains 31 heats. Its baseline assignments
  are generated before applying the outage and are persisted alongside the
  window inputs.
- A stress replay must persist decision-tree result, Codex result, changed
  assignments, adapter invocation metadata, and validation checks together.
- The browser catalog may expose Codex stress cards only; the ordinary control
  remains in SQLite evidence for comparison and invariant checks.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Window count changes from the audited 31 heats | Abort the replay build |
| Candidate append occurs outside the crane loop | Regression test must fail; every feasible crane must be scored |
| Offline crane remains in the post-event pool | Abort the replay build |
| LLM result changes an unaffected window heat | Record the change and reject the “minimal local change” claim |

### 5. Good / Base / Bad Cases

- Good: baseline window resources are distributed across source-backed cranes;
  2500 outage yields DT 30/31 and Codex 31/31 with three changed heats.
- Base: a window heat remains mapped to the baseline resource and is shown as
  unchanged in the browser.
- Bad: all 31 dots or assignments are silently bound to one crane because only
  the last crane candidate was scored.

### 6. Tests Required

- Assert the primary offline `crane_offline` record has 31 inputs, DT 30/31,
  Codex 31/31, one offline crane, and no failed LLM validation checks.
- Assert the browser catalog has one Codex card, 31 affected heats, and three
  changed assignments.
- Assert the SQLite row and JSON catalog refer to the same primary scenario
  counts.

### 7. Wrong vs Correct

#### Wrong

```python
for crane in cranes:
    if feasible(heat, ladle, crane):
        pass
options.append(score(last_crane))
```

#### Correct

```python
for crane in cranes:
    if not feasible(heat, ladle, crane):
        continue
options.append(score_candidate(heat, ladle, crane, loads, pool, weights))
```

## Scenario: Audited Disturbance Diagram Projection

### 1. Scope / Trigger

Use this contract when an offline disturbance audit is projected into a draw.io
Gantt or process diagram. The projection is a reporting layer and MUST NOT
rerun or mutate the allocation algorithms.

### 2. Signatures

```text
build_diagram_data(audit: dict, source_path: Path) -> dict
write_outputs(data: dict, output_dir: Path) -> (drawio_path, json_path, readme_path)
```

### 3. Contracts

- Required source fields: `scenario_id`, `stress_audit.window.affected_heat_ids`,
  `stress_audit.event`, `baseline_full_assignments`, `decision_tree.assignments`,
  `codex_llm.assignments`, and `scenario_inputs.heats`.
- The output MUST include `scenario_id`, `source_audit`, `event_marker`,
  `impact_window`, `branch_summary`, `heat_rows`, and `assumptions`.
- Every affected heat appears exactly once in `heat_rows` with AP, AQ, and AR
  assignment fields and a stable element key containing the scenario and heat ID.
- `炉次 -> 钢包` means ladle preallocation; `转运任务 -> 天车` means crane
  dispatch. Without pickup/drop-off timestamps and telemetry, the diagram MUST
  say plan/scheduled state and MUST NOT claim measured crane motion.
- A normalized presentation axis and the source audit clock are separate
  contracts. Visible draw.io labels and tooltips MUST use only the normalized
  presentation axis; source timestamps remain in the semantic JSON for audit.
- When an incident is anchored to 11:00 on the presentation axis, preserve
  source durations and relative offsets by translating all displayed heat
  windows against the same incident timestamp. Never mix the source UTC date
  with the normalized 10:00-20:00 labels in one diagram.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Missing scenario/event/affected heat or branch assignments | Fail before creating the output directory |
| Duplicate affected heat or branch row | Fail with the duplicate heat ID |
| Branch result omits an affected heat | Fail with the branch and heat ID |
| Source changed-assignment list differs from derived AR changes | Fail with both lists |
| Output has unstable or duplicate heat element keys | Fail semantic validation |

### 5. Good / Base / Bad Cases

- Good: the 11:00-11:20 fixture emits 31 rows, event crane 2500, DT 30/31,
  Codex 31/31, and three Codex changes.
- Base: missing physical movement fields are preserved as absent and explained
  in `assumptions`.
- Bad: converting a plan `crane_id` into a continuous physical trajectory or
  silently dropping an unassigned decision-tree heat.

### 6. Tests Required

- Assert source-to-output counts, event resource, branch counts, changed heat
  IDs, stable keys, and both before/after draw.io page names.
- Assert the visible draw.io contains the normalized axis and no source-date
  strings, while semantic JSON retains the source timestamps.
- Assert malformed audits fail without a partial output directory.
- Run the diagram-design draw.io extractor on all pages and the repository's
  import verifier before delivery.

### 7. Wrong vs Correct

#### Wrong

```python
label = f"天车 {row['crane_id']} 已经移动到 {row['ladle_id']}"
```

#### Correct

```python
label = f"计划转运任务：{row['ladle_id']} / 行车 {row['crane_id']}"
```

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)
