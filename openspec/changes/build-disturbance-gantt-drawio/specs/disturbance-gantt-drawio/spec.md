## ADDED Requirements

### Requirement: Scenario audit is converted into traceable diagram data
The generator MUST convert one offline disturbance audit into a diagram data document that preserves the scenario ID, audit source, event marker, impact window, branch summaries, and one row for every affected heat.

#### Scenario: Real 11:00-11:20 stress audit is converted
- **WHEN** the generator reads `real_window_1100_1120_codex_stress_001`
- **THEN** the output records 31 affected heats, event resource `2500`, decision-tree completion `30/31`, Codex completion `31/31`, and the three Codex-changed heat IDs from the audit

#### Scenario: Missing source fields are rejected
- **WHEN** an audit lacks `scenario_id`, affected heat IDs, or both branch results
- **THEN** the generator fails with a field-specific error and does not emit a partially valid diagram

### Requirement: Diagram distinguishes preallocation from crane dispatch
The diagram MUST label `heat -> ladle` as preallocation and `transport task -> crane` as crane dispatch, and MUST NOT describe a plan-only crane assignment as measured physical motion when pickup, drop-off, and telemetry timestamps are absent.

#### Scenario: Current audit lacks physical motion telemetry
- **WHEN** the generated data has plan windows and crane IDs but no pickup/drop-off timestamps
- **THEN** the diagram uses “计划窗口/转运任务/计划服务位置” terminology and displays a visible model-boundary note

#### Scenario: Physical movement data is available later
- **WHEN** pickup, destination, task start/end, and telemetry fields are present
- **THEN** the diagram data preserves them as optional fields and may render a separate movement layer without changing the preallocation labels

### Requirement: Draw.io output contains a readable two-page local Gantt presentation
The generator MUST emit an uncompressed `.drawio` file with one page for the affected heats before the crane outage and one page for their post-event result. Both pages MUST use the same local time axis and heat order; unaffected heats MUST be summarized rather than expanded row by row.

#### Scenario: Draw.io file is imported
- **WHEN** the output is checked by the diagram-design draw.io import verifier
- **THEN** pages `01-离线前受影响炉次` and `02-离线后受影响炉次` are discoverable and the XML imports without an error

#### Scenario: Local pages are rendered
- **WHEN** a viewer compares the two pages
- **THEN** the viewer can identify all 31 affected heats, their exact plan start/end times, the source-time disturbance marker, the pre-event assignment, and the post-event assignment without scanning the other 426 heats

### Requirement: Affected heat assignment changes are visually traceable
The affected-heat page MUST make the baseline AP assignment and the AQ/AR branch results visible for each affected heat, including ladle and crane IDs when present, and MUST mark unchanged, decision-tree-only, Codex-only, and unresolved states with text and a visual distinction.

#### Scenario: Codex changes a heat assignment
- **WHEN** a heat differs from AP in the Codex branch
- **THEN** the heat row shows AP, AR ladle/crane values, a Codex change marker, and the heat ID `DT0142D1-300759`, `DT0143D8-300767`, or `DT0164D1-300776` as applicable

#### Scenario: Decision tree is incomplete
- **WHEN** a branch has an unassigned affected heat
- **THEN** the row shows the unassigned status and failure reason rather than implying successful completion

### Requirement: Diagram provenance and regression checks are emitted
The generator MUST emit diagram data alongside the draw.io file and MUST validate stable element IDs, one-to-one affected-heat coverage, event/window presence, and source-to-output counts.

#### Scenario: Stable element IDs are checked
- **WHEN** the output is validated
- **THEN** every heat element ID contains the scenario ID and heat ID, no affected heat is duplicated within a branch, and all 31 affected heat IDs are covered

#### Scenario: Output is regenerated
- **WHEN** the same audit and generator version are run again
- **THEN** the semantic data and stable element IDs are identical even if draw.io layout metadata changes
