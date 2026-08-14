from __future__ import annotations

from ladle_preallocation.disturbance import (
    CRANE_OFFLINE,
    FACILITY_UNAVAILABLE,
    LADLE_UNAVAILABLE,
    SCHEDULE_DEVIATION,
    DisturbanceSpec,
    inject_disturbance,
)
from ladle_preallocation.real_data.lifecycle import LifecycleManager
from ladle_preallocation.response import ResponsePath, TieredResponseController


def _scenario_data():
    heats = [
        {"heat_id": "H1", "required_grade": "5", "priority": 1, "window_start": 0, "window_end": 300, "pour_at": 300, "facility_id": "F1"},
        {"heat_id": "H2", "required_grade": "5", "priority": 2, "window_start": 0, "window_end": 500, "pour_at": 500, "facility_id": "F2"},
    ]
    ladles = [
        {"ladle_id": "L1", "grade": "5", "position_m": 1000, "weight_tonnes": 80, "age_seconds": 0},
        {"ladle_id": "L2", "grade": "5", "position_m": 2000, "weight_tonnes": 80, "age_seconds": 0},
    ]
    cranes = [{"crane_id": "C1", "position_m": 0, "current_load_tonnes": 0, "max_load_tonnes": 300, "speed_mps": 1000, "safe_distance_m": 0, "limit_0_m": 0, "limit_1_m": 5000}]
    assignments = [
        {"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1", "action": "assign", "expected_arrival_seconds": 1, "violations": ()},
        {"heat_id": "H2", "ladle_id": "L2", "crane_id": "C1", "action": "assign", "expected_arrival_seconds": 2, "violations": ()},
    ]
    return heats, ladles, cranes, assignments


def test_lifecycle_locks_assignments_and_keeps_audit_immutable():
    heats, _, _, assignments = _scenario_data()
    manager = LifecycleManager(heats)
    manager.apply_assignments(assignments, now=120, reason="window")
    manager.advance(300)
    manager.apply_assignments([{**assignments[0], "ladle_id": "L2"}], now=350, reason="disturbance")
    records = {row["heat_id"]: row for row in manager.records()}
    assert records["H1"]["state"] == "locked"
    assert records["H1"]["assignment"]["ladle_id"] == "L1"
    assert records["H2"]["state"] == "preallocated"


def test_event_time_budget_blocks_llm_after_deterministic_failure():
    heats, ladles, cranes, assignments = _scenario_data()
    calls = []
    scenario = inject_disturbance(
        DisturbanceSpec(CRANE_OFFLINE, "C1", occurred_at=250), heats, ladles, cranes, assignments,
    )
    controller = TieredResponseController(lambda *_args: calls.append(True) or (True, []))
    result, llm = controller.handle_disturbance(scenario)
    assert result.path == ResponsePath.FROZEN
    assert result.human_review_required is True
    assert llm is None
    assert calls == []


def test_controller_passes_optional_rag_context_to_rescheduler():
    heats, ladles, cranes, assignments = _scenario_data()
    captured = {}

    class Rescheduler:
        def reschedule(self, _heats, _ladles, _cranes, **kwargs):
            captured.update(kwargs)
            return False, []

    scenario = inject_disturbance(
        DisturbanceSpec(CRANE_OFFLINE, "C1", occurred_at=100), heats, ladles, cranes, assignments,
    )
    TieredResponseController(Rescheduler(), rag_context="安全规程上下文").handle_disturbance(scenario)
    assert captured["rag_context"] == "安全规程上下文"


def test_all_supported_disturbance_kinds_produce_auditable_scenarios():
    heats, ladles, cranes, assignments = _scenario_data()
    cases = [
        DisturbanceSpec(CRANE_OFFLINE, "C1", occurred_at=100),
        DisturbanceSpec(LADLE_UNAVAILABLE, "L1", occurred_at=100),
        DisturbanceSpec(FACILITY_UNAVAILABLE, "F1", occurred_at=100),
        DisturbanceSpec(SCHEDULE_DEVIATION, "H1", occurred_at=100, metadata={"delay_seconds": 120}),
    ]
    for spec in cases:
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.audit["event"]["kind"] == spec.kind
        assert scenario.num_affected >= 1
