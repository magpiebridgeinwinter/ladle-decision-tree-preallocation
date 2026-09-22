# Implementation Plan

1. Add the v1 disturbance catalog and update the supported-kind contract.
2. Allow the response controller to use an injected scenario validator while
   preserving the default validation path.
3. Build ordinary and severe scenarios from the real-data source audit and run
   saved Codex proposals through the tiered controller.
4. Add SQLite schema, transactional writer, read-only repository, deterministic
   batch CLI, and logical audit export.
5. Add list/detail/summary API routes to the local server without changing the
   frontend.
6. Generate the offline database and summary, then write the DewuClaw backend
   handoff document.
7. Run unit tests, Python compilation, database integrity assertions, API smoke
   checks, and `git diff --check`.

## Rollback Points

- The controller validator injection is backward compatible and can be
  reverted independently of the offline package.
- The database and generated summary live under `outputs/offline_scenarios/`
  and can be rebuilt from the source audit.
- API GET routes can be removed without affecting `POST /api/simulate`.
