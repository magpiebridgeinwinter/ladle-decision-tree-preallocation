# Ladle-only preallocation API

`POST /api/v1/ladle-preallocation/allocate-ladles` assigns concrete ladles such as
`ST22` to the upstream heat plan. The public contract follows the confirmed
`schedule_start_at`, `heats[].route`, and original candidate field names. The
existing transport `/allocate` route remains a separate interface.

The response is the complete original JSON. Allocation manages only `ladle_id`
and, for an unassigned heat, `allocation_reason` on the original heat objects.
It preserves field names, values, JSON types, timestamps, array order, casting
metadata, machine statistics, and wrapper structure. It does not add an
`assignments` or diagnostic envelope.

The execution system owns acceptance, reservations, current occupation, and
crane dispatch. This service calculates a proposal without database writes,
production baseline registration, or LLM calls.

## Executable examples

From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tools/serve_visualization.py --port 4173
```

In another terminal:

```powershell
curl.exe -i -X POST http://127.0.0.1:4173/api/v1/ladle-preallocation/allocate-ladles -H "Content-Type: application/json" --data-binary "@docs/examples/ladle-only-request.json"
```

| Case | Request | Actual public response |
|---|---|---|
| Two converters with genuine casting groups and metadata | [request](examples/ladle-only-request.json) | [response](examples/ladle-only-response.json) |
| Four top-level fields, no request ID or casting groups | [minimal request](examples/ladle-only-minimal-request.json) | [minimal response](examples/ladle-only-minimal-response.json) |
| One candidate for two overlapping heats | [partial request](examples/ladle-only-partial-request.json) | [partial response](examples/ladle-only-partial-response.json) |
| Original message wrapper | [wrapped request](examples/ladle-only-wrapped-request.json) | [wrapped response](examples/ladle-only-wrapped-response.json) |

Every saved response is generated through the public adapter. The
[machine-readable OpenAPI](ladle-preallocation-openapi.yaml) describes the
canonical plan and the generic wrapper variant. Runtime validation enforces
unique plan location and constraints that arbitrary-depth wrapper schemas cannot
express.

## Required plan input

The normal HTTP request has four top-level fields:

| Field | Type | Meaning |
|---|---|---|
| `schedule_start_at` | RFC3339 string | First converter blowing start; exactly 08:00 in its supplied timezone |
| `turnaround_seconds` | Nonnegative integer | Total time from casting completion to the next converter-ready time; zero is valid |
| `heats` | Array, 1–500 | Upstream fixed heat plan |
| `ladles` | Array, 0–200 | Concrete candidate snapshot; empty gives a valid unassigned result |

The original document's `turnaround_time` spelling is accepted as an alias for
`turnaround_seconds`. If both occur, they must be nonnegative integers with equal
values; otherwise HTTP 409 is returned. Their original field names are preserved.

A configured in-process service may supply an explicit anchor instead of a missing
`schedule_start_at`. The HTTP server does not guess a date or use today's 08:00.
`request_id` and `casts` are optional. Upstream `solver_options` is preserved as
metadata and never changes the program's solver controls.

Consumed timestamps require a timezone and whole-second precision, for example
`2026-10-30T08:20:00+08:00`. The allocator compares normalized internal times, but
the response retains the original timestamp strings. JSON booleans do not count
as integer durations or counters. All JSON numeric values must be finite,
including metadata; explicit null remains valid where the field permits it.
The HTTP body must be standard JSON: `NaN`, `Infinity`, and `-Infinity` are rejected
even inside inert metadata.

Unknown metadata is retained at all object boundaries. It does not become a
process rule or executable configuration.

### Heat fields

| Field | Required | Meaning |
|---|---|---|
| `heat_id` | Yes | Unique nonempty upstream heat identifier |
| `grade` | Yes | Nonnegative integer or nonempty steel code string, mapped internally |
| `route` | Yes | Ordered process/machine dictionaries |
| `tap_finish_at` | Yes | Converter tapping completion, not blowing start |
| `cast_finish_at` | No | Supplied casting completion; missing/null is estimated internally |
| `seq` | No | Original sequence metadata, with its original JSON type |
| `refining_route`, `cast_id` | No | Retained upstream metadata; neither substitutes for `route` or genuine casting order |
| `ladle_id` | No | A supplied non-null identity is a hard confirmed binding |

A route is an array of dictionaries:

```json
[
  {"operation": "BOF", "machine_id": "M0", "sequence_on_machine": 1},
  {"operation": "LF", "machine_id": "M2"},
  {"operation": "CC", "machine_id": "M4"}
]
```

BOF is first, CC is last, with zero to four LF, RH, VD, or VOD stages between them.
Upstream owns these machines and process routes; the allocation service does not
reschedule them.

For each converter independently, its first heat starts at the 08:00 anchor and
each later heat starts at that converter's preceding tapping completion. Between
heat preparation is assumed zero. With no explicit BOF `sequence_on_machine`,
tapping completion determines order. If any heat on one converter supplies this
order, every heat on that converter must supply a unique positive integer and
tapping completions must advance in that order. Duplicate or contradictory order
returns 409, including a missing sequence when other heats on that converter
declare explicit order. An explicit null or wrongly typed consumed order returns
400. Global `seq` is
never used to infer converter order. Sequence metadata on other route stages is
preserved without replacing it.

### Optional casting groups

```json
{"cast_id": "C001", "heat_ids": ["H0001", "H0004"], "machine_id": "M4"}
```

When supplied, `casts` partitions every request heat exactly once, has unique group
IDs and uses one CC per group. The first listed heat receives casting-first
process restrictions. Other fields on casting groups remain unchanged.

Without confirmed casting order, every heat is conservatively qualified as
potentially casting-first. This can reduce the candidate pool. Private qualification
groups are not real upstream casting groups and are never added to the response.
A heat-level `cast_id`, global `seq`, or machine count alone does not establish
casting-first status.

### Casting-completion estimates

Supplied `cast_finish_at` is preferred and must follow tapping completion. Missing
or null completion is estimated internally from the refining-stage count:

| Refining stages | Assumed minutes after `tap_finish_at` |
|---|---:|
| 0 | 100 |
| 1 | 160 |
| 2 | 290 |
| 3 | 360 |
| 4 | 420 |

These are simulation assumptions, not measured durations or safe upper bounds.
They do not reschedule the upstream caster. The estimate and its provenance remain
in internal diagnostics. A missing field is not inserted into the response, and an
explicit null stays null.

## Candidate input and internal assumptions

The approved candidate example has six fields:

```json
{
  "ladle_id": "ST22",
  "lining_material_code": "T",
  "minor_repair_age_heats": 10,
  "major_repair_age_heats": 50,
  "availability_status": "available",
  "available_at": "2026-10-30T08:00:00+08:00"
}
```

| Field | Meaning |
|---|---|
| `ladle_id` | Concrete ST identity, not steel grade or condition |
| `lining_material_code` | Lining-material dictionary key |
| `minor_repair_age_heats` | Uses consumed since minor repair, not elapsed waiting time |
| `major_repair_age_heats` | Uses consumed since major repair |
| `availability_status` | `available`, `occupied`, `maintenance`, `offline`, `scrapped`, or `unknown` |
| `available_at` | Initial ready time, including current-use turnaround |

Available and occupied candidates can serve a future heat at or after
`available_at`, if occupation and process rules pass. Other states remain excluded
until execution supplies a usable snapshot. Identity, availability, ready time,
lining material, and repair ages are not fabricated. A missing lining/age fact
required by the active profile produces a process exclusion.

Extra equipment, condition, and previous-use facts may be supplied within the
candidate. They are not additional mandatory fields for the approved demonstration:

| Additional fact | Assumed mode, only if absent |
|---|---|
| `condition_code` or documented candidate `grade` alias | `20A` |
| `usage_count` | 2 |
| `nozzle_used_heats`, `slide_used_heats`, `frame_used_heats` | 0 |
| `argon_ready` | true |
| Previous-use history | Hypothetical clean history only when both `last_use` and `history_assumption` are absent |

These versioned defaults are program-owned demonstration facts with per-field
provenance. Supplied values, including zero, false, explicit null and unknown,
remain authoritative. Providing `last_use: null` without a clean-history marker
leaves previous-steel history unknown. Actual `last_use` can contain `heat_id`,
`grade`, and `cast_finish_at`. Supplied temperature, weight, location, and storage
references are retained; no coordinate travel time is inferred.

The default steel mappings for grade 1 and 2 and the `T` lining-material entry are
explicit assumptions. `T` is evaluated as material; it is never parsed as a stopped
condition prefix. A candidate condition such as `20A`, a heat steel code such as
`grade: 2`, and a physical identity such as `ST22` are separate dictionaries.
Conflicting supported aliases return 409. Unknown steel or material codes remain
unmatched rather than being silently converted.

Confirmed policy supplies no process defaults. It excludes candidates missing an
active rule's required facts, including thermal/history facts when required.
Assumed thermal clocks and maintenance reset assumptions do not become enterprise
observations. During simulated reuse, the service increments consumed use/component
counts, updates immediate previous-steel history, and recomputes applicable condition
bands; it does not invent maintenance resets.

### Reservations and existing bindings

An external reservation supplies `use_start_at`, `cast_finish_at`, optional
`turnaround_seconds`, and optional external `heat_id`/`grade`. Missing reservation
turnaround inherits the plan value. Its unavailable interval ends after casting
plus turnaround. Reservations cannot overlap, and external heat IDs cannot duplicate
request heats. A reservation beginning at or after `snapshot_at` cannot precede
candidate `available_at`; a contradiction returns 409
`reservation_availability_conflict`. `snapshot_at` defaults to the plan anchor and
cannot be later than it.

Snapshot counters already include services started before the snapshot. They are
not incremented again. The newest known already-started reservation can provide
immediate previous-use history, including a casting completion at or before the
snapshot.

A non-null original heat `ladle_id`, or a consistent `confirmed_bindings` entry,
fixes that heat to its candidate. Such a binding cannot be replaced or silently
dropped. Conflicting/process-incompatible bindings return 409. Search ending
without a verified binding-preserving proposal returns 503 `search_incomplete`.

## Allocation and internal diagnostics

A selected ladle occupies the half-open interval:

```text
[converter blowing start, casting completion + turnaround)
```

Its next blowing start may equal its previous ready time. Turnaround already covers
return transport, preparation/cooling, and dispatch; those activities are not added
again. Casting completion releases the production service; readiness includes
turnaround.

The program combines steel-profile rules, availability calendars, a verified
initial plan, and CP-SAT. Objectives are maximum assigned heats, minimum distinct
ladles, then qualified process preferences. An independent replay validates
occupation, qualifications, fixed identities, and state transitions.

Solver controls and internal correlation identifiers are service configuration,
not upstream request fields. Wall time is bounded to 1–60 seconds (default 10) and
CP-SAT deterministic time to 0.001–60 units (default 5), shared across phases.
The wall budget includes filtering, initial-plan preparation, and model construction.
Construction is not interrupted at the deadline; validation, replay, serialization,
and transport add overhead. These budgets are not an HTTP latency guarantee.
A large request may return its independently verified initial plan before any
objective phase can run.

Proof levels, objectives, rule outcomes, source assumptions, and derived times are
retained internally. All three objective phases must be proven before internal
status is optimal. An unproven partial plan does not establish that the batch is
globally impossible. Public `allocation_reason` explains incomplete search where
applicable, even when local candidate rejections are known.

## Public response and HTTP outcomes

A complete result preserves the request and adds the selected identity:

```json
{
  "heat_id": "H0001",
  "grade": 1,
  "route": [
    {"operation": "BOF", "machine_id": "M0"},
    {"operation": "LF", "machine_id": "M2"},
    {"operation": "CC", "machine_id": "M4"}
  ],
  "tap_finish_at": "2026-10-30T08:20:00+08:00",
  "ladle_id": "ST22"
}
```

An unassigned original heat receives `ladle_id: null`
and a concise Chinese `allocation_reason`. A successful assignment clears a stale
allocation reason. No derived deadline, casting estimate, state transition,
reservation commit, or optimization field is added to the source JSON.

| HTTP status | Meaning |
|---|---|
| 200 | Every original heat assigned |
| 400 | Invalid consumed field/type/time, ambiguous heat-plan location, malformed JSON, or body too large |
| 409 | Conflicting IDs, aliases, machine/casting order, snapshot/occupation, or fixed bindings |
| 422 | Valid partial or unassigned proposal; the entire original message and every heat are retained |
| 503 | Dependency/policy unavailable or no verified binding-preserving plan within the search budget |
| 500 | Unexpected calculation or independent-replay failure |

Validation/dependency errors use a stable object with `error`, `error_code`, optional
public `field` and optional parsed request identifier. They do not echo raw bodies
or stack traces. Successful/partial proposal responses do not use this error envelope.

The new route accepts up to 2 MiB. Existing routes retain their 64 KiB limit.

### Wrapped upstream messages

The plan may sit inside original objects or arrays. The service locates exactly
one object containing a `heats` array, resolves configuration/candidates there or on its
ancestors, and returns the same wrapper. It never obtains configuration from
unrelated sibling objects. Two possible plans are rejected with HTTP 400 rather
than selecting one silently. Unrelated metadata such as `heats: "caption"` is retained
and does not create a second plan.

## PLAN identity fixture and validation

[data/ladle_only_candidates_assumed.json](../data/ladle_only_candidates_assumed.json)
contains the 36 distinct ST identities observed across PLAN dates, using the six
public candidate names. Only identity is observed; all five other supplied fields
are hypothetical. This is not a recovered enterprise snapshot and does not prove
that all 36 ladles were simultaneously available. Additional simulation facts
come from internal policy rather than extra fixture input fields. Runtime does not
read PLAN or this fixture automatically.

Install development dependencies and run the scoped contract checks:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q tests/test_ladle_only_http.py tests/test_ladle_only_api.py tests/test_ladle_only_domain.py
.venv\Scripts\python.exe tools/check_ladle_only_scale.py
```

The scale checker validates public heat round trips and reads proof/state information
through the internal diagnostic API. It creates no production reservations or database.
Enterprise dictionaries, candidate snapshots, and observed timing should replace
demonstration assumptions before operational use.
