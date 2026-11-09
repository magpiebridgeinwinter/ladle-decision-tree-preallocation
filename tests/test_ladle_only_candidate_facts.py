"""Candidate presence, policy provenance and confirmed-mode qualification."""

from __future__ import annotations

import copy

import pytest

from ladle_preallocation.ladle_only.candidate_facts import apply_candidate_fact_defaults
from ladle_preallocation.ladle_only.errors import PolicyError
from ladle_preallocation.ladle_only.optimizer import build_plan
from ladle_preallocation.ladle_only.policy import load_policy, validate_policy
from ladle_preallocation.ladle_only.rules import initial_state, parse_condition
from tests.test_ladle_only_domain import ORIGIN, heat, request


def candidate(**changes):
    result = {
        "ladle_id": "ST22", "material_code": "T", "major_repair_age_heats": 10,
        "small_repair_age_heats": 2, "status": "AVAILABLE", "available_at": ORIGIN,
    }
    result.update(changes)
    return result


def with_defaults(raw, policy, heats=None):
    enriched, sources = apply_candidate_fact_defaults(raw, policy)
    normalized = request(heats, [enriched])
    normalized["candidate_provenance"] = {raw["ladle_id"]: sources}
    return normalized, sources


def test_minimal_candidate_uses_versioned_defaults_and_individual_sources():
    raw, policy = candidate(), load_policy()
    before = copy.deepcopy(raw)
    normalized, sources = with_defaults(raw, policy, [heat(grade=2, first=True)])
    enriched = normalized["ladles"][0]
    assert {key: enriched[key] for key in raw} == raw
    assert raw == before
    assert "data_source" not in enriched
    assert policy["version"] == "assumed-steel-policy-v2"
    assert enriched["condition_code"] == "20A"
    assert enriched["usage_count"] == 2
    assert enriched["argon_ready"] is True
    assert all(enriched[field] == 0 for field in ("nozzle_used_heats", "slide_used_heats", "frame_used_heats"))
    assert all(sources[key] == "provided" for key in raw)
    assert all(sources[key] == "assumed" for key in policy["candidate_fact_defaults"])
    assert sources["history_assumption"] == "assumed"
    result = build_plan(normalized, policy)
    assert result["assignments"] == {"H1": "ST22"}
    assert result["optimization_status"] == "optimal"


def test_T_lining_is_preserved_and_independent_from_condition():
    policy = load_policy()
    normalized, sources = with_defaults(candidate(), policy)
    assert normalized["ladles"][0]["material_code"] == "T"
    assert sources["material_code"] == "provided"
    assert policy["lining_materials"]["T"] == {"name": "DEMO_T_LINING", "source": "assumed"}
    assert parse_condition("T") is None
    assert build_plan(normalized, policy)["assignments"] == {"H1": "ST22"}
    unknown, _ = with_defaults(candidate(material_code="UNMAPPED_MATERIAL"), policy)
    result = build_plan(unknown, policy)
    assert result["assignments"] == {}
    assert "material_mismatch" in result["rejections"]["H1"][0]["codes"]
    assert unknown["ladles"][0]["material_code"] == "UNMAPPED_MATERIAL"


@pytest.mark.parametrize("field,reason", [
    ("condition_code", "missing_condition"), ("usage_count", "missing_usage_count"),
    ("nozzle_used_heats", "missing_nozzle_used_heats"),
    ("slide_used_heats", "missing_slide_used_heats"), ("frame_used_heats", "missing_frame_used_heats"),
    ("argon_ready", "missing_argon_ready"),
])
def test_explicit_null_is_not_replaced_and_required_facts_exclude(field, reason):
    policy = load_policy()
    service = heat()
    service["operations"].insert(1, {"operation": "LF", "machine_id": "L0"})
    normalized, sources = with_defaults(candidate(**{field: None}), policy, [service])
    assert normalized["ladles"][0][field] is None
    assert sources[field] == "unknown"
    result = build_plan(normalized, policy)
    assert result["assignments"] == {}
    assert reason in result["rejections"]["H1"][0]["codes"]


def test_explicit_unknown_false_and_zero_are_authoritative():
    policy = load_policy()
    raw = candidate(status="UNKNOWN", condition_code="UNKNOWN", usage_count=0, argon_ready=False,
                    nozzle_used_heats=0, history_assumption="unknown", last_use=None)
    enriched, sources = apply_candidate_fact_defaults(raw, policy)
    assert all(enriched[key] == value for key, value in raw.items())
    assert sources["status"] == sources["condition_code"] == sources["history_assumption"] == "unknown"
    assert sources["argon_ready"] == sources["usage_count"] == sources["nozzle_used_heats"] == "provided"
    normalized, _ = with_defaults(raw, policy, [heat(grade=2, first=True)])
    result = build_plan(normalized, policy)
    assert "ladle_unavailable" in result["rejections"]["H1"][0]["codes"]


@pytest.mark.parametrize("field", ["small_repair_age_heats", "major_repair_age_heats"])
def test_required_repair_age_is_never_fabricated(field):
    raw, policy = candidate(), load_policy()
    del raw[field]
    normalized, sources = with_defaults(raw, policy)
    assert field not in normalized["ladles"][0] and field not in sources
    result = build_plan(normalized, policy)
    assert result["assignments"] == {}
    assert "missing_" + field in result["rejections"]["H1"][0]["codes"]


@pytest.mark.parametrize("field", ["ladle_id", "material_code", "status", "available_at"])
def test_basic_identity_material_and_availability_are_not_defaults(field):
    raw = candidate()
    del raw[field]
    enriched, sources = apply_candidate_fact_defaults(raw, load_policy())
    assert field not in enriched and field not in sources


@pytest.mark.parametrize("history", [
    {"last_use": None}, {"history_assumption": "unknown"},
    {"last_use": {"grade": None}}, {"last_use": None, "history_assumption": "unknown"},
])
def test_explicit_unknown_history_does_not_receive_assumed_clean(history):
    policy = load_policy()
    policy["profiles"]["2"]["allowed_previous_grades"] = ["2"]
    normalized, sources = with_defaults(candidate(**history), policy, [heat(grade=2)])
    assert sources.get("history_assumption") != "assumed"
    result = build_plan(normalized, policy)
    assert result["assignments"] == {}
    assert "missing_previous_steel" in result["rejections"]["H1"][0]["codes"]


def test_only_missing_history_can_use_assumed_clean_without_relabeling_candidate():
    policy = load_policy()
    policy["profiles"]["2"]["allowed_previous_grades"] = ["2"]
    normalized, sources = with_defaults(candidate(data_source="provided"), policy, [heat(grade=2)])
    assert normalized["ladles"][0]["data_source"] == "provided"
    assert sources["major_repair_age_heats"] == "provided"
    assert initial_state(normalized["ladles"][0], normalized, policy)["history_known"] is True
    assert build_plan(normalized, policy)["assignments"] == {"H1": "ST22"}


def test_confirmed_policy_adds_no_facts_and_missing_process_facts_exclude():
    policy, raw = load_policy(), candidate()
    policy["source"] = "confirmed"
    enriched, sources = apply_candidate_fact_defaults(raw, policy)
    assert enriched == raw and all(source == "provided" for source in sources.values())
    normalized, _ = with_defaults(raw, policy)
    result = build_plan(normalized, policy)
    assert result["assignments"] == {}
    assert "missing_condition" in result["rejections"]["H1"][0]["codes"]
    assert "missing_usage_count" in result["rejections"]["H1"][0]["codes"]


@pytest.mark.parametrize("field,value", [
    ("usage_count", True), ("frame_used_heats", -1), ("argon_ready", 1), ("condition_code", "T"),
])
def test_policy_rejects_invalid_candidate_defaults(field, value):
    policy = load_policy()
    policy["candidate_fact_defaults"][field] = value
    with pytest.raises(PolicyError):
        validate_policy(policy)


def test_policy_cannot_add_basic_repair_age_as_a_default():
    policy = load_policy()
    policy["candidate_fact_defaults"]["small_repair_age_heats"] = 0
    with pytest.raises(PolicyError):
        validate_policy(policy)


def test_T_acceptance_requires_an_explicit_lining_dictionary_entry():
    policy = load_policy()
    policy["lining_materials"] = {"OTHER": {"name": "other", "source": "assumed"}}
    with pytest.raises(PolicyError):
        validate_policy(policy)


def test_helper_does_not_mutate_nested_input_or_policy():
    raw = candidate(last_use={"grade": 1}, reservations=[{"metadata": {"note": "keep"}}])
    policy = load_policy()
    before_raw, before_policy = copy.deepcopy(raw), copy.deepcopy(policy)
    enriched, _ = apply_candidate_fact_defaults(raw, policy)
    enriched["last_use"]["grade"] = 2
    enriched["reservations"][0]["metadata"]["note"] = "changed"
    assert raw == before_raw and policy == before_policy
