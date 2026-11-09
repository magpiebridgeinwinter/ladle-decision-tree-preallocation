"""Behavior checks for stateful fixed-plan ladle selection and proof status."""

from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import pytest

from ladle_preallocation.ladle_only.errors import BindingConflictError, PolicyError, ReplayError, SearchIncompleteError, SolverUnavailableError
from ladle_preallocation.ladle_only.optimizer import build_plan
from ladle_preallocation.ladle_only.policy import load_policy, validate_policy
from ladle_preallocation.ladle_only.rules import parse_condition, replay_plan

ORIGIN = 1_000_000


def heat(identifier="H1", *, start=0, finish=60, grade=1, first=False):
    return {"heat_id": identifier, "grade": grade, "seq": None,
            "operations": [{"operation": "BOF", "machine_id": "M0"}, {"operation": "CC", "machine_id": "C0"}],
            "use_start_at": ORIGIN + start * 60, "tap_finish_at": ORIGIN + (start + 5) * 60,
            "cast_finish_at": ORIGIN + finish * 60, "cast_finish_source": "provided",
            "cast_id": "cast0", "is_cast_first": first}


def ladle(identifier="ST22", **changes):
    result = {"ladle_id": identifier, "condition_code": "22A", "material_code": "DEMO_HIGH",
              "status": "AVAILABLE", "available_at": ORIGIN, "small_repair_age_heats": 10,
              "major_repair_age_heats": 50, "usage_count": 10, "nozzle_used_heats": 0,
              "slide_used_heats": 0, "frame_used_heats": 0, "argon_ready": True,
              "temperature_celsius": None, "last_use": None, "reservations": [],
              "data_source": "assumed", "history_assumption": "clean"}
    result.update(changes)
    return result


def request(heats=None, ladles=None, *, turnaround=0, bindings=None, options=None):
    return {"request_id": "domain-test", "plan_start_at": ORIGIN, "snapshot_at": ORIGIN,
            "turnaround_seconds": turnaround, "heats": heats or [heat()],
            "ladles": [ladle()] if ladles is None else ladles,
            "confirmed_bindings": bindings or {}, "solver_options": options or {"time_limit_seconds": 10, "max_deterministic_time": 5}}


def reservation(*, start, finish, grade=1, turnaround=0):
    return {"heat_id": "external", "grade": grade, "use_start_at": ORIGIN + start * 60,
            "cast_finish_at": ORIGIN + finish * 60, "turnaround_seconds": turnaround,
            "ready_at": ORIGIN + finish * 60 + turnaround}


def test_internal_mapping_and_condition_semantics():
    policy = load_policy()
    assert policy["profiles"]["2"]["name"] == "DEMO_STEEL_HOT"
    assert policy["casting_minutes"]["1"] == 160
    assert policy["casting_minutes"]["2"] == 290
    assert parse_condition("25F") == (5, "F")
    assert parse_condition("T7A") is None
    assert parse_condition("W3A") is None
    with pytest.raises(PolicyError):
        validate_policy({})


def test_policy_file_failure_is_redacted(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not-json-secret", encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        load_policy(path)
    assert "secret" not in str(error.value)


def test_solver_is_lazy_and_missing_dependency_is_explicit(monkeypatch):
    import ladle_preallocation.ladle_only.optimizer as optimizer
    def absent():
        raise SolverUnavailableError("unavailable")
    monkeypatch.setattr(optimizer, "_load_solver", absent)
    with pytest.raises(SolverUnavailableError):
        build_plan(request(), load_policy())


def test_scarce_candidate_is_protected():
    data = request([heat("H1", grade=1), heat("H2", grade=2)],
                   [ladle("ST22"), ladle("ST23", material_code="DEMO_STANDARD")])
    result = build_plan(data, load_policy())
    assert result["assignments"] == {"H1": "ST23", "H2": "ST22"}
    assert result["optimization_status"] == "optimal"
    assert result["objectives"]["assigned_heats"] == 2
    assert all(phase["proven"] for phase in result["solver"]["phase_statuses"])


def test_configurable_material_rank_and_large_usage_match_replay_score():
    policy = load_policy()
    policy["material_preference"] = {"DEMO_HIGH": 100, "DEMO_STANDARD": 101}
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20)],
                   [ladle("ST22", usage_count=1500), ladle("ST23", material_code="DEMO_STANDARD", usage_count=1500)])
    result = build_plan(data, policy)
    assert result["assignments"] == {"H1": "ST22", "H2": "ST22"}
    assert result["objectives"]["preference"] == -378001
    assert result["optimization_status"] == "optimal"
    assert result["transitions"]["H2"]["before"]["usage_count"] == 1501
    policy["material_preference"]["DEMO_HIGH"] = 1_000_001
    with pytest.raises(PolicyError):
        validate_policy(policy)


def test_reuse_at_ready_equality_and_one_second_early():
    second = heat("H2", start=90, finish=120)
    data = request([heat("H1"), second], turnaround=1800)
    result = build_plan(data, load_policy())
    assert len(result["assignments"]) == 2
    assert result["objectives"]["distinct_ladles"] == 1
    early = copy.deepcopy(data)
    early["heats"][1]["use_start_at"] -= 1
    assert build_plan(early, load_policy())["objectives"]["assigned_heats"] == 1


@pytest.mark.parametrize("field,initial", [("small_repair_age_heats", 33), ("major_repair_age_heats", 194),
                                            ("nozzle_used_heats", 14), ("slide_used_heats", 3), ("frame_used_heats", 99)])
def test_batch_consumption_exhausts_each_enabled_lifetime(field, initial):
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20)],
                   [ladle(**{field: initial})], bindings={"H1": "ST22"})
    result = build_plan(data, load_policy())
    assert result["assignments"] == {"H1": "ST22"}
    assert "exhausted_" + field in result["rejections"]["H2"][0]["codes"]


def test_missing_required_attributes_are_not_fabricated():
    result = build_plan(request(ladles=[ladle(small_repair_age_heats=None)]), load_policy())
    assert result["assignments"] == {}
    assert "missing_small_repair_age_heats" in result["rejections"]["H1"][0]["codes"]


def test_first_cast_disallows_new_or_repair_first_ladle():
    for candidate in [ladle(condition_code="20A", usage_count=0), ladle(condition_code="28A")]:
        result = build_plan(request([heat(first=True)], [candidate]), load_policy())
        assert not result["assignments"]
        assert "first_cast_new_ladle_forbidden" in result["rejections"]["H1"][0]["codes"]


def test_repair_first_then_second_then_hot_state_is_modeled_in_solver():
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20),
                    heat("H3", start=20, finish=30, grade=2)], [ladle(condition_code="28A")])
    result = build_plan(data, load_policy())
    assert len(result["assignments"]) == 3
    assert result["transitions"]["H1"]["before"]["condition_code"] == "28A"
    assert result["transitions"]["H2"]["before"]["condition_code"] == "27A"
    assert result["transitions"]["H3"]["before"]["condition_code"] == "20A"


def test_prior_steel_checks_immediately_preceding_use():
    policy = load_policy()
    policy["profiles"]["2"]["allowed_previous_grades"] = ["1"]
    data = request([heat("H1", finish=10, grade=2), heat("H2", start=10, finish=20, grade=1),
                    heat("H3", start=20, finish=30, grade=2)],
                   [ladle(last_use={"grade": 1, "cast_finish_at": ORIGIN - 1800}, history_assumption="unknown", data_source="provided")])
    result = build_plan(data, policy)
    assert len(result["assignments"]) == 3
    assert result["transitions"]["H3"]["before"]["previous_grade"] == 1


def test_unknown_history_needs_explicit_clean_assumption_for_enabled_rule():
    policy = load_policy()
    policy["profiles"]["2"]["allowed_previous_grades"] = ["2"]
    for changes in [{"data_source": "provided", "history_assumption": "unknown"}, {"history_assumption": "unknown"}]:
        result = build_plan(request([heat(grade=2)], [ladle(**changes)]), policy)
        assert not result["assignments"]
        assert "missing_previous_steel" in result["rejections"]["H1"][0]["codes"]
    assert build_plan(request([heat(grade=2)]), policy)["assignments"] == {"H1": "ST22"}


def test_future_reservation_preserves_earlier_available_gap():
    fixed = reservation(start=120, finish=130)
    result = build_plan(request([heat(finish=20)], [ladle(reservations=[fixed])]), load_policy())
    assert result["assignments"] == {"H1": "ST22"}


def test_external_turnaround_override_is_not_double_counted():
    data = request([heat(start=90, finish=100)],
                   [ladle(reservations=[reservation(start=20, finish=60, turnaround=0)])], turnaround=3600)
    assert build_plan(data, load_policy())["assignments"] == {"H1": "ST22"}
    data["ladles"][0]["reservations"] = [reservation(start=20, finish=60, turnaround=3600)]
    assert build_plan(data, load_policy())["assignments"] == {}


def test_future_reservation_consumes_life_and_changes_previous_steel():
    policy = load_policy()
    policy["profiles"]["1"]["allowed_previous_grades"] = ["2"]
    data = request([heat("H1", finish=10), heat("H2", start=30, finish=40)],
                   [ladle(reservations=[reservation(start=20, finish=30, grade=2)])])
    result = build_plan(data, policy)
    assert len(result["assignments"]) == 2
    before = result["transitions"]["H2"]["before"]
    assert before["usage_count"] == 12
    assert before["previous_grade"] == 2
    data["ladles"][0]["slide_used_heats"] = 2
    data["confirmed_bindings"] = {"H1": "ST22"}
    exhausted = build_plan(data, policy)
    assert exhausted["assignments"] == {"H1": "ST22"}
    assert "exhausted_slide_used_heats" in exhausted["rejections"]["H2"][0]["codes"]


def test_ongoing_reservation_is_not_counted_twice():
    fixed = reservation(start=-10, finish=30, turnaround=600)
    data = request([heat(start=40, finish=50)],
                   [ladle(status="BUSY", available_at=ORIGIN + 2400, reservations=[fixed])])
    result = build_plan(data, load_policy())
    assert result["transitions"]["H1"]["before"]["usage_count"] == 10
    assert result["transitions"]["H1"]["after"]["usage_count"] == 11


def test_reservation_completed_at_snapshot_supplies_history_without_counter_increment():
    policy = load_policy()
    policy["profiles"]["1"]["allowed_previous_grades"] = ["2"]
    data = request([heat()], [ladle(reservations=[reservation(start=-10, finish=0, grade=2)])])
    result = build_plan(data, policy)
    before = result["transitions"]["H1"]["before"]
    assert before["previous_grade"] == 2
    assert before["last_cast_finish_at"] == ORIGIN
    assert before["usage_count"] == 10
    assert before["thermal_source"] == "provided_history"
    assert result["transitions"]["H1"]["after"]["usage_count"] == 11


@pytest.mark.parametrize("previous_finish,expected_grade", [(-30, 2), (-10, 1)])
def test_completed_reservation_and_explicit_history_use_latest_completion(previous_finish, expected_grade):
    policy = load_policy()
    policy["profiles"]["1"]["allowed_previous_grades"] = [str(expected_grade)]
    data = request([heat()], [ladle(
        last_use={"grade": 1, "cast_finish_at": ORIGIN + previous_finish * 60},
        history_assumption="unknown", data_source="provided",
        reservations=[reservation(start=-25, finish=-20, grade=2)],
    )])
    result = build_plan(data, policy)
    before = result["transitions"]["H1"]["before"]
    assert before["previous_grade"] == expected_grade
    assert before["last_cast_finish_at"] == ORIGIN + max(previous_finish, -20) * 60
    assert before["usage_count"] == 10


def test_completed_reservation_with_unknown_grade_overrides_assumed_clean_history():
    policy = load_policy()
    policy["profiles"]["1"]["allowed_previous_grades"] = ["2"]
    data = request([heat()], [ladle(reservations=[reservation(start=-10, finish=0, grade=None)])])
    result = build_plan(data, policy)
    assert result["assignments"] == {}
    assert "missing_previous_steel" in result["rejections"]["H1"][0]["codes"]


def test_long_reservation_turnaround_retains_old_thermal_anchor_in_model():
    data = request([heat()], [ladle(reservations=[reservation(start=-310, finish=-300, turnaround=18000)])])
    result = build_plan(data, load_policy())
    assert result["assignments"] == {}
    assert result["optimization_status"] == "optimal"
    assert "thermal_condition_stopped" in result["rejections"]["H1"][0]["codes"]


def test_fixed_binding_is_hard_even_when_another_assignment_would_be_better():
    data = request([heat("H1", grade=1), heat("H2", grade=2)],
                   [ladle("ST22"), ladle("ST23", material_code="DEMO_STANDARD")], bindings={"H1": "ST22"})
    result = build_plan(data, load_policy())
    assert result["assignments"] == {"H1": "ST22"}
    assert result["solver"]["complete_allocation_proven_impossible"]


def test_incompatible_fixed_binding_is_proved_conflict():
    data = request([heat(grade=2)], [ladle(material_code="DEMO_STANDARD")], bindings={"H1": "ST22"})
    with pytest.raises(BindingConflictError):
        build_plan(data, load_policy())


def test_fixed_binding_can_require_preceding_unbound_state_changes():
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20),
                    heat("H3", start=20, finish=30, grade=2)], [ladle(condition_code="28A")], bindings={"H3": "ST22"})
    result = build_plan(data, load_policy())
    assert len(result["assignments"]) == 3
    assert result["assignments"]["H3"] == "ST22"


def test_initial_thermal_state_ages_even_without_previous_use_history():
    data = request([heat(start=600, finish=650, grade=2)])
    result = build_plan(data, load_policy())
    assert not result["assignments"]
    assert "thermal_condition_stopped" in result["rejections"]["H1"][0]["codes"]
    assert "initial_thermal_clock_estimated:ST22" in result["assumptions"]
    assert data["ladles"][0]["last_use"] is None


def test_confirmed_policy_requires_thermal_history_without_midpoint_estimate():
    policy = load_policy()
    policy["source"] = "confirmed"
    data = request([heat(grade=2)], [ladle(data_source="provided", history_assumption="unknown", last_use={"grade": 2})])
    result = build_plan(data, policy)
    assert result["assignments"] == {}
    assert "missing_thermal_history" in result["rejections"]["H1"][0]["codes"]
    assert "initial_thermal_clock_estimated:ST22" not in result["assumptions"]
    assert result["optimization_status"] == "optimal"


def test_confirmed_policy_completed_reservation_supplies_thermal_history():
    policy = load_policy()
    policy["source"] = "confirmed"
    policy["profiles"]["2"]["allowed_previous_grades"] = ["2"]
    data = request([heat(grade=2)], [ladle(data_source="provided", history_assumption="unknown",
                                          reservations=[reservation(start=-10, finish=0, grade=2)])])
    result = build_plan(data, policy)
    assert result["assignments"] == {"H1": "ST22"}
    before = result["transitions"]["H1"]["before"]
    assert before["thermal_source"] == "provided_history" and before["previous_grade"] == 2
    assert before["usage_count"] == 10


def test_confirmed_policy_future_reservation_can_enable_later_assignment():
    policy = load_policy()
    policy["source"] = "confirmed"
    data = request([heat("H1", finish=10), heat("H2", start=30, finish=40)],
                   [ladle(data_source="provided", history_assumption="unknown",
                          reservations=[reservation(start=20, finish=30)])])
    result = build_plan(data, policy)
    assert result["assignments"] == {"H2": "ST22"}
    assert result["transitions"]["H2"]["before"]["usage_count"] == 11
    assert "missing_thermal_history" in result["rejections"]["H1"][0]["codes"]
    assert result["optimization_status"] == "optimal"


def test_confirmed_repair_first_use_can_establish_history_for_normal_state():
    policy = load_policy()
    policy["source"] = "confirmed"
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20),
                    heat("H3", start=20, finish=30, grade=2)],
                   [ladle(condition_code="28A", data_source="provided", history_assumption="unknown")])
    result = build_plan(data, policy)
    assert len(result["assignments"]) == 3
    assert result["optimization_status"] == "optimal"
    assert result["transitions"]["H3"]["before"]["condition_code"] == "20A"


def test_confirmed_policy_does_not_accept_a_clean_history_assumption():
    policy = load_policy()
    policy["source"] = "confirmed"
    policy["profiles"]["1"]["allowed_previous_grades"] = ["2"]
    data = request([heat()], [ladle(condition_code="28A")])
    data["candidate_provenance"] = {"ST22": {"history_assumption": "assumed"}}
    result = build_plan(data, policy)
    assert result["assignments"] == {}
    assert "missing_previous_steel" in result["rejections"]["H1"][0]["codes"]


def test_unknown_steel_and_stopped_condition_have_explicit_reasons():
    result = build_plan(request([heat(grade=999)]), load_policy())
    assert result["rejections"]["H1"][0]["codes"] == ["unknown_steel_grade"]
    result = build_plan(request(ladles=[ladle(condition_code="T7A")]), load_policy())
    assert "unsupported_condition" in result["rejections"]["H1"][0]["codes"]


def test_independent_replay_rejects_identity_overlap_and_missing_binding():
    policy = load_policy()
    data = request([heat("H1"), heat("H2")])
    with pytest.raises(ReplayError):
        replay_plan(data, policy, {"unknown": "ST22"})
    with pytest.raises(ReplayError):
        replay_plan(data, policy, {"H1": "ST22", "H2": "ST22"})
    data["confirmed_bindings"] = {"H1": "ST22"}
    with pytest.raises(ReplayError):
        replay_plan(data, policy, {})


def test_budget_expiry_returns_verified_fallback_without_optimal_claim(monkeypatch):
    import ladle_preallocation.ladle_only.optimizer as optimizer
    times = iter([0.0] + [2.0] * 20)
    monkeypatch.setattr(optimizer.time, "perf_counter", lambda: next(times))
    data = request(options={"time_limit_seconds": 1, "max_deterministic_time": 5})
    result = build_plan(data, load_policy())
    assert result["assignments"] == {"H1": "ST22"}
    assert result["optimization_status"] == "feasible"
    assert not any(p["proven"] for p in result["solver"]["phase_statuses"])
    assert result["solver"]["fallback_used"]


def test_budget_expiry_cannot_drop_binding_or_claim_it_infeasible(monkeypatch):
    import ladle_preallocation.ladle_only.optimizer as optimizer
    times = iter([0.0] + [2.0] * 20)
    monkeypatch.setattr(optimizer.time, "perf_counter", lambda: next(times))
    monkeypatch.setattr(optimizer, "_initial_plan", lambda *_args: None)
    data = request(bindings={"H1": "ST22"}, options={"time_limit_seconds": 1, "max_deterministic_time": 5})
    with pytest.raises(SearchIncompleteError):
        build_plan(data, load_policy())


def test_input_and_policy_objects_remain_unchanged():
    policy = load_policy()
    data = request([heat("H1", finish=10), heat("H2", start=10, finish=20)])
    original_data, original_policy = copy.deepcopy(data), copy.deepcopy(policy)
    build_plan(data, policy)
    assert data == original_data
    assert policy == original_policy


@pytest.mark.parametrize("grades,starts", [([1, 2, 1], [0, 0, 70]), ([1, 1, 2], [0, 20, 80]),
                                           ([2, 1, 2], [0, 50, 100]), ([1, 2, 2], [0, 10, 70])])
def test_small_complete_enumeration_agrees_with_all_objective_levels(grades, starts):
    policy = load_policy()
    heats = [heat(f"H{i}", start=s, finish=s + 30, grade=g) for i, (g, s) in enumerate(zip(grades, starts))]
    data = request(heats, [ladle("ST22"), ladle("ST23", material_code="DEMO_STANDARD")])
    best = None
    for choices in itertools.product([None, "ST22", "ST23"], repeat=len(heats)):
        assignments = {h["heat_id"]: choice for h, choice in zip(heats, choices) if choice is not None}
        try:
            replay = replay_plan(data, policy, assignments, include_rejections=False)
        except ReplayError:
            continue
        objective = (-len(assignments), len(set(assignments.values())), -replay["preference"])
        best = objective if best is None or objective < best else best
    result = build_plan(data, policy)
    objectives = result["objectives"]
    assert (-objectives["assigned_heats"], objectives["distinct_ladles"], -objectives["preference"]) == best
    assert result["optimization_status"] == "optimal"
