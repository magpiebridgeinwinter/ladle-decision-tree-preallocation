"""Strict internal model boundary and independently verified diagnostics."""

from copy import deepcopy
from datetime import datetime
import math

import pytest

from ladle_preallocation import ladle_only_api as api


def _seconds(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _ladle(identifier: str = "ST22") -> dict:
    return {
        "ladle_id": identifier, "status": "AVAILABLE",
        "available_at": "2026-10-30T08:00:00+08:00",
        "condition_code": "22A", "material_code": "DEMO_HIGH",
        "small_repair_age_heats": 10, "major_repair_age_heats": 50,
        "usage_count": 10, "nozzle_used_heats": 0,
        "slide_used_heats": 0, "frame_used_heats": 0, "argon_ready": True,
        "last_use": None, "reservations": [],
        "data_source": "assumed", "history_assumption": "clean",
    }


def _heat(identifier: str = "H1", machine: str = "M0", caster: str = "CC0",
          tapping: str = "08:20:00", finish: str = "09:00:00") -> dict:
    return {
        "heat_id": identifier, "grade": 2, "seq": 1,
        "operations": [
            {"operation": "BOF", "machine_id": machine},
            {"operation": "LF", "machine_id": "LF0"},
            {"operation": "CC", "machine_id": caster},
        ],
        "tap_finish_at": f"2026-10-30T{tapping}+08:00",
        "cast_finish_at": f"2026-10-30T{finish}+08:00",
    }


def _request() -> dict:
    return {
        "request_id": "plan-demo", "plan_start_at": "2026-10-30T08:00:00+08:00",
        "turnaround_seconds": 3600,
        "heats": [_heat(), _heat("H2", "M1", "CC1", "08:25:00", "09:05:00")],
        "casts": [{"cast_id": "cast0", "heat_ids": ["H1"]},
                  {"cast_id": "cast1", "heat_ids": ["H2"]}],
        "ladles": [_ladle(), _ladle("ST23")],
    }


def _reservation(start: str = "10:00:00", finish: str = "11:00:00", **extra) -> dict:
    return {
        "use_start_at": f"2026-10-30T{start}+08:00",
        "cast_finish_at": f"2026-10-30T{finish}+08:00",
        "turnaround_seconds": 0, **extra,
    }


def _result(assignments: dict | None = None, rejections: dict | None = None) -> dict:
    assignments = {"H1": "ST22", "H2": "ST23"} if assignments is None else assignments
    return {
        "assignments": assignments,
        "transitions": {key: {
            "before": {"ready_at": _seconds("2026-10-30T08:00:00+08:00"), "usage_count": 10},
            "after": {"ready_at": _seconds("2026-10-30T10:00:00+08:00"), "usage_count": 11},
            "rule_outcomes": [{"rule": "process", "outcome": "pass"}],
            "selection_reasons": ["qualified"],
        } for key in assignments},
        "rejections": rejections or {},
        "objectives": {"assigned_heats": len(assignments),
                       "distinct_ladles": len(set(assignments.values())), "preference": 0},
        "optimization_status": "optimal", "solver": {"phase_statuses": [
            {"objective": name, "status": "OPTIMAL", "proven": True}
            for name in ("assigned_heats", "distinct_ladles", "preference")
        ]},
        "assumptions": ["demo"], "validation": {"passed": True},
    }


def test_each_converter_advances_independently_and_preserves_input_order():
    request = _request()
    h3 = _heat("H3", "M0", "CC0", "08:40:00", "09:30:00")
    h4 = _heat("H4", "M1", "CC1", "08:50:00", "09:40:00")
    request["heats"] = [h4, request["heats"][1], h3, request["heats"][0]]
    request["casts"][0]["heat_ids"].append("H3")
    request["casts"][1]["heat_ids"].append("H4")
    original = deepcopy(request)
    normalized = api._normalize_model_request(request)
    by_id = {heat["heat_id"]: heat for heat in normalized["heats"]}
    anchor = _seconds(request["plan_start_at"])
    assert by_id["H1"]["use_start_at"] == by_id["H2"]["use_start_at"] == anchor
    assert by_id["H3"]["use_start_at"] == by_id["H1"]["tap_finish_at"]
    assert by_id["H4"]["use_start_at"] == by_id["H2"]["tap_finish_at"]
    assert [row["heat_id"] for row in normalized["heats"]] == ["H4", "H2", "H3", "H1"]
    assert request == original


def test_cast_first_is_from_cast_order_not_global_sequence():
    request = _request()
    request["heats"][1]["operations"][-1]["machine_id"] = "CC0"
    request["casts"] = [{"cast_id": "cast0", "heat_ids": ["H2", "H1"]}]
    normalized = api._normalize_model_request(request)
    assert [heat["is_cast_first"] for heat in normalized["heats"]] == [False, True]


@pytest.mark.parametrize("count,minutes", [(0, 100), (1, 160), (2, 290), (3, 360), (4, 420)])
def test_estimates_casting_finish_with_declared_route_count(count, minutes):
    request = _request()
    heat = request["heats"][0]
    heat["operations"] = [heat["operations"][0]] + [
        {"operation": "LF", "machine_id": f"LF{i}"} for i in range(count)
    ] + [heat["operations"][-1]]
    heat["cast_finish_at"] = None
    normalized = api._normalize_model_request(request)
    output = normalized["heats"][0]
    assert output["cast_finish_at"] == output["tap_finish_at"] + minutes * 60
    assert output["cast_finish_source"] == "estimated"
    assert any("casting_finish_estimated:H1" in item for item in normalized["assumptions"])


def test_explicit_zero_turnaround_is_preserved_for_heat_and_reservation():
    request = _request()
    request["turnaround_seconds"] = 0
    request["ladles"][0]["reservations"] = [_reservation()]
    normalized = api._normalize_model_request(request)
    assert normalized["turnaround_seconds"] == 0
    assert normalized["heats"][0]["ready_at"] == normalized["heats"][0]["cast_finish_at"]
    reservation = normalized["ladles"][0]["reservations"][0]
    assert reservation["ready_at"] == reservation["cast_finish_at"]


def test_absent_optional_facts_stay_unknown_and_history_needs_explicit_marker():
    request = _request()
    candidate = request["ladles"][0]
    del candidate["history_assumption"]
    del candidate["material_code"]
    candidate["small_repair_age_heats"] = None
    output = api._normalize_model_request(request)["ladles"][0]
    assert output["history_assumption"] == "unknown"
    assert output["material_code"] is None
    assert output["small_repair_age_heats"] is None


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(secret="do-not-echo"),
    lambda r: r["heats"][0].update(secret="do-not-echo"),
    lambda r: r["heats"][0]["operations"][0].update(secret="do-not-echo"),
    lambda r: r["casts"][0].update(secret="do-not-echo"),
    lambda r: r["ladles"][0].update(secret="do-not-echo"),
    lambda r: r["ladles"][0].update(last_use={"secret": "do-not-echo"}, history_assumption="unknown"),
    lambda r: r["ladles"][0].update(reservations=[{**_reservation(), "secret": "do-not-echo"}]),
    lambda r: r.update(confirmed_bindings=[{"heat_id": "H1", "ladle_id": "ST22", "secret": "do-not-echo"}]),
    lambda r: r.update(solver_options={"random_seed": 42}),
])
def test_unknown_fields_are_rejected_without_echoing_values(mutate):
    request = _request()
    mutate(request)
    status, body = api._allocate_model_ladles(request)
    assert status == 400
    assert body["error_code"] == "unknown_fields"
    assert "do-not-echo" not in str(body)


@pytest.mark.parametrize("field,value", [
    ("turnaround_seconds", True), ("turnaround_seconds", -1),
    ("turnaround_seconds", 1.0), ("turnaround_seconds", "3600"),
    ("heats", {}), ("casts", []), ("ladles", None), ("request_id", 17),
    ("plan_start_at", "2026-10-30T09:00:00+08:00"),
    ("plan_start_at", "2026-10-30 08:00:00+08:00"),
    ("plan_start_at", "2026-10-30T08:00:00"),
    ("plan_start_at", "2026-10-30T08:00:00.500+08:00"),
    ("plan_start_at", "2026-10-30T08:00:00-00:00"),
    ("plan_start_at", "2026-10-30T08:00:00+08:60"),
    ("plan_start_at", "2026-10-30T08:00:00+24:00"),
    ("plan_start_at", "2026-02-30T08:00:00+08:00"),
    ("snapshot_at", "2026-10-30T08:00:01+08:00"),
])
def test_top_level_invalid_types_and_times_are_bad_requests(field, value):
    request = _request()
    request[field] = value
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("field,value", [
    ("grade", True), ("grade", -1), ("grade", 2.5), ("grade", ""),
    ("seq", True), ("seq", -1), ("seq", 1.0),
    ("cast_finish_at", "2026-10-30T08:20:00+08:00"),
    ("tap_finish_at", "2026-10-30T08:00:00+08:00"),
])
def test_heat_field_validation(field, value):
    request = _request()
    request["heats"][0][field] = value
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("operations", [
    [{"operation": "BOF", "machine_id": "M0"}],
    [{"operation": "LF", "machine_id": "LF0"}, {"operation": "CC", "machine_id": "CC0"}],
    [{"operation": "BOF", "machine_id": "M0"}, {"operation": "CC", "machine_id": "CC0"}, {"operation": "CC", "machine_id": "CC0"}],
    [{"operation": " BOF ", "machine_id": "M0"}, {"operation": "CC", "machine_id": "CC0"}],
])
def test_process_route_has_exact_supported_operations(operations):
    request = _request()
    request["heats"][0]["operations"] = operations
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("field,value", [
    ("status", "available"), ("usage_count", True), ("nozzle_used_heats", -1),
    ("small_repair_age_heats", 1.5), ("argon_ready", 1),
    ("temperature_celsius", math.inf), ("temperature_celsius", math.nan),
    ("empty_weight_tonnes", -1), ("data_source", "PLAN"),
    ("history_assumption", "new"), ("material_code", ""),
])
def test_candidate_field_validation(field, value):
    request = _request()
    request["ladles"][0][field] = value
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("options", [
    {"time_limit_seconds": 0}, {"time_limit_seconds": 61}, {"time_limit_seconds": True},
    {"time_limit_seconds": 1.5}, {"max_deterministic_time": 0},
    {"max_deterministic_time": 61}, {"max_deterministic_time": math.inf},
])
def test_solver_budget_ranges(options):
    request = _request()
    request["solver_options"] = options
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("mutate", [
    lambda r: r["heats"][1].update(heat_id=" H1 "),
    lambda r: r["ladles"][1].update(ladle_id=" ST22 "),
    lambda r: r["heats"][1]["operations"][0].update(machine_id="M0") or r["heats"][1].update(tap_finish_at=r["heats"][0]["tap_finish_at"]),
    lambda r: r["casts"][1].update(cast_id="cast0"),
    lambda r: r["casts"][1].update(heat_ids=["H1"]),
    lambda r: r["casts"].pop(),
    lambda r: r["casts"][0].update(heat_ids=["external-heat"]),
    lambda r: r.update(casts=[{"cast_id": "cast0", "heat_ids": ["H1", "H2"]}]),
    lambda r: r.update(confirmed_bindings=[{"heat_id": "external-heat", "ladle_id": "ST22"}]),
    lambda r: r.update(confirmed_bindings=[{"heat_id": "H1", "ladle_id": "ST22"}] * 2),
    lambda r: r["ladles"][0].update(reservations=[_reservation(heat_id="H1")]),
    lambda r: r["ladles"][0].update(reservations=[_reservation(), _reservation("10:59:59", "12:00:00")]),
])
def test_identity_and_snapshot_conflicts_are_409(mutate):
    request = _request()
    mutate(request)
    assert api._allocate_model_ladles(request)[0] == 409


def test_reservation_touching_ready_boundary_is_valid_and_inherits_turnaround():
    request = _request()
    first = _reservation()
    del first["turnaround_seconds"]
    request["ladles"][0]["reservations"] = [first, _reservation("12:00:00", "13:00:00")]
    normalized = api._normalize_model_request(request)
    reservations = normalized["ladles"][0]["reservations"]
    assert reservations[0]["turnaround_seconds"] == 3600
    assert reservations[0]["ready_at"] == reservations[1]["use_start_at"]


def test_busy_ladle_may_describe_an_ongoing_service_without_future_available_history():
    request = _request()
    ladle = request["ladles"][0]
    ladle.update(status="BUSY", available_at="2026-10-30T10:00:00+08:00",
                 history_assumption="unknown", last_use={"grade": 1, "cast_finish_at": "2026-10-30T09:00:00+08:00"})
    assert api._normalize_model_request(request)["ladles"][0]["last_use"]["grade"] == 1
    ladle["status"] = "AVAILABLE"
    assert api._allocate_model_ladles(request)[0] == 409


@pytest.mark.parametrize("reservation_start", ["08:00:00", "09:59:59"])
def test_future_reservation_cannot_start_before_declared_initial_availability(monkeypatch, reservation_start):
    request = _request()
    request["ladles"][0].update(status="BUSY", available_at="2026-10-30T10:00:00+08:00",
                                reservations=[_reservation(reservation_start, "11:00:00")])
    called = []
    monkeypatch.setattr(api, "build_plan", lambda *_: called.append(True))
    status, body = api._allocate_model_ladles(request)
    assert status == 409
    assert body["error_code"] == "reservation_availability_conflict"
    assert body["field"] == "ladles[0].reservations[0].use_start_at"
    assert called == []


def test_reservation_at_initial_availability_and_ongoing_service_are_valid():
    request = _request()
    request["ladles"][0].update(status="BUSY", available_at="2026-10-30T10:00:00+08:00",
                                reservations=[_reservation("10:00:00", "11:00:00")])
    normalized = api._normalize_model_request(request)
    assert normalized["ladles"][0]["reservations"][0]["use_start_at"] == normalized["ladles"][0]["available_at"]
    request["ladles"][0]["reservations"] = [_reservation("07:30:00", "09:00:00", turnaround_seconds=3600)]
    assert api._normalize_model_request(request)["ladles"][0]["reservations"][0]["ready_at"] == normalized["ladles"][0]["available_at"]


@pytest.mark.parametrize("changes", [{"data_source": "provided"}, {"last_use": {}}])
def test_clean_history_marker_requires_explicit_empty_assumed_history(changes):
    request = _request()
    request["ladles"][0].update(changes)
    assert api._allocate_model_ladles(request)[0] == 400


def test_response_preserves_metadata_and_outputs_utc_state_times(monkeypatch):
    request = _request()
    request["heats"][0]["grade"] = " 2 "
    original = deepcopy(request)
    monkeypatch.setattr(api, "build_plan", lambda *_: _result())
    status, body = api._allocate_model_ladles(request)
    assert status == 200
    assert body["assignments"][0]["grade"] == " 2 "
    assert body["assignments"][0]["steel_profile"] == "DEMO_STEEL_HOT"
    assert body["assignments"][0]["operations"] == request["heats"][0]["operations"]
    assert body["assignments"][0]["use_deadline_at"] == "2026-10-30T00:00:00Z"
    assert body["assignments"][0]["state_transition"]["before"]["ready_at"] == "2026-10-30T00:00:00Z"
    assert body["execution"]["reservations_committed"] is False
    assert "history_assumed_clean:ST22" in body["assumptions"]
    assert request == original


def test_partial_response_keeps_all_rows_and_does_not_claim_infeasibility(monkeypatch):
    result = _result({"H1": "ST22"}, {"H2": [{"ladle_id": "ST22", "codes": ["not_ready"]}]})
    result["optimization_status"] = "feasible"
    monkeypatch.setattr(api, "build_plan", lambda *_: result)
    status, body = api._allocate_model_ladles(_request())
    assert status == 422
    assert body["status"] == "partial"
    assert [row["heat_id"] for row in body["assignments"]] == ["H1", "H2"]
    assert body["assignments"][1]["reason_codes"] == ["not_selected", "search_incomplete"]
    assert body["assignments"][1]["candidate_rejections"][0]["codes"] == ["not_ready"]
    assert body["assignments"][1]["next_available_at"] is None
    assert "无解" not in body["error"]


def test_feasible_partial_local_candidate_rejections_do_not_prove_total_infeasibility(monkeypatch):
    result = _result({"H1": "ST22"}, {"H2": [
        {"ladle_id": "ST22", "codes": ["not_ready"]},
        {"ladle_id": "ST23", "codes": ["first_cast_condition_mismatch"]},
    ]})
    result["optimization_status"] = "feasible"
    result["solver"]["phase_statuses"][0].update(status="FEASIBLE", proven=False)
    monkeypatch.setattr(api, "build_plan", lambda *_: result)
    status, body = api._allocate_model_ladles(_request())
    assert status == 422
    row = body["assignments"][1]
    assert row["reason_codes"] == ["first_cast_condition_mismatch", "not_ready", "search_incomplete"]
    assert row["candidate_rejections"] == result["rejections"]["H2"]


def test_empty_candidate_response_explains_every_unassigned_heat(monkeypatch):
    request = _request()
    request["ladles"] = []
    monkeypatch.setattr(api, "build_plan", lambda *_: _result({}))
    status, body = api._allocate_model_ladles(request)
    assert status == 422
    assert body["status"] == "unassigned"
    assert all(row["reason_codes"] == ["no_candidates"] for row in body["assignments"])


@pytest.mark.parametrize("name,status,code", [
    ("PolicyError", 503, "dependency_unavailable"),
    ("SolverUnavailableError", 503, "dependency_unavailable"),
    ("SearchIncompleteError", 503, "search_incomplete"),
    ("BindingConflictError", 409, "binding_conflict"),
    ("ReplayError", 500, "calculation_failed"),
])
def test_domain_errors_are_redacted_and_never_successful(monkeypatch, name, status, code):
    from ladle_preallocation.ladle_only import errors

    def fail(*_):
        raise getattr(errors, name)("secret input must never escape")

    monkeypatch.setattr(api, "build_plan", fail)
    actual_status, body = api._allocate_model_ladles(_request())
    assert actual_status == status
    assert body["error_code"] == code
    assert "secret" not in str(body)


def test_unknown_domain_identity_is_internal_failure(monkeypatch):
    monkeypatch.setattr(api, "build_plan", lambda *_: _result({"invented": "ST22"}))
    status, body = api._allocate_model_ladles(_request())
    assert status == 500
    assert "invented" not in str(body)


@pytest.mark.parametrize("mutate", [
    lambda result: result["validation"].update(passed=False),
    lambda result: result["objectives"].update(assigned_heats=999),
    lambda result: result["objectives"].update(distinct_ladles=999),
    lambda result: result.update(optimization_status="undocumented"),
])
def test_unverified_or_misreported_result_never_becomes_success(monkeypatch, mutate):
    result = _result()
    mutate(result)
    monkeypatch.setattr(api, "build_plan", lambda *_: result)
    assert api._allocate_model_ladles(_request())[0] == 500


@pytest.mark.parametrize("mutate", [
    lambda solver: solver.update(phase_statuses=[]),
    lambda solver: solver["phase_statuses"].pop(),
    lambda solver: solver["phase_statuses"][1].update(proven=False),
    lambda solver: solver["phase_statuses"][2].update(proven=1),
    lambda solver: solver["phase_statuses"][0].update(status="FEASIBLE"),
    lambda solver: solver["phase_statuses"][2].update(objective="distinct_ladles"),
])
def test_optimal_response_requires_three_genuinely_proven_objectives(monkeypatch, mutate):
    result = _result()
    mutate(result["solver"])
    monkeypatch.setattr(api, "build_plan", lambda *_: result)
    assert api._allocate_model_ladles(_request())[0] == 500


def test_domain_output_cannot_drop_a_confirmed_binding(monkeypatch):
    request = _request()
    request["confirmed_bindings"] = [{"heat_id": "H2", "ladle_id": "ST23"}]
    monkeypatch.setattr(api, "build_plan", lambda *_: _result({"H1": "ST22"}))
    assert api._allocate_model_ladles(request)[0] == 500


def test_collection_limits_reject_before_identity_scans():
    request = _request()
    request["heats"] = [_heat()] * 501
    assert api._allocate_model_ladles(request)[0] == 400
    request = _request()
    request["ladles"] = [_ladle()] * 201
    assert api._allocate_model_ladles(request)[0] == 400


@pytest.mark.parametrize("mutation,status", [
    (lambda r: r.update(turnaround_seconds=-1), 400),
    (lambda r: r["ladles"][1].update(ladle_id="ST22"), 409),
])
def test_parsed_request_identity_survives_input_and_conflict_errors(mutation, status):
    request = _request()
    mutation(request)
    actual_status, body = api._allocate_model_ladles(request)
    assert actual_status == status
    assert body["request_id"] == "plan-demo"


def test_giant_turnaround_rejected_before_date_or_solver_overflow():
    request = _request()
    request["turnaround_seconds"] = 10**100
    assert api._allocate_model_ladles(request)[0] == 400


def test_real_public_allocation_protects_scarce_candidate_and_replays():
    request = _request()
    request["heats"][0]["grade"] = 1
    request["ladles"][1]["material_code"] = "DEMO_STANDARD"
    original = deepcopy(request)
    status, body = api._allocate_model_ladles(request)
    assert status == 200
    assert {row["heat_id"]: row["ladle_id"] for row in body["assignments"]} == {"H1": "ST23", "H2": "ST22"}
    assert body["objectives"]["assigned_heats"] == 2
    assert body["objectives"]["distinct_ladles"] == 2
    assert body["validation"]["passed"] is True
    assert request == original


def test_real_unknown_steel_codes_are_preserved_and_not_defaulted():
    request = _request()
    for heat in request["heats"]:
        heat["grade"] = "enterprise-code-pending"
    status, body = api._allocate_model_ladles(request)
    assert status == 422
    assert all(row["grade"] == "enterprise-code-pending" and row["steel_profile"] is None for row in body["assignments"])
    assert all("unknown_steel_grade" in row["reason_codes"] for row in body["assignments"])


def test_real_missing_required_counter_is_not_assumed_qualified():
    request = _request()
    for ladle in request["ladles"]:
        del ladle["small_repair_age_heats"]
    status, body = api._allocate_model_ladles(request)
    assert status == 422
    assert all("missing_small_repair_age_heats" in row["reason_codes"] for row in body["assignments"])


def test_real_incompatible_confirmed_binding_is_conflict():
    request = _request()
    request["ladles"][1]["material_code"] = "DEMO_STANDARD"
    request["confirmed_bindings"] = [{"heat_id": "H2", "ladle_id": "ST23"}]
    status, body = api._allocate_model_ladles(request)
    assert status == 409
    assert body["error_code"] == "binding_conflict"
