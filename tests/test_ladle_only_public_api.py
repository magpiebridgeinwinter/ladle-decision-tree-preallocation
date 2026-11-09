"""Approved protocol, lossless projection and public-to-model translations."""

from copy import deepcopy
import math

import pytest

from ladle_preallocation import ladle_only_api as api
from ladle_preallocation.ladle_only.policy import load_policy


def candidate(identifier="ST22", **extra):
    return {"ladle_id": identifier, "lining_material_code": "T",
            "minor_repair_age_heats": 12, "major_repair_age_heats": 68,
            "availability_status": "available", "available_at": "2026-10-30T08:00:00+08:00",
            **extra}


def heat(identifier="H0001", machine="M0", finish="08:40:00", **extra):
    return {"heat_id": identifier, "seq": "original-sequence", "grade": 2,
            "route": [{"operation": "BOF", "machine_id": machine},
                      {"operation": "LF", "machine_id": "M3"},
                      {"operation": "CC", "machine_id": "CC1"}],
            "tap_finish_at": f"2026-10-30T{finish}+08:00", **extra}


def request():
    return {"schedule_start_at": "2026-10-30T08:00:00+08:00", "turnaround_seconds": 3600,
            "heats": [heat()], "ladles": [candidate()]}


def without_allocations(payload):
    copy = deepcopy(payload)
    pending = [copy]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if isinstance(item.get("heats"), list):
                for row in item["heats"]:
                    row.pop("ladle_id", None)
                    row.pop("allocation_reason", None)
            pending.extend(value for value in item.values() if isinstance(value, (list, dict)))
        elif isinstance(item, list):
            pending.extend(value for value in item if isinstance(value, (list, dict)))
    return copy


def test_approved_minimal_request_enters_real_allocation_without_internal_fields():
    payload = request()
    original = deepcopy(payload)
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result == {**original, "heats": [{**original["heats"][0], "ladle_id": "ST22"}]}
    assert payload == original
    assert not any(key in result for key in ("request_id", "casts", "assignments", "solver", "assumptions"))


def test_public_normalization_keeps_provided_base_facts_and_field_provenance():
    normalized = api.normalize_ladle_only_request(request())
    ladle = normalized["ladles"][0]
    assert ladle["material_code"] == "T"
    assert ladle["small_repair_age_heats"] == 12
    assert ladle["major_repair_age_heats"] == 68
    assert ladle["status"] == "AVAILABLE"
    assert ladle["data_source"] == "provided"
    assert ladle["condition_code"] == "20A"
    assert ladle["usage_count"] == 2
    assert ladle["history_assumption"] == "clean"
    provenance = normalized["candidate_provenance"]["ST22"]
    assert provenance["small_repair_age_heats"] == "provided"
    assert provenance["condition_code"] == "assumed"
    assert provenance["history_assumption"] == "assumed"
    assert "candidate_fact_assumed:ST22:condition_code" in normalized["assumptions"]


def test_missing_cast_completion_is_estimated_only_inside_model():
    payload = request()
    normalized = api.normalize_ladle_only_request(payload)
    row = normalized["heats"][0]
    assert row["cast_finish_source"] == "estimated"
    assert row["cast_finish_at"] - row["tap_finish_at"] == 160 * 60
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert "cast_finish_at" not in result["heats"][0]
    payload["heats"][0]["cast_finish_at"] = None
    assert api.allocate_ladles(payload)[1]["heats"][0]["cast_finish_at"] is None


@pytest.mark.parametrize("seq", [None, "00042", {"order": 1}, ["stage", 2], 1.25, True])
def test_unconsumed_sequence_type_is_preserved(seq):
    payload = request()
    payload["heats"][0]["seq"] = seq
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["heats"][0]["seq"] == seq
    assert type(result["heats"][0]["seq"]) is type(seq)


def test_metadata_cannot_execute_solver_controls_and_every_extension_roundtrips():
    payload = request()
    payload.update(request_id={"foreign_id": 7}, machine_count=8,
                   solver_options={"time_limit_seconds": False, "random_seed": 999,
                                   "profiles": {"2": {"allow_everything": True}}},
                   extension={"arrival_at": "not-a-consumed-time", "type": [False, None, 1.5]})
    payload["heats"][0].update(upstream_tap_start_at="preserve-only", cast_id="cast-upstream",
                               quality={"must_keep": ["x", 2]})
    payload["heats"][0]["route"][1].update(sequence_on_machine="LF metadata", processing_minutes=19)
    payload["ladles"][0].update(enterprise_state={"sensor": None})
    normalized = api.normalize_ladle_only_request(payload)
    assert normalized["solver_options"] == {"time_limit_seconds": 10, "max_deterministic_time": 5.0}
    assert normalized["request_id"].startswith("ladle-")
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert without_allocations(result) == payload
    result["extension"]["type"].append("changed")
    assert len(payload["extension"]["type"]) == 3


@pytest.mark.parametrize("metadata_heats", ["caption", 42, None])
def test_nonarray_metadata_heats_is_not_mistaken_for_a_second_plan(metadata_heats):
    payload = request()
    payload["metadata"] = {"heats": metadata_heats, "origin": "unconsumed"}
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["metadata"] == payload["metadata"]
    assert without_allocations(result) == payload


@pytest.mark.parametrize("malformed_heats", ["caption", 42, None, {}])
def test_single_malformed_heats_field_still_has_a_public_type_error(malformed_heats):
    status, body = api.allocate_ladles({"wrapper": {"heats": malformed_heats}})
    assert status == 400
    assert body["field"] == "wrapper.heats"
    assert body["error_code"] == "invalid_input"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_metadata_is_rejected_as_invalid_json_with_its_original_path(value):
    payload = {"wrapper": request(), "extensions": {"sensor": [None, value]}}
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == "extensions.sensor[1]"
    assert "inf" not in str(body).lower()
    assert "nan" not in str(body).lower()


@pytest.mark.parametrize("extension", [(1, 2), {1: "not a JSON key"}, {"datetime": object()}])
def test_non_json_metadata_cannot_leave_a_nominally_successful_boundary(extension):
    payload = request()
    payload["extension"] = extension
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"].startswith("extension")


def test_wrappers_and_nearest_ancestor_configuration_are_preserved():
    payload = {"schedule_start_at": "2026-10-29T08:00:00+08:00", "turnaround_seconds": 999,
               "ladles": [], "message_type": "planning",
               "data": [{"schedule_start_at": "2026-10-30T08:00:00+08:00", "turnaround_time": 0,
                         "ladles": [candidate()], "wrapper_extension": 4,
                         "plan": {"heats": [heat()], "source": "scheduler"}}]}
    normalized = api.normalize_ladle_only_request(payload)
    assert normalized["turnaround_seconds"] == 0
    assert normalized["_plan_path"] == ("data", 0, "plan")
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["data"][0]["plan"]["heats"][0]["ladle_id"] == "ST22"
    assert without_allocations(result) == payload


@pytest.mark.parametrize("payload", [
    {"a": {"heats": []}, "b": {"heats": []}},
    {"heats": [], "metadata": {"heats": []}},
    {"data": [{"heats": []}, {"heats": []}]},
])
def test_multiple_heats_bearing_objects_are_rejected(payload):
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["error_code"] == "ambiguous_plan"


def test_sibling_configuration_is_not_used_for_nested_plan():
    payload = {"source": {"heats": [heat()]}, "sibling": request()}
    del payload["sibling"]["heats"]
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == "source.ladles"


def test_explicit_service_anchor_and_budgets_do_not_change_upstream_message():
    payload = request()
    del payload["schedule_start_at"]
    config = {"schedule_start_at": "2026-10-30T08:00:00+08:00",
              "solver_options": {"time_limit_seconds": 3, "max_deterministic_time": 2}}
    normalized = api.normalize_ladle_only_request(payload, service_config=config)
    assert normalized["solver_options"] == {"time_limit_seconds": 3, "max_deterministic_time": 2.0}
    status, result = api.allocate_ladles(payload, service_config=config)
    assert status == 200
    assert without_allocations(result) == payload
    assert "schedule_start_at" not in result


def test_no_server_date_is_inferred_for_missing_anchor():
    payload = request()
    del payload["schedule_start_at"]
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == "schedule_start_at"


@pytest.mark.parametrize("config", [None, [], {"random_seed": 17},
                                    {"solver_options": {"time_limit_seconds": 0}},
                                    {"solver_options": None}])
def test_invalid_service_configuration_is_not_blameable_client_metadata(config):
    if config is None:
        config = {"schedule_start_at": "not-a-time"}
    payload = request()
    if "schedule_start_at" in config:
        del payload["schedule_start_at"]
    status, body = api.allocate_ladles(payload, service_config=config)
    assert status == 503
    assert body["error_code"] == "dependency_unavailable"


@pytest.mark.parametrize("metadata", [None, [], "upstream control object", False])
def test_null_or_nonobject_solver_metadata_is_inert(metadata):
    payload = request()
    payload["solver_options"] = metadata
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["solver_options"] == metadata


@pytest.mark.parametrize("duration", [0, 3600])
def test_turnaround_alias_and_equal_dual_values_are_accepted_and_preserved(duration):
    payload = request()
    del payload["turnaround_seconds"]
    payload["turnaround_time"] = duration
    normalized = api.normalize_ladle_only_request(payload)
    assert normalized["turnaround_seconds"] == duration
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert "turnaround_seconds" not in result
    assert result["turnaround_time"] == duration
    payload["turnaround_seconds"] = duration
    assert without_allocations(api.allocate_ladles(payload)[1]) == payload


def test_conflicting_turnaround_alias_values_are_409():
    payload = request()
    payload["turnaround_time"] = 0
    status, body = api.allocate_ladles(payload)
    assert status == 409
    assert body["error_code"] == "alias_conflict"


@pytest.mark.parametrize("key,alias,good,bad", [
    ("lining_material_code", "material_code", "T", "DEMO_HIGH"),
    ("minor_repair_age_heats", "small_repair_age_heats", 12, 13),
    ("availability_status", "status", "AVAILABLE", "BUSY"),
    ("grade", "condition_code", "20A", "28A"),
])
def test_candidate_aliases_require_consistency(key, alias, good, bad):
    payload = request()
    if key == "grade":
        payload["ladles"][0][key] = good
    payload["ladles"][0][alias] = good
    assert api.allocate_ladles(payload)[0] == 200
    payload["ladles"][0][alias] = bad
    status, body = api.allocate_ladles(payload)
    assert status == 409
    assert body["field"] == "ladles[0]." + key


@pytest.mark.parametrize("availability,status", list(api.PUBLIC_AVAILABILITY.items()))
def test_public_availability_enum_is_translated_and_preserved(availability, status):
    payload = request()
    payload["ladles"][0]["availability_status"] = availability
    normalized = api.normalize_ladle_only_request(payload)
    assert normalized["ladles"][0]["status"] == status
    actual_status, result = api.allocate_ladles(payload)
    assert actual_status == (200 if availability in {"available", "occupied"} else 422)
    assert result["ladles"][0]["availability_status"] == availability


@pytest.mark.parametrize("mutation,field", [
    (lambda p: p.update(schedule_start_at="2026-10-30T09:00:00+08:00"), "schedule_start_at"),
    (lambda p: p.update(schedule_start_at="2026-10-30T08:00:00"), "schedule_start_at"),
    (lambda p: p.update(turnaround_seconds=True), "turnaround_seconds"),
    (lambda p: p["heats"][0].update(grade=True), "heats[0].grade"),
    (lambda p: p["heats"][0]["route"][0].update(operation="BOF "), "heats[0].route[0].operation"),
    (lambda p: p["heats"][0]["route"][0].update(machine_id=None), "heats[0].route[0].machine_id"),
    (lambda p: p["ladles"][0].update(minor_repair_age_heats=True), "ladles[0].minor_repair_age_heats"),
    (lambda p: p["ladles"][0].update(lining_material_code=""), "ladles[0].lining_material_code"),
    (lambda p: p["ladles"][0].update(availability_status="available "), "ladles[0].availability_status"),
])
def test_invalid_consumed_fields_use_public_paths(mutation, field):
    payload = request()
    mutation(payload)
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == field


def test_wrapped_private_validation_error_is_remapped_to_public_name():
    payload = {"message": request()}
    payload["message"]["heats"][0]["route"][-1]["operation"] = "LF"
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == "message.heats[0].route"
    assert "operations" not in body["error"]


def test_complete_explicit_bof_sequences_must_agree_with_tapping_order():
    payload = request()
    payload["heats"] = [heat("H2", finish="09:00:00"), heat("H1", finish="08:40:00")]
    payload["heats"][0]["route"][0]["sequence_on_machine"] = 8
    payload["heats"][1]["route"][0]["sequence_on_machine"] = 3
    normalized = api.normalize_ladle_only_request(payload)
    rows = {row["heat_id"]: row for row in normalized["heats"]}
    assert rows["H2"]["use_start_at"] == rows["H1"]["tap_finish_at"]
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert [row["heat_id"] for row in result["heats"]] == ["H2", "H1"]
    assert without_allocations(result) == payload
    payload["heats"][0]["route"][0]["sequence_on_machine"] = 1
    assert api.allocate_ladles(payload)[0] == 409


@pytest.mark.parametrize("sequence", [None, True, 0, -1, 1.0, "1"])
def test_explicit_bof_sequence_is_a_positive_integer(sequence):
    payload = request()
    payload["heats"][0]["route"][0]["sequence_on_machine"] = sequence
    status, body = api.allocate_ladles(payload)
    assert status == 400
    assert body["field"] == "heats[0].route[0].sequence_on_machine"


@pytest.mark.parametrize("second_sequence,code", [(None, "incomplete_converter_sequence"), (1, "duplicate_converter_sequence")])
def test_partial_or_duplicate_explicit_converter_sequence_is_a_conflict(second_sequence, code):
    payload = request()
    payload["heats"].append(heat("H2", finish="09:00:00"))
    payload["heats"][0]["route"][0]["sequence_on_machine"] = 1
    if second_sequence is not None:
        payload["heats"][1]["route"][0]["sequence_on_machine"] = second_sequence
    status, body = api.allocate_ladles(payload)
    assert status == 409
    assert body["error_code"] == code


def test_missing_casts_is_conservative_and_does_not_invent_source_groups():
    payload = request()
    payload["heats"].append(heat("H2", "M1", "08:35:00", cast_id="same-source-group"))
    normalized = api.normalize_ladle_only_request(payload)
    assert all(row["is_cast_first"] for row in normalized["heats"])
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert "casts" not in result
    assert "cast_id" not in result["heats"][0]
    assert result["heats"][1]["cast_id"] == "same-source-group"


def test_supplied_casts_and_nested_metadata_roundtrip_without_reformatting():
    payload = request()
    payload["heats"].append(heat("H2", "M1", "08:35:00"))
    payload["ladles"].append(candidate("ST23"))
    payload["casts"] = [{"cast_id": " original ", "heat_ids": ["H2", "H0001"], "upstream_order": {"confirmed": True}}]
    payload["heats"][0]["heat_id"] = " H0001 "
    normalized = api.normalize_ladle_only_request(payload)
    assert [row["is_cast_first"] for row in normalized["heats"]] == [False, True]
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert without_allocations(result) == payload


def test_original_non_null_ladle_id_is_a_hard_binding():
    payload = request()
    payload["ladles"].append(candidate("ST23"))
    payload["heats"][0]["ladle_id"] = "ST23"
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["heats"][0]["ladle_id"] == "ST23"
    payload["confirmed_bindings"] = [{"heat_id": "H0001", "ladle_id": "ST23", "external_note": "keep"}]
    assert without_allocations(api.allocate_ladles(payload)[1]) == without_allocations(payload)
    payload["confirmed_bindings"][0]["ladle_id"] = "ST22"
    status, body = api.allocate_ladles(payload)
    assert status == 409
    assert body["field"] == "heats[0].ladle_id"


def test_unknown_embedded_binding_reference_uses_original_heat_path():
    payload = request()
    payload["heats"][0]["ladle_id"] = "missing"
    status, body = api.allocate_ladles(payload)
    assert status == 409
    assert body["field"] == "heats[0].ladle_id"


def test_null_original_binding_can_be_allocated_and_stale_reason_is_removed():
    payload = request()
    payload["heats"][0].update(ladle_id=None, allocation_reason="old failure")
    status, result = api.allocate_ladles(payload)
    assert status == 200
    assert result["heats"][0]["ladle_id"] == "ST22"
    assert "allocation_reason" not in result["heats"][0]


def test_partial_and_empty_candidate_outputs_preserve_every_original_heat():
    payload = request()
    payload["heats"].append(heat("H2", "M1", "08:35:00"))
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert len(result["heats"]) == 2
    assert sum(row["ladle_id"] is not None for row in result["heats"]) == 1
    assert "allocation_reason" in next(row for row in result["heats"] if row["ladle_id"] is None)
    assert without_allocations(result) == payload
    payload["ladles"] = []
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert all(row["ladle_id"] is None and "no_candidates" in row["allocation_reason"] for row in result["heats"])


@pytest.mark.parametrize("field,value", [("condition_code", None), ("usage_count", 0),
                                         ("nozzle_used_heats", None), ("argon_ready", False),
                                         ("last_use", None), ("history_assumption", "unknown")])
def test_explicit_candidate_facts_are_not_replaced_by_assumed_defaults(field, value):
    payload = request()
    payload["ladles"][0][field] = value
    normalized = api.normalize_ladle_only_request(payload)
    assert normalized["ladles"][0][field] == value
    assert normalized["candidate_provenance"]["ST22"][field] != "assumed"
    if field == "last_use":
        assert normalized["ladles"][0]["history_assumption"] == "unknown"
    status, result = api.allocate_ladles(payload)
    assert status == (200 if field in {"last_use", "history_assumption"} else 422)
    assert result["ladles"][0][field] == value


def test_missing_age_is_an_exclusion_not_an_assumed_base_fact():
    payload = request()
    del payload["ladles"][0]["minor_repair_age_heats"]
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert "missing_small_repair_age_heats" in result["heats"][0]["allocation_reason"]
    assert "minor_repair_age_heats" not in result["ladles"][0]


def test_unknown_steel_is_preserved_with_a_necessary_reason():
    payload = request()
    payload["heats"][0]["grade"] = "enterprise pending"
    status, result = api.allocate_ladles(payload)
    assert status == 422
    assert result["heats"][0]["grade"] == "enterprise pending"
    assert "unknown_steel_grade" in result["heats"][0]["allocation_reason"]


def test_verified_feasible_partial_reason_reports_incomplete_search(monkeypatch):
    payload = request()
    payload["heats"].append(heat("H2", "M1", "08:35:00"))
    real_build = api.build_plan
    def incomplete(normalized, policy):
        result = real_build(normalized, policy)
        result["optimization_status"] = "feasible"
        result["solver"]["phase_statuses"][0]["proven"] = False
        return result
    monkeypatch.setattr(api, "build_plan", incomplete)
    status, result = api.allocate_ladles(payload)
    assert status == 422
    unassigned = next(row for row in result["heats"] if row["ladle_id"] is None)
    assert "search_incomplete" in unassigned["allocation_reason"]
    assert "不能" in unassigned["allocation_reason"]


def test_diagnostic_log_is_redacted_and_does_not_change_public_shape(caplog):
    import logging
    payload = request()
    payload["secret_foreign_metadata"] = "not-for-log"
    with caplog.at_level(logging.INFO, logger=api.__name__):
        status, result = api.allocate_ladles(payload)
    assert status == 200
    assert "policy=assumed-steel-policy-v2" in caplog.text
    assert "assigned=1 distinct=1 proof=optimal" in caplog.text
    assert "not-for-log" not in caplog.text
    assert without_allocations(result) == payload


@pytest.mark.parametrize("name,status,code", [
    ("PolicyError", 503, "dependency_unavailable"),
    ("SolverUnavailableError", 503, "dependency_unavailable"),
    ("SearchIncompleteError", 503, "search_incomplete"),
    ("BindingConflictError", 409, "binding_conflict"),
    ("ReplayError", 500, "calculation_failed"),
])
def test_public_errors_are_redacted_and_keep_established_shape(monkeypatch, name, status, code):
    from ladle_preallocation.ladle_only import errors
    def fail(*_):
        raise getattr(errors, name)("raw request must not escape")
    monkeypatch.setattr(api, "build_plan", fail)
    actual_status, body = api.allocate_ladles(request())
    assert actual_status == status
    assert body["error_code"] == code
    assert "raw request" not in str(body)
    assert "request_id" not in body


def test_domain_cannot_drop_an_existing_heat_binding(monkeypatch):
    payload = request()
    payload["heats"][0]["ladle_id"] = "ST22"
    real_build = api.build_plan
    def bad_plan(normalized, policy):
        result = real_build(normalized, policy)
        result["assignments"] = {}
        return result
    monkeypatch.setattr(api, "build_plan", bad_plan)
    assert api.allocate_ladles(payload)[0] == 500


def test_confirmed_policy_adds_no_missing_process_facts(monkeypatch):
    policy = load_policy()
    policy["source"] = "confirmed"
    monkeypatch.setattr(api, "load_policy", lambda: deepcopy(policy))
    normalized = api.normalize_ladle_only_request(request())
    assert normalized["ladles"][0]["condition_code"] is None
    assert normalized["ladles"][0]["usage_count"] is None
    status, result = api.allocate_ladles(request())
    assert status == 422
    assert result["heats"][0]["ladle_id"] is None


def test_root_limits_are_still_enforced_before_model_build():
    payload = request()
    payload["heats"] *= 501
    assert api.allocate_ladles(payload)[0] == 400
    payload = request()
    payload["ladles"] *= 201
    assert api.allocate_ladles(payload)[0] == 400
