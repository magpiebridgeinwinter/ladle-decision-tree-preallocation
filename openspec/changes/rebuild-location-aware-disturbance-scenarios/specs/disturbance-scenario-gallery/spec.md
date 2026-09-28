## ADDED Requirements

### Requirement: Gallery contains one card for every dynamic scenario
The gallery MUST render all 20 catalog scenarios from the benchmark output and MUST derive each card's row count and impact label from that scenario's dynamic `heat_results` and `impact_scope`.

#### Scenario: Scenarios have different affected counts
- **WHEN** the benchmark contains different local window sizes
- **THEN** each SVG/card renders the corresponding number of affected rows without padding them as if they were fixed two-heat or 20-heat cases

#### Scenario: The benchmark is incomplete
- **WHEN** the gallery input does not contain exactly 20 scenarios or a required branch result
- **THEN** generation fails before writing a misleading gallery

### Requirement: Affected and context heats are visually distinct
The gallery MUST distinguish window-affected heats from window-outside context heats. Affected rows MUST use the AQ/AR result colors, while context rows MUST use the existing blue context treatment and MUST NOT be described as solved by either branch.

#### Scenario: AQ and AR produce the same affected assignment
- **WHEN** an affected heat has equivalent AQ and AR ladle, crane, and route assignments
- **THEN** the row is rendered green

#### Scenario: AQ and AR differ or AQ fails
- **WHEN** an affected heat has different branch assignments, an AQ failure, or Codex completion of an AQ gap
- **THEN** the row uses the corresponding yellow, red, or orange treatment and the branch text remains visible

#### Scenario: A context heat is shown around the window
- **WHEN** a source heat is outside the affected set but is included to explain local order
- **THEN** it is rendered blue in both columns and is not included in branch completion or changed-heat metrics

### Requirement: Gallery is a read-only projection of audited results
The gallery generator MUST NOT rerun AQ, AR, or event injection. It MUST display the scenario's persisted recommendation, counts, audit status, and normalized presentation labels while retaining source timestamps only in machine-readable benchmark data.

#### Scenario: Offline Codex metadata is displayed
- **WHEN** a card displays a Codex branch
- **THEN** it identifies the result as an offline audited Codex proposal and preserves `external_api_called=false`

#### Scenario: Physical telemetry is unavailable
- **WHEN** the source has no pickup/drop-off timestamps or continuous crane telemetry
- **THEN** the gallery uses plan/scheduled wording and does not claim a measured crane trajectory
