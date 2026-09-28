## 1. Request Contract And Adapter

- [x] 1.1 Add a pure request parser that validates `request_id`, `heats`, `ladles`, `cranes`, date-time fields, numeric units, duplicate IDs, and location-map conflicts.
- [x] 1.2 Normalize valid API records into the existing decision-tree `heats`, `ladles`, and `cranes` structures while preserving `plan_key` and source identifiers.
- [x] 1.3 Map decision-tree assignments and excluded records into the documented output result, status, metrics, and audit shapes.

## 2. HTTP Route

- [x] 2.1 Add `POST /api/v1/ladle-preallocation/allocate` to the existing standard-library server without changing existing scenario routes.
- [x] 2.2 Return structured `400`, `409`, and `422` responses for malformed input, resource conflicts, and incomplete feasible allocation.
- [x] 2.3 Ensure the normal allocation route never constructs or calls an LLM client and never writes credentials to the response or audit.

## 3. Documentation And Configuration

- [x] 3.1 Synchronize `docs/ladle-preallocation-openapi.yaml` with the implemented route, status codes, schemas, and examples.
- [x] 3.2 Document `.env.local` sourcing and curl examples for normal preallocation and disturbance simulation.

## 4. Verification

- [x] 4.1 Add unit tests for valid requests, missing fields, malformed timestamps, duplicate resources, and location conflicts.
- [x] 4.2 Add route tests for complete assignment, partial/manual-review response, existing `/api/simulate` compatibility, and secret redaction.
- [x] 4.3 Run focused tests, OpenAPI YAML/reference validation, and `git diff --check`.
