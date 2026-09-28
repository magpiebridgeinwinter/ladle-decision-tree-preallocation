## ADDED Requirements

### Requirement: Dynamic impact windows are derived from source data
The benchmark builder MUST derive each disturbance scenario's candidate and affected heat sets from the audited PLAN(1), CRANE, and `loc_location.xlsx` data, including source order, schedule fields, resource assignments, and location mapping. It MUST NOT use a fixed two-heat fixture for the catalog scenarios.

#### Scenario: A catalog scenario has a data-driven local window
- **WHEN** the builder creates a stress scenario for any disturbance kind
- **THEN** the audit records the candidate window, final affected heat IDs, excluded locked heat IDs, window bounds, and the source fields used to select them
- **AND** the final affected heat count is allowed to differ between scenarios

#### Scenario: The primary crane replay keeps its audited window
- **WHEN** the builder creates the primary `crane_offline` replay
- **THEN** it preserves the audited normalized 11:00 window and its 31 affected heats
- **AND** it preserves the source heat IDs and source-backed crane IDs

### Requirement: Location mapping and event state are auditable
The benchmark builder MUST validate and persist the location mapping status and every controlled event state delta used to alter a crane, ladle, route, facility, or heat.

#### Scenario: A mapped location is used for a candidate resource
- **WHEN** a heat or resource is selected through a location-aware constraint
- **THEN** the scenario audit includes the mapping key, mapped position, source file, and selection reason

#### Scenario: A required location is missing
- **WHEN** an event requires a location key that is absent or ambiguous in `loc_location.xlsx`
- **THEN** the builder MUST fail the affected scenario before writing benchmark output
- **AND** it MUST report the missing or ambiguous key

### Requirement: AQ and AR solve the same AP window independently
Each stress scenario MUST create one AP baseline for its affected heat set and pass equivalent source-backed heat, ladle, crane, route, and location inputs to AQ and AR. AR MUST NOT consume AQ assignments as its allocation input.

#### Scenario: Both branches receive the same affected heat set
- **WHEN** AQ and AR are evaluated for a scenario
- **THEN** their returned assignment keys are validated against the same affected heat ID set
- **AND** a branch missing, duplicating, or inventing a heat is rejected

#### Scenario: A window-outside heat is changed
- **WHEN** either branch changes an assignment outside `impact_scope.affected_heat_ids`
- **THEN** the branch fails the scope-preservation gate
- **AND** the scenario is not reported as a minimal local reschedule

### Requirement: Decision-tree failure is followed by validated Codex fallback
The builder MUST attempt AQ first and MUST only accept the offline Codex proposal after the same completeness, resource availability, route policy, location, and lock-preservation checks pass.

#### Scenario: Decision tree cannot complete a stress scenario
- **WHEN** AQ returns an incomplete or hard-constraint-invalid result and remaining budget permits fallback
- **THEN** the Codex adapter is invoked with the recorded failure context
- **AND** the audit records AQ failure, adapter invocation, Codex validation, and `external_api_called=false`

#### Scenario: Codex proposal is incomplete
- **WHEN** the Codex proposal omits, duplicates, invents, or assigns an unavailable resource to a heat
- **THEN** the proposal is rejected and the scenario is marked unexecutable or requiring human review
- **AND** no unchecked assignment is persisted as a successful result

### Requirement: Benchmark metrics compare AP, AQ, and AR per heat
The benchmark output MUST preserve per-scenario and per-heat AP, AQ, and AR assignments and calculate completion, timing, change, resource, route, hard-constraint, location, and factory-ladle agreement metrics when source data is available.

#### Scenario: A branch completes the same window as its peer
- **WHEN** AQ and AR both pass all hard gates
- **THEN** the benchmark records their metrics, changed heat IDs, factory-ladle matches, and an explicit recommendation or tie

#### Scenario: Neither branch has an eligible LLM denominator
- **WHEN** a report aggregates a set with no LLM-eligible scenario
- **THEN** LLM-specific rates are represented as `null`/N/A rather than zero
