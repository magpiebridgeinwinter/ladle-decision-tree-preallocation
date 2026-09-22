"""Single explainable decision-tree method for ladle pre-allocation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ladle_preallocation.data_modeling.grades import grade_matches
from ladle_preallocation.decision_tree.constraints import expected_arrival, validate_assignment
from ladle_preallocation.decision_tree.scoring import score_candidate
from ladle_preallocation.rules import evaluate_ladle_rules


@dataclass(frozen=True)
class DecisionTreeAssignment:
    heat_id: str
    ladle_id: str | None
    crane_id: str | None
    expected_arrival_seconds: float | None
    grade_match: bool
    reason: str
    violations: tuple[str, ...] = ()
    action: str = "unassigned"
    decision_path: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _required_missing(heat: dict[str, Any]) -> list[str]:
    return [field for field in ("heat_id", "required_grade") if heat.get(field) in (None, "")]


def allocate(
    heats: list[dict[str, Any]],
    ladles: list[dict[str, Any]],
    cranes: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> list[DecisionTreeAssignment]:
    """Run the documented tree nodes, then use shared validator as final authority."""
    base_loads = {str(c["crane_id"]): max(0.0, float(c.get("current_load_tonnes", 0) or 0)) for c in cranes}
    transported_loads = dict(base_loads)
    crane_positions = {str(c["crane_id"]): float(c.get("position_m", 0) or 0) for c in cranes}
    available = list(ladles)
    result: list[DecisionTreeAssignment] = []
    ordered_heats = sorted(
        heats,
        key=lambda h: (
            -float(h.get("priority", 0) or 0),
            float(h.get("window_start", float("inf")) or 0),
            str(h.get("heat_id", "")),
        ),
    )
    for heat in ordered_heats:
        missing = _required_missing(heat)
        if missing:
            result.append(DecisionTreeAssignment(str(heat.get("heat_id", "unknown")), None, None, None, False, "关键输入缺失，人工复核", action="request_human_review", decision_path=("input_complete:fail." + ".".join(missing),)))
            continue
        options: list[tuple[float, dict[str, Any], dict[str, Any], tuple[str, ...]]] = []
        rejected: list[str] = []
        for ladle in available:
            rules = evaluate_ladle_rules(heat, ladle)
            if not rules.feasible:
                rejected.extend(rules.violations)
                continue
            for crane in cranes:
                crane_id = str(crane["crane_id"])
                candidate_crane = {**crane, "position_m": crane_positions[crane_id]}
                errors = validate_assignment(heat, ladle, candidate_crane, base_loads)
                if errors:
                    rejected.extend(errors)
                    continue
                path = (
                    "input_complete:pass",
                    "ladle_state_repair_argon:pass",
                    "grade_age_weight_previous_grade:pass",
                    "crane_load_time_safety:pass",
                    "yellow_rule_score:" + ("warn." + ".".join(rules.warnings) if rules.warnings else "pass"),
                )
                options.append((score_candidate(heat, ladle, candidate_crane, transported_loads, available, weights), ladle, candidate_crane, path))
        if not options:
            action = "request_human_review" if not cranes or any(item.startswith("missing.") for item in rejected) else "unassigned"
            reason = "无可行候选：" + (",".join(sorted(set(rejected))) if rejected else "钢包或行车不可用")
            # Rejected candidates are diagnostic evidence, not violations of an applied assignment.
            result.append(DecisionTreeAssignment(str(heat["heat_id"]), None, None, None, False, reason, (), action, ("candidate_exhausted",)))
            continue
        _, ladle, crane, path = max(options, key=lambda item: item[0])
        crane_id = str(crane["crane_id"])
        transported_loads[crane_id] += max(0.0, float(ladle.get("weight_tonnes", 0) or 0))
        crane_positions[crane_id] = float(ladle.get("position_m", crane_positions[crane_id]) or crane_positions[crane_id])
        # No real-time ladle lifecycle is available. Treat a completed transport
        # as an immediate release, allowing the same ladle to serve the next heat.
        result.append(DecisionTreeAssignment(str(heat["heat_id"]), str(ladle["ladle_id"]), crane_id, expected_arrival(heat, ladle, crane), grade_matches(heat.get("required_grade"), ladle.get("grade")), "规则决策树→真实行车距离/作业均衡→硬约束终检→本次转运后钢包释放", (), "assign", path + ("crane_distance_and_workload:scored", "ladle_reuse:immediate_release",)))
    return result
