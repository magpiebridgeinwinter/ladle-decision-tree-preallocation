## ADDED Requirements

### Requirement: Location dictionary parsing

The system SHALL read `loc_location.xlsx` as an explicit input and SHALL normalize each location record by its `LOC_LOCATION` code while preserving its coordinate, span, type, status, and plant description fields.

#### Scenario: Parse a mapped location

- **WHEN** the location dictionary contains `4QF5` with `POS_X=36075`
- **THEN** the normalized location record for `4QF5` SHALL expose coordinate `36075` and retain the source location code and metadata.

#### Scenario: Reject duplicate location codes

- **WHEN** the location dictionary contains two non-identical rows with the same `LOC_LOCATION`
- **THEN** the loader SHALL report a duplicate-key validation error instead of silently selecting one row.

### Requirement: Location-aware scheduling inputs

The system SHALL use the normalized location coordinate when constructing a ladle scheduling candidate, SHALL preserve the original position code, and SHALL record whether the coordinate came from `loc_location.xlsx`.

#### Scenario: Use mapped coordinate in allocation

- **WHEN** a PLAN ladle position code matches a location dictionary record with a valid `POS_X`
- **THEN** the candidate ladle SHALL use that mapped coordinate for distance, arrival-time, range, and scoring calculations.

#### Scenario: Report missing coordinate mapping

- **WHEN** a PLAN position code is absent from the dictionary or its dictionary row has no valid `POS_X`
- **THEN** the system SHALL mark the mapping as missing and SHALL expose that reason in the run audit or explicit exclusion result rather than silently treating the code as coordinate `0`.

### Requirement: Reproducible location-aware preallocation

The system SHALL rerun the decision-tree preallocation against the selected real PLAN and CRANE records using the location-aware inputs, and SHALL produce an auditable result keyed by `出钢记号-计划顺序号`.

#### Scenario: Generate a full real-data result

- **WHEN** the real PLAN, CRANE, and location dictionary inputs are available
- **THEN** the run SHALL produce one auditable assignment or explicit non-assignment outcome for every selected PLAN heat and SHALL record input paths, mapping statistics, algorithm version, and allocation metrics.

#### Scenario: Preserve traceable crane IDs

- **WHEN** a heat is assigned by the location-aware decision tree
- **THEN** its crane ID SHALL belong to the real crane snapshot set used by the run.

### Requirement: Append workbook result without overwriting prior results

The system SHALL append the location-aware decision-tree result as a new final column in the output workbook and SHALL preserve all existing source and prior result columns.

#### Scenario: Append AP after existing output columns

- **WHEN** the existing workbook ends at column `AO`
- **THEN** the exporter SHALL append column `AP` with header `决策树预配包（接入位置映射）` and second-row key `DecisionTreePreallocationWithLocationMap`.

#### Scenario: Keep prior columns unchanged

- **WHEN** the output workbook is compared with its input across columns `A:AO`
- **THEN** the comparison SHALL report zero changed cells.

#### Scenario: Write explicit assignment outcomes

- **WHEN** an evaluated heat is assigned, unassigned, or excluded
- **THEN** column `AP` SHALL contain respectively a short assignment string with ladle/crane IDs, an explicit non-assignment reason, or an explicit exclusion reason; blank cells SHALL not be used to hide an outcome for an evaluated heat.

### Requirement: Verification and audit

The system SHALL verify the location-aware workbook and audit before publishing the output path.

#### Scenario: Verify key sample and formulas

- **WHEN** export verification runs
- **THEN** it SHALL inspect a representative mapped heat including `JU6310E7-300770`, scan for common formula errors, and render the appended result area for visual inspection.

#### Scenario: Publish a safe output

- **WHEN** all verification checks pass
- **THEN** the system SHALL save a new output workbook under `outputs/` without overwriting the original desktop data file or the existing disturbance result workbook.
