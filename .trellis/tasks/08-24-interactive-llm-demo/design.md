# Technical Design

## Data Flow

`PLAN(1)/CRANE audit -> controlled scenario builder -> tiered controller ->
scenario validator -> SQLite repository -> read-only JSON API -> frontend`.

The existing decision-tree allocator and `validate_output` remain the base
hard-constraint authority. A scenario validator adds contracts absent from the
legacy assignment shape, including configured alternate routes and distinct
resource use. The tiered controller accepts this validator so decision-tree and
LLM proposals are judged by the same rules.

## Scenario Model

The disturbance catalog is grouped by equipment, ladle, process/facility,
plan/timing, logistics/safety, telemetry, and compound events. Each definition
owns a stable kind, Chinese title, event description, affected source resource,
controlled state changes, and a frontend visual cue.

The ordinary control replays a local source-backed crane outage with the full
remaining candidate pool and no LLM. Severe scenarios use real heat, ladle,
crane, and route records with explicit controlled overrides. Saved Codex
proposals are deterministic fixtures and are always revalidated at build time.

## Persistence

Use standard-library SQLite with foreign keys and indexed normalized tables:

- `scenario`: category, kind, evidence type, timing, path and outcome summary.
- `event`: ordered timeline events and payloads.
- `scenario_asset`: source-backed heats, ladles, cranes, routes, and roles.
- `response_result`: decision-tree and LLM stage outcomes.
- `assignment`: per-stage heat-to-ladle/crane/route decisions.
- `validation`: machine-readable check outcomes.
- `audit_metadata`: source references and controlled-override details.

Nested source snapshots and audit explanations remain JSON; fields used for
filtering or metrics are first-class columns.

## API

The local server exposes `GET /api/scenarios/summary`, `GET /api/scenarios`,
and `GET /api/scenarios/{id}` from a read-only SQLite connection. Existing
static serving and `POST /api/simulate` remain compatible. Missing databases
return a redacted service-unavailable response.

## Safety And Compatibility

- No schema stores credentials.
- Building writes a new exact database target and performs integrity checks
  before replacing the prior artifact.
- Existing allocator callers use the default validator unchanged.
- Additional assignment fields are preserved during merge so route decisions
  survive controller output.
