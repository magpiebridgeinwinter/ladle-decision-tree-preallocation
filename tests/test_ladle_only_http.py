from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import jsonschema
import pytest
import yaml

from ladle_preallocation import ladle_only_api


ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location(
    "serve_ladle_only_http", ROOT / "tools/serve_visualization.py"
)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
SERVER = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(SERVER)
ROUTE = "/api/v1/ladle-preallocation/allocate-ladles"


def example_request() -> dict:
    return json.loads((ROOT / "docs/examples/ladle-only-request.json").read_text(encoding="utf-8-sig"))


class FakePostHandler:
    def __init__(self, path: str, payload: object, *, length: int | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.path = path
        self.headers = {"Content-Length": str(len(body) if length is None else length)}
        self.rfile = io.BytesIO(body)
        self.status = None
        self.body = None

    def _send_json(self, status: int, body: dict) -> None:
        self.status, self.body = status, body


def dispatch(payload: object, path: str = ROUTE, *, length: int | None = None) -> FakePostHandler:
    handler = FakePostHandler(path, payload, length=length)
    SERVER.DemoHandler.do_POST(handler)
    return handler


@pytest.fixture
def live_server(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("ladle-only calculation crossed an execution/LLM boundary")

    monkeypatch.setattr(SERVER, "ReActRescheduler", forbidden)
    monkeypatch.setattr(SERVER.DemoHandler, "_production_service", classmethod(forbidden))
    production_database = tmp_path / "production.sqlite3"
    scenario_database = tmp_path / "scenario.sqlite3"
    monkeypatch.setattr(SERVER.DemoHandler, "production_database", production_database)
    monkeypatch.setattr(SERVER.DemoHandler, "scenario_database", scenario_database)
    server = SERVER.ThreadingHTTPServer(("127.0.0.1", 0), SERVER.DemoHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not production_database.exists()
        assert not scenario_database.exists()


def post_http(base_url: str, payload: object, path: str = ROUTE) -> tuple[int, dict]:
    return post_raw_http(base_url, json.dumps(payload).encode("utf-8"), path)


def post_raw_http(base_url: str, raw_body: bytes, path: str = ROUTE) -> tuple[int, dict]:
    request = Request(
        base_url + path,
        data=raw_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            assert response.headers["Content-Type"] == "application/json; charset=utf-8"
            assert response.headers["Cache-Control"] == "no-store"
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read())


def assert_source_preserved(source: dict, output: dict) -> None:
    restored = copy.deepcopy(output)
    for heat in restored["heats"]:
        heat.pop("ladle_id", None)
        heat.pop("allocation_reason", None)
    expected = copy.deepcopy(source)
    for heat in expected["heats"]:
        heat.pop("ladle_id", None)
        heat.pop("allocation_reason", None)
    assert restored == expected


def test_live_http_original_message_and_execution_isolation(live_server):
    payload = example_request()
    status, body = post_http(live_server, payload)
    assert status == 200
    assert [row["heat_id"] for row in body["heats"]] == ["H0001", "H0002"]
    assert {row["ladle_id"] for row in body["heats"]} == {"ST22", "ST23"}
    assert_source_preserved(payload, body)
    assert "cast_finish_at" not in body["heats"][0]
    assert body["heats"][1]["cast_finish_at"] == "2026-10-30T11:05:00+08:00"
    assert body["heats"][0]["seq"] == "1"
    assert body["heats"][1]["seq"] == 2
    assert set(body) == set(payload)
    assert "assignments" not in body and "solver" not in body
    assert "crane_id" not in json.dumps(body)


def test_live_http_minimal_six_field_candidate(live_server):
    payload = json.loads((ROOT / "docs/examples/ladle-only-minimal-request.json").read_text(encoding="utf-8"))
    assert set(payload) == {"schedule_start_at", "turnaround_seconds", "heats", "ladles"}
    assert set(payload["ladles"][0]) == {"ladle_id", "lining_material_code", "minor_repair_age_heats", "major_repair_age_heats", "availability_status", "available_at"}
    status, body = post_http(live_server, payload)
    assert status == 200
    assert body["heats"][0]["ladle_id"] == "ST22"
    assert "casts" not in body and "request_id" not in body
    assert_source_preserved(payload, body)


def test_live_http_documented_input_and_business_errors(live_server):
    invalid = example_request()
    invalid["heats"][0]["grade"] = True
    status, body = post_http(live_server, invalid)
    assert status == 400 and "error" in body
    assert "grade" in body["field"]
    duplicate = example_request()
    duplicate["ladles"].append(copy.deepcopy(duplicate["ladles"][0]))
    status, body = post_http(live_server, duplicate)
    assert status == 409 and "error" in body
    empty = example_request()
    empty["ladles"] = []
    status, body = post_http(live_server, empty)
    assert status == 422
    assert len(body["heats"]) == len(empty["heats"])
    assert all(row["ladle_id"] is None and row["allocation_reason"] for row in body["heats"])
    assert_source_preserved(empty, body)


def test_live_http_metadata_is_inert_and_wrappers_round_trip(live_server):
    payload = example_request()
    payload["solver_options"] = {"seed": 123, "time_limit_seconds": "inert", "process_rules": {"allow_all": True}}
    payload["extension"] = {"nullable": None, "mixed": [False, 0, "text"]}
    status, body = post_http(live_server, payload)
    assert status == 200
    assert_source_preserved(payload, body)
    wrapped = {"code": 0, "heats": "caption", "data": payload, "trace": ["kept", {"request_id": 12}]}
    status, body = post_http(live_server, wrapped)
    assert status == 200
    assert body["trace"] == wrapped["trace"]
    assert body["code"] == 0
    assert body["heats"] == "caption"
    validator("InputLadleOnlyWrappedRequest").validate(wrapped)
    validator("OutputLadleOnlyWrappedResponse").validate(body)
    assert_source_preserved(payload, body["data"])
    status, body = post_http(live_server, {"first": payload, "second": copy.deepcopy(payload)})
    assert status == 400 and "error" in body


def test_live_http_turnaround_alias_preserves_original_spelling(live_server):
    payload = example_request()
    payload["turnaround_time"] = payload.pop("turnaround_seconds")
    status, body = post_http(live_server, payload)
    assert status == 200
    assert "turnaround_seconds" not in body and body["turnaround_time"] == 3600
    assert_source_preserved(payload, body)
    payload["turnaround_seconds"] = 0
    status, body = post_http(live_server, payload)
    assert status == 409
    assert body["error_code"] == "alias_conflict"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_live_http_rejects_nonstandard_constants_in_metadata(live_server, constant):
    payload = example_request()
    payload["metadata"] = "replace-with-nonstandard-constant"
    raw_body = json.dumps(payload).replace('"replace-with-nonstandard-constant"', constant).encode("utf-8")
    status, body = post_raw_http(live_server, raw_body)
    assert status == 400
    assert "error" in body and constant not in json.dumps(body)
    assert "heats" not in body and "traceback" not in json.dumps(body).lower()


def test_nonstandard_json_legacy_parser_is_unchanged(monkeypatch):
    seen = []

    def legacy(payload):
        seen.append(payload)
        return 200, {"legacy": True}

    monkeypatch.setattr(SERVER, "allocate_preallocation", legacy)
    result = dispatch({"metadata": float("nan")}, "/api/v1/ladle-preallocation/allocate")
    assert result.status == 200 and result.body == {"legacy": True}
    assert len(seen) == 1


def test_new_route_body_limit_preserves_legacy_limits(monkeypatch):
    calls = []

    def record(payload):
        calls.append(payload["request_id"])
        return 200, {"request_id": payload["request_id"]}

    monkeypatch.setattr(SERVER, "allocate_ladles", record)
    payload = {"request_id": "x" * (70 * 1024)}
    new = dispatch(payload)
    assert new.status == 200 and calls == [payload["request_id"]]
    old = dispatch(payload, "/api/v1/ladle-preallocation/allocate")
    assert old.status == 400
    assert dispatch({}, length=2 * 1024 * 1024 + 1).status == 400
    assert dispatch({}, length=0).status == 400


def test_legacy_simulation_dispatch_remains_separate():
    handler = dispatch({"scenario_id": "unsupported"}, "/api/simulate")
    assert handler.status == 400
    assert "supported_scenario_ids" in handler.body
    missing = dispatch({}, "/api/v1/ladle-preallocation/does-not-exist")
    assert missing.status == 404


@pytest.mark.parametrize("status", [503, 500])
def test_http_preserves_calculation_failure_status(monkeypatch, status):
    monkeypatch.setattr(SERVER, "allocate_ladles", lambda payload: (status, {"error": "配包计算未完成"}))
    handler = dispatch(example_request())
    assert handler.status == status
    assert handler.body == {"error": "配包计算未完成"}


@pytest.mark.parametrize(
    ("exception_name", "expected_status", "expected_code"),
    [
        ("SolverUnavailableError", 503, "dependency_unavailable"),
        ("SearchIncompleteError", 503, "search_incomplete"),
        ("BindingConflictError", 409, "binding_conflict"),
        ("ReplayError", 500, "calculation_failed"),
    ],
)
def test_live_http_domain_failures_are_mapped_and_redacted(
    monkeypatch, live_server, exception_name, expected_status, expected_code
):
    from ladle_preallocation.ladle_only import errors

    def fail(request, policy):
        raise getattr(errors, exception_name)("private domain diagnostic")

    monkeypatch.setattr(ladle_only_api, "build_plan", fail)
    status, body = post_http(live_server, example_request())
    assert status == expected_status
    assert body["error_code"] == expected_code
    assert "private domain diagnostic" not in json.dumps(body)
    assert "traceback" not in json.dumps(body).lower()
    validator("OutputLadleOnlyError").validate(body)


def _oas_schema_to_json_schema(value):
    if isinstance(value, list):
        return [_oas_schema_to_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    converted = {
        key: _oas_schema_to_json_schema(item)
        for key, item in value.items()
        if key != "nullable"
    }
    if "$ref" in converted:
        converted["$ref"] = converted["$ref"].replace("#/components/schemas/", "#/$defs/")
    if value.get("nullable"):
        return {"anyOf": [converted, {"type": "null"}]}
    return converted


def openapi_document() -> dict:
    return yaml.safe_load((ROOT / "docs/ladle-preallocation-openapi.yaml").read_text(encoding="utf-8"))


def validator(name: str) -> jsonschema.Draft202012Validator:
    document = openapi_document()
    schema = {"$ref": f"#/$defs/{name}", "$defs": _oas_schema_to_json_schema(document["components"]["schemas"])}
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def test_openapi_preserves_paths_and_resolves_all_local_references():
    document = openapi_document()
    for path in [ROUTE, "/api/v1/ladle-preallocation/allocate", "/api/v1/ladle-preallocation/disturbances", "/api/simulate", "/api/scenarios", "/api/scenarios/summary"]:
        assert path in document["paths"]
    responses = document["paths"][ROUTE]["post"]["responses"]
    assert set(responses) == {"200", "400", "409", "422", "503", "500"}

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            reference = value.get("$ref")
            if reference is not None:
                assert reference.startswith("#/")
                target = document
                for part in reference[2:].split("/"):
                    target = target[part]
            for item in value.values():
                visit(item)

    visit(document)


@pytest.mark.parametrize("stem", ["ladle-only", "ladle-only-minimal", "ladle-only-partial", "ladle-only-wrapped"])
def test_published_request_response_and_schema_agree(stem):
    payload = json.loads((ROOT / f"docs/examples/{stem}-request.json").read_text(encoding="utf-8-sig"))
    wrapped = stem.endswith("wrapped")
    validator("InputLadleOnlyWrappedRequest" if wrapped else "InputLadleOnlyRequest").validate(payload)
    status, body = ladle_only_api.allocate_ladles(payload)
    assert status == (422 if stem.endswith("partial") else 200)
    validator("OutputLadleOnlyWrappedResponse" if wrapped else "OutputLadleOnlyResponse").validate(body)
    saved = json.loads((ROOT / f"docs/examples/{stem}-response.json").read_text(encoding="utf-8-sig"))
    assert saved == body
    if wrapped:
        assert_source_preserved(payload["data"], body["data"])
        assert body["trace"] == payload["trace"]
    else:
        assert_source_preserved(payload, body)


def test_canonical_schema_uses_approved_names_and_optional_metadata():
    payload = example_request()
    validator("InputLadleOnlyRequest").validate(payload)
    schema = openapi_document()["components"]["schemas"]["InputLadleOnlyRequest"]
    assert schema["required"] == ["schedule_start_at", "heats", "ladles"]
    assert schema["additionalProperties"] is True
    assert "request_id" not in schema["required"] and "casts" not in schema["required"]
    assert "plan_start_at" not in schema["properties"] and "solver_options" in schema["properties"]
    candidate = openapi_document()["components"]["schemas"]["InputLadleOnlyCandidate"]
    assert {"lining_material_code", "minor_repair_age_heats", "availability_status"} <= set(candidate["properties"])
    assert not {"material_code", "small_repair_age_heats", "status"} & set(candidate["properties"])
    heat = openapi_document()["components"]["schemas"]["InputLadleOnlyHeat"]
    assert "route" in heat["required"] and "operations" not in heat["properties"]
    payload["solver_options"] = {"seed": "metadata", "unknown": {"preserved": True}}
    payload["heats"][0]["seq"] = {"original": [1, None]}
    validator("InputLadleOnlyRequest").validate(payload)
    payload["turnaround_time"] = payload.pop("turnaround_seconds")
    validator("InputLadleOnlyRequest").validate(payload)
    payload["turnaround_time"] = True
    with pytest.raises(jsonschema.ValidationError):
        validator("InputLadleOnlyRequest").validate(payload)


def test_partial_response_and_failure_schema_agree():
    payload = example_request()
    payload["ladles"] = []
    status, body = ladle_only_api.allocate_ladles(payload)
    assert status == 422
    validator("OutputLadleOnlyResponse").validate(body)
    payload["heats"][0]["route"][0]["operation"] = "unsupported"
    status, error = ladle_only_api.allocate_ladles(payload)
    assert status == 400
    validator("OutputLadleOnlyError").validate(error)


def test_plan_fixture_is_explicitly_assumed_and_has_verified_id_set():
    fixture = json.loads((ROOT / "data/ladle_only_candidates_assumed.json").read_text(encoding="utf-8-sig"))
    expected = set("ST02 ST03 ST04 ST06 ST07 ST08 ST09 ST12 ST13 ST15 ST16 ST17 ST18 ST19 ST20 ST21 ST22 ST23 ST24 ST25 ST26 ST27 ST28 ST29 ST31 ST32 ST33 ST34 ST35 ST36 ST38 ST39 ST50 ST51 ST54 ST55".split())
    candidates = fixture["ladles"]
    assert len(candidates) == 36
    assert {candidate["ladle_id"] for candidate in candidates} == expected
    assert fixture["metadata"]["observed_fields"] == ["ladle_id"]
    assert "not an enterprise snapshot" in fixture["metadata"]["explanation"]
    candidate_validator = validator("InputLadleOnlyCandidate")
    six_fields = {"ladle_id", "lining_material_code", "minor_repair_age_heats", "major_repair_age_heats", "availability_status", "available_at"}
    for candidate in candidates:
        candidate_validator.validate(candidate)
        assert set(candidate) == six_fields
        assert candidate["lining_material_code"] == "T"
        assert candidate["availability_status"] == "available"
        assert candidate["minor_repair_age_heats"] == 10
