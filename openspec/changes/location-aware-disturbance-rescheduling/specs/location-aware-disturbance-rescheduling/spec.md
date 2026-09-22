## ADDED Requirements

### Requirement: Location-aware disturbance baseline

The system SHALL use the location-mapped decision-tree audit as the only baseline for a location-aware disturbance replay, including its normalized PLAN/CRANE inputs, ladle coordinates, crane coordinates, and baseline assignments.

#### Scenario: Load a valid location-aware baseline

- **WHEN** a replay receives a decision-tree audit containing location metadata and normalized scheduling inputs
- **THEN** the replay SHALL construct its baseline from that audit and SHALL preserve the recorded location source and algorithm version.

#### Scenario: Reject an incompatible baseline

- **WHEN** a replay receives an audit without location-aware inputs or with a mismatched algorithm/source marker
- **THEN** the replay SHALL fail before injecting a disturbance and SHALL report that a location-aware baseline is required.

### Requirement: Local disturbance impact scope

The system SHALL apply a disturbance only to the affected, not-yet-locked heats and resources, SHALL preserve frozen assignments, and SHALL record both affected and excluded heat IDs.

#### Scenario: Exclude locked heats

- **WHEN** an event resource is assigned to a heat that is already locked or executed
- **THEN** that heat SHALL remain on its baseline assignment, SHALL not enter reallocation, and SHALL appear in the excluded locked heat audit.

#### Scenario: Preserve unaffected heats

- **WHEN** a disturbance affects a subset of the production plan
- **THEN** heats outside the impact scope SHALL retain their baseline assignments in every response result.

#### Scenario: Apply supported event state changes

- **WHEN** the event is crane unavailable, ladle unavailable, facility unavailable, or schedule deviation
- **THEN** the replay SHALL remove or block the corresponding resource, route, or time state and SHALL record the event delta in the scenario audit.

### Requirement: Tiered response on mapped inputs

The system SHALL run the decision tree first for the location-aware affected heats, SHALL call LLM ReAct only after a non-emergency decision-tree failure with positive remaining budget, and SHALL use Frozen plus human review after budget exhaustion or failed recovery.

#### Scenario: Decision tree recovers locally

- **WHEN** the location-aware decision tree assigns every affected heat within the shared constraints
- **THEN** the system SHALL merge the decision-tree result with frozen baseline assignments and SHALL not call LLM.

#### Scenario: LLM recovers a decision-tree failure

- **WHEN** the decision tree does not complete the affected set, the event is non-emergency, and remaining budget is positive
- **THEN** the system SHALL invoke the LLM adapter with only the affected context and decision-tree failure feedback, validate the proposal, and use it only when the full proposal passes.

#### Scenario: Emergency or exhausted budget

- **WHEN** the earliest affected pour leaves no budget after the 90-second safety buffer
- **THEN** the system SHALL not invoke LLM, SHALL retain Frozen assignments, and SHALL require human review.

#### Scenario: Failed LLM recovery

- **WHEN** the LLM times out, returns an incomplete/duplicate/unknown proposal, or fails shared/event-specific validation
- **THEN** the system SHALL reject the proposal, retain Frozen assignments, and SHALL record the failure reason and validation feedback.

### Requirement: Shared location and event validation

The decision-tree result and LLM result SHALL be validated against the same location-aware hard constraints, including ladle position, crane position and range, load, time window, safe distance, and event-specific route or facility policy.

#### Scenario: Reject an invalid resource proposal

- **WHEN** a response proposes an unknown resource, an unavailable resource, or an assignment that violates mapped-coordinate constraints
- **THEN** the validator SHALL mark the assignment invalid and SHALL prevent it from being merged or published.

#### Scenario: Preserve route constraints

- **WHEN** a facility or refining-route disturbance has an allowed/blocked route policy
- **THEN** the validator SHALL require every affected assignment to preserve or select an allowed route and SHALL reject omitted or blocked routes.

### Requirement: Reproducible offline and realtime adapters

The system SHALL support both a reviewed offline LLM adapter and a runtime LLM adapter through the same controller contract, and SHALL distinguish offline evidence from external API execution.

#### Scenario: Run an offline reviewed proposal

- **WHEN** a saved Codex proposal fixture is supplied to the LLM adapter
- **THEN** the controller SHALL invoke the adapter through the normal fallback path, validate the proposal, and record `external_api_called=false`.

#### Scenario: Run a runtime LLM request

- **WHEN** a runtime LLM adapter is configured with an API key and an eligible failure occurs
- **THEN** the adapter SHALL receive the runtime key without persisting the key, Authorization value, or credential-bearing prompt in any audit or database record.

### Requirement: Audited scenario outputs

The system SHALL persist a scenario record containing the mapped baseline source, event, impact scope, locked exclusions, decision-tree result, LLM result when attempted, Frozen fallback when applicable, changed assignments, timing budget, and validation checks.

#### Scenario: Persist a successful LLM stress scenario

- **WHEN** a mapped-input stress scenario has an incomplete decision-tree result and a passing LLM result
- **THEN** the saved JSON/SQLite evidence SHALL contain both response stages, the adapter invocation metadata, all affected heat IDs, and passing validation checks.

#### Scenario: Persist a decision-tree control scenario

- **WHEN** a mapped-input control scenario is solved by the decision tree
- **THEN** the saved evidence SHALL contain the decision-tree result, SHALL contain no LLM invocation, and SHALL remain queryable as a control category.
