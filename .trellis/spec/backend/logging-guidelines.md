# Logging Guidelines

The service uses the Python standard-library `logging` module. `tools/serve_visualization.py`
configures a concise `LEVEL message` format for the local server; library modules use a module
logger and do not configure global handlers.

## Levels

- `INFO`: route access, server startup, and a completed high-level operation.
- `WARNING`: recoverable fallback, stale local data, or a degraded/manual-review result.
- `ERROR`: an operation failed and was handled by the caller.
- `LOGGER.exception(...)`: unexpected failures where a traceback is useful for local debugging.
- Avoid `DEBUG` output in normal scripts unless a focused diagnostic needs it.

## Required context

When available, include the route or operation, stable identifier, result status, and exception
type. Prefer structured values in the message over dumping a full dictionary.

```python
LOGGER.exception("simulation failed: %s", type(exc).__name__)
```

## Never log

- `LLM_API_KEY`, Authorization headers, `.env.local`, prompts, raw model responses, or full request bodies;
- source workbook rows unless the log is a deliberately redacted diagnostic;
- credentials embedded in exception text or URLs.

Audit data belongs in the documented response/audit model, where it must remain redacted and
reproducible. Logs are operational context, not a second database.
