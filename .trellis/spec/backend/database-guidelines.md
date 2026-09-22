# Database Guidelines

## Scenario: Offline Scheduling Evidence Store

### 1. Scope / Trigger

Use this contract when persisting reproducible ladle-disturbance scenarios for
browser playback. SQLite is an offline evidence projection; the source of truth
for production fields remains the audited PLAN(1)/CRANE input.

### 2. Signatures

```python
write_database(records: Iterable[dict[str, Any]], database_path: str | Path) -> Path
ScenarioRepository(database_path).summary() -> dict[str, Any]
ScenarioRepository(database_path).list_scenarios(category=None) -> list[dict[str, Any]]
ScenarioRepository(database_path).get_scenario(scenario_id) -> dict[str, Any] | None
```

CLI and API:

```text
python3 tools/build_offline_scenario_db.py [--source-audit PATH] [--database PATH] [--summary PATH]
GET /api/scenarios/summary
GET /api/scenarios?category=decision_tree_control|llm_fallback_stress
GET /api/scenarios/{scenario_id}
```

Tables are `scenario`, `event`, `scenario_asset`, `response_result`,
`assignment`, `validation`, `audit_metadata`, and `build_metadata`.

### 3. Contracts

- `scenario.category` is exactly `decision_tree_control` or
  `llm_fallback_stress`.
- Filterable values are typed columns. Nested source snapshots and audit detail
  use canonical JSON (`sort_keys=True`, compact separators).
- Every child table has a foreign key to `scenario`; assignments also reference
  `(scenario_id, stage)` in `response_result`.
- Writer builds an exact temporary database, runs integrity/invariant checks,
  commits, then atomically replaces the requested output.
- Repository connections use SQLite URI `mode=ro`.
- API keys, Authorization values, prompts containing credentials, and secret
  environment values are forbidden in every table.
- Saved offline timings use the deterministic demo clock, not host wall time.

### 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| Database missing | Repository raises `FileNotFoundError`; API returns 503 |
| Unsupported category query | Repository raises `ValueError`; API returns 400 |
| Unknown scenario ID | Repository returns `None`; API returns 404 |
| Foreign-key or integrity failure | Abort build; do not replace prior database |
| Stress row has DT success, no LLM call, or LLM failure | Abort build |
| Control row attempts LLM | Abort build |
| Any LLM validation row fails | Abort build |

### 5. Good / Base / Bad Cases

- Good: a stress scenario stores DT `1/2`, LLM `2/2`, source assets, event
  deltas, and passing validations in one transaction.
- Base: a control scenario stores only a decision-tree response and has
  `llm_success=NULL`.
- Bad: persisting a single summary JSON that cannot show which heat, ladle,
  crane, route, or validation produced the headline result.

### 6. Tests Required

- Rebuild logical records twice and assert canonical JSON equality.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
- Assert only the two allowed categories exist.
- Assert every catalog disturbance has one verified LLM stress row.
- Round-trip a route-change detail and assert alternate routes survive storage.
- Serialize a scenario detail and assert credential field names are absent.
- Exercise summary, filtered list, detail, and not-found API paths.

### 7. Wrong vs Correct

#### Wrong

```python
connection = sqlite3.connect(path)
connection.execute("INSERT INTO scenario ...")
connection.commit()  # partially overwrites the only demo artifact
```

#### Correct

```python
with sqlite3.connect(temporary) as connection:
    connection.executescript(SCHEMA)
    insert_all_records(connection)
    assert_database(connection)
    connection.commit()
os.replace(temporary, path)
```

## Naming And Query Conventions

- Table and column names use singular `snake_case`.
- Stable domain IDs are text primary keys; ordered timeline/check rows use a
  composite key ending in `sequence`.
- Always parameterize query values. Static schema and invariant SQL may remain
  literal constants.
