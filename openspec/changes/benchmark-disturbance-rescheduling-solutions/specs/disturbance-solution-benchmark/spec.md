## ADDED Requirements

### Requirement: Shared experiment baseline
The system SHALL build every benchmark scenario from the location-aware AP audit and SHALL provide AQ and AR with the same disturbance snapshot, affected heat set, available resources, time window, and validation policy.

#### Scenario: Build a comparable scenario
- **WHEN** a supported controlled disturbance is included in the benchmark
- **THEN** the result SHALL identify its AP source, affected heat IDs, controlled state changes, AQ input contract, and AR input contract
- **AND** AR SHALL NOT use AQ assignments as proposal input

#### Scenario: Reject mixed evidence
- **WHEN** AP heat IDs or source assets do not match the scenario record
- **THEN** the benchmark build SHALL fail before publishing comparison outputs

### Requirement: Complete disturbance matrix
The system SHALL evaluate each supported v1 disturbance kind exactly once as an LLM fallback stress scenario and SHALL preserve the 31-heat crane-offline scenario as the primary replay.

#### Scenario: Build the v1 matrix
- **WHEN** the benchmark is generated from the current disturbance catalog
- **THEN** it SHALL contain 20 stress scenarios covering every catalog kind without duplicates
- **AND** the primary crane-offline result SHALL contain 31 affected heats

### Requirement: Executability hard gates
The system SHALL mark a branch executable only when it completes every affected heat, passes every shared validation check, changes no locked or unaffected heat, and references no unavailable or unknown resource.

#### Scenario: Branch fails a hard gate
- **WHEN** any executability hard gate fails
- **THEN** the branch SHALL be marked non-executable
- **AND** the result SHALL list the failed gate and evidence

#### Scenario: Branch passes all hard gates
- **WHEN** all executability hard gates pass
- **THEN** the branch SHALL be marked executable and eligible for effectiveness comparison

### Requirement: Deterministic branch recommendation
The system SHALL choose the recommended branch using hard-gate validity first, followed by completion, on-time rate, average delay, maximum delay, AP changed-heat count, resource-change count, and crane-load dispersion in that order.

#### Scenario: Only one branch is executable
- **WHEN** exactly one branch passes all hard gates
- **THEN** the system SHALL recommend that branch and identify the other branch's failed gates

#### Scenario: Both branches are executable
- **WHEN** both branches pass all hard gates
- **THEN** the system SHALL apply the ordered metric comparison and record the first differentiating metric

#### Scenario: Neither branch is executable
- **WHEN** neither branch passes all hard gates
- **THEN** the system SHALL recommend human review and retain both failure explanations

### Requirement: Factory comparison boundary
The system SHALL compare AP, AQ, and AR with the factory preallocated ladle only for heats with a valid factory ladle value and SHALL report unavailable factory fields explicitly.

#### Scenario: Factory ladle is available
- **WHEN** a heat has a valid factory `preallocated_ladle`
- **THEN** the heat result SHALL record whether AP, AQ, and AR select the same ladle
- **AND** scenario agreement rates SHALL use only valid factory-ladle samples as the denominator

#### Scenario: Factory evidence is unavailable
- **WHEN** factory crane assignment, post-disturbance manual assignment, or execution outcome is absent
- **THEN** the corresponding comparison SHALL be `not_available` with a reason and SHALL NOT be represented as zero

### Requirement: Auditable experiment outputs
The system SHALL publish one canonical benchmark JSON and derive CSV and Excel views from that JSON without reimplementing recommendation logic.

#### Scenario: Export experiment package
- **WHEN** benchmark generation succeeds
- **THEN** the output directory SHALL contain the canonical JSON, scenario CSV, heat CSV, and one Excel workbook
- **AND** all outputs SHALL identify source files, evidence type, controlled overrides, method results, validations, metrics, recommendation, and Codex invocation boundary

#### Scenario: Protect evidence integrity
- **WHEN** outputs are validated
- **THEN** there SHALL be no API key, Authorization value, duplicated scenario ID, missing affected heat, or unsupported disturbance kind

### Requirement: Qualified aggregate conclusions
The system SHALL aggregate results by scenario and disturbance group without presenting controlled experiments as field incident statistics.

#### Scenario: Produce overall summary
- **WHEN** all stress scenarios are evaluated
- **THEN** the summary SHALL report scenario counts, executable counts, recommendation counts, hard-gate failures, and metric distributions for AQ and AR
- **AND** 31-heat and two-heat experiments SHALL remain distinguishable

#### Scenario: State evidence limits
- **WHEN** the experiment conclusion is exported
- **THEN** it SHALL state that the assets and schedules are source-backed, the disturbances are controlled injections, and the Codex proposals are offline audited results with `external_api_called=false`
