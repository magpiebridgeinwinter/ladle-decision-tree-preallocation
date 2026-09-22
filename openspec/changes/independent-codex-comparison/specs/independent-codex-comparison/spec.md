## ADDED Requirements

### Requirement: Shared AP baseline

The system SHALL use the location-aware preallocation represented by `AP` as the only baseline for both disturbance response branches.

#### Scenario: Build both branches from AP

- **WHEN** a comparison is created for a location-aware disturbance
- **THEN** the decision-tree and Codex branches SHALL receive the same AP-derived assignments, normalized PLAN/CRANE inputs, mapped ladle positions, event state, and affected heat set.

#### Scenario: Reject a mixed baseline

- **WHEN** the proposed comparison baseline does not match the location-aware audit source or heat ID set
- **THEN** the comparison SHALL fail before writing AQ or AR and SHALL report the baseline mismatch.

### Requirement: Independent decision branches

The system SHALL solve decision-tree and Codex branches independently from the shared AP disturbance snapshot.

#### Scenario: Decision-tree branch

- **WHEN** a valid AP baseline and disturbance are available
- **THEN** the decision-tree branch SHALL inject the event, rerank only the affected heats, validate the result, and write the result to AQ.

#### Scenario: Codex branch

- **WHEN** the same AP baseline and disturbance are available
- **THEN** the Codex branch SHALL receive the same affected heats and available resources, SHALL NOT use AQ assignments as its solution input, and SHALL write its validated result to AR.

### Requirement: Current Codex offline adapter

The system SHALL support a credential-free Codex adapter whose structured response is the source of AR for this offline comparison.

#### Scenario: Codex returns a complete proposal

- **WHEN** the current Codex returns one assignment for every affected heat
- **THEN** the system SHALL validate the proposal with the shared validator, accept it only when all checks pass, and record `external_api_called=false`.

#### Scenario: Codex proposal is invalid

- **WHEN** the Codex response has missing, duplicate, unknown, unavailable, or constraint-violating assignments
- **THEN** the system SHALL reject the response, record validation feedback, and mark AR as unavailable for the affected heat or scenario.

### Requirement: Row-level comparison columns

The system SHALL append AS:AZ as a stable row-level comparison contract for affected heats.

#### Scenario: Populate comparison fields

- **WHEN** AQ and AR results are available for an affected heat
- **THEN** AS and AT SHALL report validation status, AU and AV SHALL report on-time status, AW and AX SHALL compare each branch with AP, and AY/AZ SHALL report the recommendation and reason.

#### Scenario: Leave unaffected rows empty

- **WHEN** a heat is outside the disturbance impact scope
- **THEN** AQ:AZ SHALL remain empty for that row and the AP baseline SHALL remain the only displayed assignment.

### Requirement: Deterministic recommendation

The system SHALL determine a recommendation using hard-constraint validity before service-effectiveness metrics.

#### Scenario: One branch is invalid

- **WHEN** exactly one of AQ and AR passes hard validation and completes the affected heat
- **THEN** AY SHALL recommend the valid branch and AZ SHALL state the validation difference.

#### Scenario: Both branches are valid

- **WHEN** both branches pass validation
- **THEN** the system SHALL compare completeness, on-time rate, average delay, maximum delay, changed heat count, and crane balance in that order, and SHALL mark the winner or `持平`.

#### Scenario: Both branches fail

- **WHEN** neither branch passes validation or completes the affected set
- **THEN** AY SHALL be `人工复核` and AZ SHALL include both failure reasons.

### Requirement: Scenario summary and audit

The system SHALL persist scenario-level comparison metrics and the Codex request/response audit without credentials.

#### Scenario: Export summary

- **WHEN** a comparison is exported
- **THEN** the workbook SHALL include a compact summary of completion, on-time rate, average/max delay, violations, changed heats, and final recommendation for both branches.

#### Scenario: Protect credentials

- **WHEN** the Codex request or response is saved
- **THEN** API keys, Authorization headers, and credential-bearing prompt fragments SHALL NOT appear in Excel, JSON, SQLite, or logs.
