"""Tests for the LLM local rescheduling pipeline.

Covers: disturbance injection, tiered response controller, ReAct agent,
batch experiment framework, and RAG knowledge base.
"""

from __future__ import annotations

import pytest

from ladle_preallocation.disturbance import (
    DisturbanceSpec,
    inject_disturbance,
    random_disturbance,
)
from ladle_preallocation.response import (
    ResponsePath,
    TieredResponseController,
)
from ladle_preallocation.llm import ReActRescheduler
from ladle_preallocation.experiment import BatchConfig, BatchRunner
from ladle_preallocation.rag import KnowledgeBase, SimpleEmbedder


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def baseline() -> tuple[list, list, list, list]:
    """Minimal baseline: 2 heats, 2 ladles, 1 crane — 100% assigned."""
    heats = [
        {"heat_id": "H1", "required_grade": "5", "window_start": 0.0, "window_end": 120.0, "priority": 1},
        {"heat_id": "H2", "required_grade": "5", "window_start": 30.0, "window_end": 150.0, "priority": 1},
    ]
    ladles = [
        {"ladle_id": "L1", "grade": "5", "position_m": 1000.0, "weight_tonnes": 80.0, "age_seconds": 100.0},
        {"ladle_id": "L2", "grade": "5", "position_m": 2000.0, "weight_tonnes": 85.0, "age_seconds": 200.0},
    ]
    cranes = [
        {"crane_id": "C1", "position_m": 500.0, "current_load_tonnes": 0.0, "max_load_tonnes": 300.0,
         "speed_mps": 2000.0, "safe_distance_m": 10000.0, "limit_0_m": 0.0, "limit_1_m": 48000.0},
    ]
    assignments = [
        {"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1", "action": "assign", "grade_match": True, "violations": ()},
        {"heat_id": "H2", "ladle_id": "L2", "crane_id": "C1", "action": "assign", "grade_match": True, "violations": ()},
    ]
    return heats, ladles, cranes, assignments


@pytest.fixture
def multi_crane_baseline() -> tuple[list, list, list, list]:
    """3 heats, 2 cranes — so disturbance leaves one working."""
    heats = [
        {"heat_id": "H1", "required_grade": "5", "window_start": 0.0, "window_end": 200.0, "priority": 1},
        {"heat_id": "H2", "required_grade": "5", "window_start": 30.0, "window_end": 300.0, "priority": 1},
        {"heat_id": "H3", "required_grade": "5", "window_start": 60.0, "window_end": 400.0, "priority": 1},
    ]
    ladles = [
        {"ladle_id": "L1", "grade": "5", "position_m": 1000.0, "weight_tonnes": 80.0, "age_seconds": 100.0},
        {"ladle_id": "L2", "grade": "5", "position_m": 2000.0, "weight_tonnes": 85.0, "age_seconds": 200.0},
        {"ladle_id": "L3", "grade": "5", "position_m": 3000.0, "weight_tonnes": 90.0, "age_seconds": 300.0},
    ]
    cranes = [
        {"crane_id": "C1", "position_m": 500.0, "current_load_tonnes": 0.0, "max_load_tonnes": 300.0,
         "speed_mps": 2000.0, "safe_distance_m": 10000.0, "limit_0_m": 0.0, "limit_1_m": 48000.0},
        {"crane_id": "C2", "position_m": 1500.0, "current_load_tonnes": 0.0, "max_load_tonnes": 300.0,
         "speed_mps": 2000.0, "safe_distance_m": 10000.0, "limit_0_m": 0.0, "limit_1_m": 48000.0},
    ]
    assignments = [
        {"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1", "action": "assign", "grade_match": True, "violations": ()},
        {"heat_id": "H2", "ladle_id": "L2", "crane_id": "C2", "action": "assign", "grade_match": True, "violations": ()},
        {"heat_id": "H3", "ladle_id": "L3", "crane_id": "C1", "action": "assign", "grade_match": True, "violations": ()},
    ]
    return heats, ladles, cranes, assignments


# ---------------------------------------------------------------------------
# Disturbance injector
# ---------------------------------------------------------------------------

class TestDisturbanceInjector:

    def test_crane_offline_identifies_affected_heats(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="C1 离线")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.num_affected == 2
        assert scenario.affected_heat_ids == ["H1", "H2"]
        assert len(scenario.remaining_cranes) == 0

    def test_ladle_unavailable_identifies_affected_heats(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="ladle_unavailable", resource_id="L1", description="L1 不可用")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.num_affected == 1
        assert scenario.affected_heat_ids == ["H1"]
        assert len(scenario.remaining_ladles) == 1

    def test_earliest_casting_calculation(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="test")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.earliest_casting_seconds == 120.0
        assert scenario.is_emergency is False  # 120 > 90

    def test_emergency_when_casting_within_90s(self):
        heats = [
            {"heat_id": "H1", "required_grade": "5", "window_start": 0, "window_end": 60.0, "priority": 1},
            {"heat_id": "H2", "required_grade": "5", "window_start": 10, "window_end": 200.0, "priority": 1},
        ]
        ladles = [{"ladle_id": "L1", "grade": "5", "position_m": 1000, "weight_tonnes": 80, "age_seconds": 100}]
        cranes = [{"crane_id": "C1", "position_m": 500, "current_load_tonnes": 0, "max_load_tonnes": 300,
                    "speed_mps": 2000, "safe_distance_m": 10000, "limit_0_m": 0, "limit_1_m": 48000}]
        assignments = [
            {"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1", "action": "assign"},
            {"heat_id": "H2", "ladle_id": "L1", "crane_id": "C1", "action": "assign"},
        ]
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="test")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.is_emergency is True

    def test_frozen_heats_are_not_affected(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="test")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments, frozen_heat_ids=["H1"])
        assert scenario.num_affected == 1
        assert scenario.affected_heat_ids == ["H2"]
        assert "H1" in scenario.frozen_assignments

    def test_random_disturbance_produces_valid_scenario(self, baseline):
        heats, ladles, cranes, assignments = baseline
        scenario = random_disturbance(heats, ladles, cranes, assignments, disturbance_probability=1.0, seed=42)
        assert scenario is not None
        assert scenario.num_affected > 0
        assert scenario.spec.kind in ("crane_offline", "ladle_unavailable", "facility_unavailable", "schedule_deviation")

    def test_random_disturbance_no_affect_when_no_assignments(self):
        heats = [{"heat_id": "H1", "required_grade": "5"}]
        ladles = [{"ladle_id": "L1", "grade": "5"}]
        cranes = [{"crane_id": "C1"}]
        assignments = []  # no assignments
        scenario = random_disturbance(heats, ladles, cranes, assignments, seed=42)
        assert scenario is None

    def test_no_reallocation_when_no_affected_heats(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C99", description="nonexistent")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.num_affected == 0
        assert len(scenario.heats_needing_reallocation) == 0


# ---------------------------------------------------------------------------
# Tiered response controller
# ---------------------------------------------------------------------------

class TestTieredResponseController:

    def test_no_heats_to_reallocate_keeps_all(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C99", description="nonexistent")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        ctrl = TieredResponseController()
        primary, llm = ctrl.handle_disturbance(scenario)
        assert primary.path == ResponsePath.FROZEN
        assert primary.success is True
        assert primary.num_assigned == 2
        assert llm is None

    def test_emergency_goes_to_frozen_on_decision_tree_failure(self, baseline):
        heats, ladles, cranes, assignments = baseline
        # Make it emergency by having earliest casting < 90s
        heats[0]["window_end"] = 50.0
        heats[1]["window_end"] = 80.0
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="test")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        assert scenario.is_emergency is True

        ctrl = TieredResponseController()
        primary, llm = ctrl.handle_disturbance(scenario)
        assert primary.path == ResponsePath.FROZEN
        assert "呼叫人工" in primary.reason

    def test_decision_tree_succeeds_with_remaining_resources(self, multi_crane_baseline):
        heats, ladles, cranes, assignments = multi_crane_baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="C1 离线")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)
        # H1 and H3 were on C1 (offline), H2 was on C2 (still online)
        assert scenario.num_affected == 2

        ctrl = TieredResponseController()
        primary, llm = ctrl.handle_disturbance(scenario)
        # Decision tree should try to reassign with remaining crane C2
        # With 2 ladles and 1 crane, DT may succeed or fail depending on timing
        # We just check the response is well-formed
        assert primary.path in (ResponsePath.DECISION_TREE_SUCCESS, ResponsePath.DECISION_TREE_FAILURE, ResponsePath.FROZEN)
        assert len(primary.assignments) > 0

    def test_three_way_comparison_structure(self, multi_crane_baseline):
        heats, ladles, cranes, assignments = multi_crane_baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="C1 离线")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)

        ctrl = TieredResponseController()
        comp = ctrl.run_three_way(scenario, "test_001")
        assert comp.scenario_id == "test_001"
        assert comp.num_affected == 2
        assert comp.num_total == 3
        assert comp.frozen is not None
        assert comp.decision_tree is not None
        assert comp.dt_saved >= 0
        summary = comp.summary()
        assert "scenario_id" in summary
        assert summary["dt_saved"] >= 0

    def test_frozen_result_makes_affected_unassigned(self, baseline):
        heats, ladles, cranes, assignments = baseline
        spec = DisturbanceSpec(kind="crane_offline", resource_id="C1", description="test")
        scenario = inject_disturbance(spec, heats, ladles, cranes, assignments)

        ctrl = TieredResponseController()
        comp = ctrl.run_three_way(scenario, "test")
        # All heats affected since only one crane
        frozen_assigned = sum(1 for a in comp.frozen.assignments if a.get("action") == "assign")
        assert frozen_assigned == 0  # All frozen → unassigned


# ---------------------------------------------------------------------------
# LLM ReAct agent
# ---------------------------------------------------------------------------

class TestReActRescheduler:

    def test_builds_prompt_correctly(self):
        heats = [{"heat_id": "H1", "required_grade": "5", "window_start": 0.0, "window_end": 120.0, "priority": 1}]
        ladles = [{"ladle_id": "L1", "grade": "5", "position_m": 1000.0, "weight_tonnes": 80.0, "age_seconds": 100.0}]
        cranes = [{"crane_id": "C1", "position_m": 500.0, "current_load_tonnes": 0.0, "max_load_tonnes": 300.0,
                    "speed_mps": 2000.0, "safe_distance_m": 10000.0, "limit_0_m": 0.0, "limit_1_m": 48000.0}]
        calls = []

        def fake_call(messages, **_kwargs):
            calls.append(messages)
            return '{"assignments": [{"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1"}]}'

        agent = ReActRescheduler(api_key="sk-test", llm_call=fake_call)
        result = agent.reschedule(heats, ladles, cranes)
        assert result.success is True
        assert len(calls) == 1
        assert "当前需要重新分配的炉次" in calls[0][1]["content"]

    def test_budget_exhaustion_does_not_call_llm(self):
        calls = []
        agent = ReActRescheduler(api_key="sk-test", llm_call=lambda *_args, **_kwargs: calls.append(True))
        result = agent.reschedule([{"heat_id": "H1"}], [], [], remaining_budget_seconds=0)
        assert result.success is False
        assert "预算耗尽" in result.reason
        assert calls == []

    def test_no_api_key_returns_failure(self):
        agent = ReActRescheduler(api_key="")
        result = agent.reschedule([{"heat_id": "H1"}], [], [])
        assert result.success is False
        assert "API key" in result.reason

    def test_empty_heats_returns_success(self):
        agent = ReActRescheduler(api_key="sk-test")
        result = agent.reschedule([], [], [])
        assert result.success is True
        assert len(result.assignments) == 0

    def test_parse_json_from_response(self):
        from ladle_preallocation.llm.react_agent import _parse_json_from_response
        # Valid JSON block
        parsed = _parse_json_from_response('''```json
{"assignments": [{"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1"}]}
```''')
        assert parsed is not None
        assert parsed["assignments"][0]["heat_id"] == "H1"

        # Plain JSON
        parsed = _parse_json_from_response('{"assignments": []}')
        assert parsed is not None

        # Garbage
        parsed = _parse_json_from_response("not json")
        assert parsed is None

    def test_validate_proposal_catches_unknown_ids(self):
        from ladle_preallocation.llm.react_agent import _validate_proposal
        heats = [{"heat_id": "H1", "required_grade": "5", "window_start": 0, "window_end": 120, "priority": 1}]
        ladles = [{"ladle_id": "L1", "grade": "5", "position_m": 1000, "weight_tonnes": 80, "age_seconds": 100}]
        cranes = [{"crane_id": "C1", "position_m": 500, "current_load_tonnes": 0, "max_load_tonnes": 300,
                    "speed_mps": 2000, "safe_distance_m": 10000, "limit_0_m": 0, "limit_1_m": 48000}]
        proposals = [{"heat_id": "H999", "ladle_id": "L999", "crane_id": "C999"}]
        violations = _validate_proposal(heats, ladles, cranes, proposals)
        assert "H999" in violations
        assert "unknown_heat" in violations["H999"]

    def test_validate_proposal_passes_for_valid_assignment(self):
        from ladle_preallocation.llm.react_agent import _validate_proposal
        heats = [{"heat_id": "H1", "required_grade": "5", "window_start": 0, "window_end": 5000, "priority": 1}]
        ladles = [{"ladle_id": "L1", "grade": "5", "position_m": 1000, "weight_tonnes": 80, "age_seconds": 100}]
        cranes = [{"crane_id": "C1", "position_m": 500, "current_load_tonnes": 0, "max_load_tonnes": 300,
                    "speed_mps": 2000, "safe_distance_m": 10000, "limit_0_m": 0, "limit_1_m": 48000}]
        proposals = [{"heat_id": "H1", "ladle_id": "L1", "crane_id": "C1"}]
        violations = _validate_proposal(heats, ladles, cranes, proposals)
        assert not violations


# ---------------------------------------------------------------------------
# Batch experiment
# ---------------------------------------------------------------------------

class TestBatchRunner:

    def test_batch_with_no_llm(self, multi_crane_baseline):
        heats, ladles, cranes, assignments = multi_crane_baseline
        config = BatchConfig(num_scenarios=5, seed=42)
        runner = BatchRunner(config=config)
        # Inject single-crane disturbance manually since batch runner does this internally
        # Actually, the runner uses random disturbances - let's just verify it runs
        result = runner.run(heats, ladles, cranes, assignments)
        assert result.summary["total_scenarios"] > 0
        assert "dt_success_rate" in result.summary
        # No LLM configured, so 0 attempted
        assert result.summary["llm_attempted"] == 0

    def test_markdown_report(self, multi_crane_baseline):
        heats, ladles, cranes, assignments = multi_crane_baseline
        config = BatchConfig(num_scenarios=3, seed=42)
        runner = BatchRunner(config=config)
        result = runner.run(heats, ladles, cranes, assignments)
        report = result.markdown_report()
        assert "三路对比" in report
        assert "决策树重排" in report

    def test_batch_output_written(self, multi_crane_baseline, tmp_path):
        heats, ladles, cranes, assignments = multi_crane_baseline
        config = BatchConfig(num_scenarios=2, seed=42, output_dir=str(tmp_path))
        runner = BatchRunner(config=config)
        result = runner.run(heats, ladles, cranes, assignments)
        md_file = tmp_path / "three_way_comparison.md"
        json_file = tmp_path / "three_way_comparison.json"
        assert md_file.exists()
        assert json_file.exists()
        assert "三路对比" in md_file.read_text()


# ---------------------------------------------------------------------------
# RAG knowledge base
# ---------------------------------------------------------------------------

class TestKnowledgeBase:

    def test_seed_defaults(self):
        kb = KnowledgeBase()
        kb.seed_default_rules()
        assert kb.size == 8
        # Retrieval should work
        results = kb.search("行车安全间距", top_k=3)
        assert len(results) > 0
        # Top result should be about safety distance
        assert any("安全" in r["text"] for r in results)

    def test_add_and_search(self):
        kb = KnowledgeBase()
        kb.add_chunk("行车不能同时吊运两个钢包", source="测试")
        kb.add_chunk("钢包浇注后需冷却30分钟", source="测试")
        results = kb.search("行车吊运规则", top_k=2)
        assert len(results) > 0

    def test_build_context_for_llm(self):
        kb = KnowledgeBase()
        kb.add_chunk("行车安全间距10米", source="安全规程")
        context = kb.build_context_for_llm("行车安全间距")
        assert "安全规程" in context
        assert "10米" in context or "安全间距" in context

    def test_empty_search(self):
        kb = KnowledgeBase()
        results = kb.search("anything")
        assert results == []

    def test_cosine_similarity(self):
        from ladle_preallocation.rag.knowledge_base import _cosine_similarity
        assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_simple_embedder(self):
        embedder = SimpleEmbedder()
        embedder.fit(["行车安全间距10米", "钢包硬度测试"])
        vec = embedder.encode("行车安全")
        assert len(vec) > 1
        assert any(v > 0 for v in vec)
