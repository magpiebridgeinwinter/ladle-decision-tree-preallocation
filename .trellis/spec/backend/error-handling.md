# Error Handling

## Boundary rules

Validate external JSON at the API boundary, return stable JSON errors, and keep domain
exceptions inside the package. The standard-library handler in `tools/serve_visualization.py`
must not expose tracebacks or raw request bodies.

## Status matrix

| Status | Meaning | Example |
| --- | --- | --- |
| `200` | Request completed | Complete allocation or successful simulation |
| `400` | Malformed request | Invalid JSON, missing field, unsupported query value |
| `404` | Resource absent | Unknown `scenario_id` |
| `409` | Snapshot conflict | Duplicate resource ID or conflicting location mapping |
| `422` | Valid but infeasible | No resource set satisfies the hard constraints |
| `500` | Unexpected local failure | Unhandled repository or workflow failure |
| `503` | Required local dependency unavailable | Scenario database missing, or LLM is unconfigured for simulation |

## Response shape

All API errors are JSON objects with `error`. Add `error_type`, `request_id`, `scenario_id`,
or `details` only when they help the caller recover. Never return a stack trace, prompt,
authorization header, API key, or complete input payload.

```json
{
  "error": "请求格式错误：JSONDecodeError",
  "request_id": "plan-001",
  "details": ["heats must be a non-empty array"]
}
```

## Catching exceptions

- Catch expected `ValueError`, `KeyError`, `TypeError`, `OSError`, and SQLite errors at the
  boundary where they can be translated into a stable response.
- Log unexpected failures with `LOGGER.exception(...)` and return a generic `500` message.
- Do not use a broad catch to mark an allocation as successful. An invalid or incomplete
  proposal remains unassigned or requires human review.
- Preserve `request_id` in both successful and business-failure responses when it was parsed.

## Common mistakes

- Treating `llm_result.success` as sufficient without running the shared validator.
- Returning `200` for malformed input or hiding an incomplete assignment as `completed`.
- Echoing the request body to make debugging easier; use a redacted audit summary instead.
