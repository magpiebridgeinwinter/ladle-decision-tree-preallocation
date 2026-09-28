"""Auditable AP/AQ/AR benchmark for controlled disturbance scenarios."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from statistics import pvariance
from typing import Any, Iterable

from ladle_preallocation.disturbance.catalog import DISTURBANCE_KINDS
from ladle_preallocation.real_data.reader import read_plan


SCHEMA_VERSION = 1
METHOD_LABELS = {"decision_tree": "决策树", "llm": "Codex"}
RECOMMENDATION_LABELS = {
    "decision_tree": "决策树",
    "codex": "Codex",
    "tie": "持平",
    "human_review": "人工复核",
}
COMPARISON_ORDER = (
    ("completion_rate", "max"),
    ("on_time_rate", "max"),
    ("average_delay_seconds", "min"),
    ("max_delay_seconds", "min"),
    ("changed_heat_count", "min"),
    ("resource_change_count", "min"),
    ("crane_load_dispersion", "min"),
)


class BenchmarkContractError(ValueError):
    """Raised when experiment inputs cannot form a fair comparison."""


def _identifier(value: Any) -> str:
    return str(value or "").strip()


def _route(value: Any) -> str:
    return _identifier(value)


def _assignment_changed(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if left is None or right is None:
        return left is not right
    return any(
        _identifier(left.get(field)) != _identifier(right.get(field))
        for field in ("ladle_id", "crane_id")
    ) or _route(left.get("refining_route")) != _route(right.get("refining_route"))


def _transport_assignment_changed(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    """Compare the ladle/crane allocation while leaving route changes separate."""
    if left is None or right is None:
        return left is not right
    return any(
        _identifier(left.get(field)) != _identifier(right.get(field))
        for field in ("ladle_id", "crane_id")
    )


def _assignment_index(rows: Iterable[dict[str, Any]], label: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    for row in rows:
        heat_id = _identifier(row.get("heat_id"))
        if not heat_id:
            raise BenchmarkContractError(f"{label} contains an empty heat_id")
        if heat_id in indexed:
            duplicates.append(heat_id)
        indexed[heat_id] = deepcopy(row)
    return indexed, sorted(set(duplicates))


def load_factory_ladle_mapping(plan_path: str | Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Read valid factory ladle assignments from the source PLAN workbook."""
    path = Path(plan_path)
    rows = read_plan(path)
    mapping: dict[str, str] = {}
    invalid: list[dict[str, str]] = []
    duplicates: list[str] = []
    for row in rows:
        heat = _identifier(row.get("heat_id"))
        sequence = _identifier(row.get("plan_sequence"))
        if not heat or not sequence:
            continue
        heat_id = f"{heat}-{sequence}"
        ladle = _identifier(row.get("preallocated_ladle"))
        if not ladle:
            continue
        if not (ladle.startswith("ST") and ladle[2:].isdigit()):
            invalid.append({"heat_id": heat_id, "value": ladle})
            continue
        if heat_id in mapping and mapping[heat_id] != ladle:
            duplicates.append(heat_id)
            continue
        mapping[heat_id] = ladle
    if duplicates:
        raise BenchmarkContractError(f"factory PLAN has conflicting duplicate heats: {sorted(set(duplicates))}")
    return mapping, {
        "source": str(path),
        "plan_row_count": len(rows),
        "valid_factory_ladle_count": len(mapping),
        "invalid_factory_ladle_count": len(invalid),
        "invalid_factory_ladle_samples": invalid[:20],
    }


def _resource_is_unavailable(row: dict[str, Any]) -> bool:
    if row.get("available") is False or row.get("online") is False:
        return True
    status = _identifier(row.get("availability") or row.get("candidate_status") or row.get("status")).lower()
    return status in {"unavailable", "offline", "excluded", "maintenance", "scrapped", "damaged"}


def _branch_evaluation(
    record: dict[str, Any],
    stage: str,
    baseline: dict[str, dict[str, Any]],
    factory_ladles: dict[str, str],
) -> dict[str, Any]:
    response = record["responses"].get(stage)
    if response is None:
        raise BenchmarkContractError(f"{record['scenario_id']} is missing {stage} response")
    source_routes = {
        _identifier(row.get("heat_id")): _route(row.get("refining_route"))
        for row in record["inputs"].get("heats") or ()
    }
    response_rows = []
    for source_row in response.get("assignments") or ():
        row = deepcopy(source_row)
        if not _route(row.get("refining_route")):
            route = source_routes.get(_identifier(row.get("heat_id")))
            if route:
                row["refining_route"] = route
        response_rows.append(row)
    assignments, duplicate_ids = _assignment_index(response_rows, f"{record['scenario_id']}:{stage}")
    affected_ids = [_identifier(row.get("heat_id")) for row in record["inputs"]["heats"]]
    affected_set = set(affected_ids)
    returned_set = set(assignments)
    assigned_ids = {
        heat_id for heat_id, row in assignments.items()
        if row.get("action") == "assign"
    }
    validations = deepcopy(record.get("validations", {}).get(stage) or [])
    failed_validations = [
        _identifier(item.get("check_code")) or "unknown_check"
        for item in validations if not item.get("passed")
    ]
    impact_scope = record.get("audit", {}).get("impact_scope") or {}
    locked_ids = {_identifier(value) for value in impact_scope.get("excluded_locked_heat_ids") or ()}
    extra_ids = sorted(returned_set - affected_set)
    missing_ids = sorted(affected_set - returned_set)
    locked_changes = sorted(
        heat_id for heat_id in locked_ids
        if heat_id in assignments and _assignment_changed(baseline.get(heat_id), assignments[heat_id])
    )

    ladles = {_identifier(row.get("ladle_id")): row for row in record["inputs"]["ladles"]}
    cranes = {_identifier(row.get("crane_id")): row for row in record["inputs"]["cranes"]}
    unknown_resources: list[str] = []
    unavailable_resources: list[str] = []
    for heat_id in assigned_ids:
        row = assignments[heat_id]
        ladle_id = _identifier(row.get("ladle_id"))
        crane_id = _identifier(row.get("crane_id"))
        if ladle_id not in ladles:
            unknown_resources.append(f"ladle:{ladle_id or '<empty>'}")
        elif _resource_is_unavailable(ladles[ladle_id]):
            unavailable_resources.append(f"ladle:{ladle_id}")
        if crane_id not in cranes:
            unknown_resources.append(f"crane:{crane_id or '<empty>'}")
        elif _resource_is_unavailable(cranes[crane_id]):
            unavailable_resources.append(f"crane:{crane_id}")

    complete = (
        not duplicate_ids
        and not extra_ids
        and not missing_ids
        and len(assigned_ids) == len(affected_ids)
    )
    validation_passed = bool(validations) and not failed_validations
    scope_preserved = not extra_ids and not locked_changes
    resources_available = not unknown_resources and not unavailable_resources
    hard_gates = {
        "complete_assignment_set": {
            "passed": complete,
            "assigned": len(assigned_ids),
            "expected": len(affected_ids),
            "missing_heat_ids": missing_ids,
            "duplicate_heat_ids": duplicate_ids,
        },
        "shared_validation": {
            "passed": validation_passed,
            "failed_checks": failed_validations,
        },
        "locked_and_scope_preserved": {
            "passed": scope_preserved,
            "extra_heat_ids": extra_ids,
            "changed_locked_heat_ids": locked_changes,
        },
        "resources_available": {
            "passed": resources_available,
            "unknown_resources": sorted(set(unknown_resources)),
            "unavailable_resources": sorted(set(unavailable_resources)),
        },
    }
    executable = all(item["passed"] for item in hard_gates.values())

    changed_heat_ids: list[str] = []
    resource_change_count = 0
    route_change_count = 0
    factory_samples = 0
    factory_matches = 0
    crane_counts = Counter()
    for heat_id in affected_ids:
        branch = assignments.get(heat_id)
        base = baseline.get(heat_id)
        if _transport_assignment_changed(base, branch):
            changed_heat_ids.append(heat_id)
        if branch is not None:
            for field in ("ladle_id", "crane_id"):
                if _identifier(branch.get(field)) != _identifier((base or {}).get(field)):
                    resource_change_count += 1
            if _route(branch.get("refining_route")) != _route((base or {}).get("refining_route")):
                resource_change_count += 1
                route_change_count += 1
        if branch and branch.get("action") == "assign":
            crane_counts[_identifier(branch.get("crane_id"))] += 1
        factory_ladle = factory_ladles.get(heat_id)
        if factory_ladle:
            factory_samples += 1
            if branch and branch.get("action") == "assign" and _identifier(branch.get("ladle_id")) == factory_ladle:
                factory_matches += 1

    all_crane_counts = [crane_counts.get(crane_id, 0) for crane_id in sorted(cranes)]
    response_metrics = response.get("metrics") or {}
    metrics = {
        "completion_rate": len(assigned_ids) / len(affected_ids) if affected_ids else 0.0,
        "on_time_rate": float(response_metrics.get("on_time_rate", 0.0) or 0.0),
        "average_delay_seconds": float(response_metrics.get("average_delay_seconds", 0.0) or 0.0),
        "max_delay_seconds": float(response_metrics.get("max_delay_seconds", 0.0) or 0.0),
        "changed_heat_count": len(changed_heat_ids),
        "resource_change_count": resource_change_count,
        "route_change_count": route_change_count,
        "crane_load_dispersion": pvariance(all_crane_counts) if len(all_crane_counts) > 1 else 0.0,
        "hard_constraint_violation_count": sum(
            len(row.get("violations") or ()) for row in assignments.values()
        ),
        "human_review_rate": float(response_metrics.get("human_review_rate", 0.0) or 0.0),
        "decision_seconds": float(response_metrics.get("decision_seconds", response.get("elapsed_seconds", 0.0)) or 0.0),
        "factory_ladle_sample_count": factory_samples,
        "factory_ladle_match_count": factory_matches,
        "factory_ladle_agreement_rate": factory_matches / factory_samples if factory_samples else None,
    }
    return {
        "stage": stage,
        "method": METHOD_LABELS[stage],
        "path": response.get("path"),
        "executable": executable,
        "hard_gates": hard_gates,
        "failed_hard_gates": [name for name, result in hard_gates.items() if not result["passed"]],
        "metrics": metrics,
        "changed_heat_ids": changed_heat_ids,
        "assignments": assignments,
        "validations": validations,
    }


def recommend_branches(decision_tree: dict[str, Any], codex: dict[str, Any]) -> tuple[str, str]:
    """Choose one branch using hard gates and the documented metric order."""
    if decision_tree["executable"] != codex["executable"]:
        winner = "decision_tree" if decision_tree["executable"] else "codex"
        loser = codex if winner == "decision_tree" else decision_tree
        failed = ", ".join(loser["failed_hard_gates"])
        return winner, f"{RECOMMENDATION_LABELS[winner]}通过全部硬门槛；另一线路失败：{failed}"
    if not decision_tree["executable"]:
        return "human_review", "两条线路均未通过可执行性硬门槛"
    for metric, direction in COMPARISON_ORDER:
        left = float(decision_tree["metrics"][metric])
        right = float(codex["metrics"][metric])
        if abs(left - right) <= 1e-9:
            continue
        if direction == "max":
            winner = "decision_tree" if left > right else "codex"
        else:
            winner = "decision_tree" if left < right else "codex"
        return winner, f"两条线路均可执行，首个差异指标为 {metric}：决策树={left:g}，Codex={right:g}"
    return "tie", "两条线路在可执行性和排序指标上相同"


def _heat_rows(
    record: dict[str, Any],
    baseline: dict[str, dict[str, Any]],
    decision_tree: dict[str, Any],
    codex: dict[str, Any],
    factory_ladles: dict[str, str],
) -> list[dict[str, Any]]:
    heats = {_identifier(row.get("heat_id")): row for row in record["inputs"]["heats"]}
    rows: list[dict[str, Any]] = []
    for heat_id in heats:
        base = deepcopy(baseline[heat_id])
        source_heat = heats[heat_id]
        if not _route(base.get("refining_route")):
            base["refining_route"] = _route(source_heat.get("refining_route"))
        dt = decision_tree["assignments"].get(heat_id) or {}
        llm = codex["assignments"].get(heat_id) or {}
        if not _route(dt.get("refining_route")):
            dt = {**dt, "refining_route": _route(source_heat.get("refining_route")) or None}
        if not _route(llm.get("refining_route")):
            llm = {**llm, "refining_route": _route(source_heat.get("refining_route")) or None}
        factory_ladle = factory_ladles.get(heat_id)
        rows.append({
            "scenario_id": record["scenario_id"],
            "disturbance_kind": record["disturbance_kind"],
            "heat_id": heat_id,
            "factory_ladle_id": factory_ladle,
            "factory_comparison_available": factory_ladle is not None,
            "ap_ladle_id": base.get("ladle_id"),
            "ap_crane_id": base.get("crane_id"),
            "ap_refining_route": _route(base.get("refining_route")) or None,
            "ap_matches_factory_ladle": None if factory_ladle is None else _identifier(base.get("ladle_id")) == factory_ladle,
            "aq_action": dt.get("action"),
            "aq_ladle_id": dt.get("ladle_id"),
            "aq_crane_id": dt.get("crane_id"),
            "aq_refining_route": _route(dt.get("refining_route")) or None,
            "aq_changed_from_ap": _transport_assignment_changed(base, dt),
            "aq_matches_factory_ladle": None if factory_ladle is None else _identifier(dt.get("ladle_id")) == factory_ladle,
            "aq_violations": list(dt.get("violations") or ()),
            "ar_action": llm.get("action"),
            "ar_ladle_id": llm.get("ladle_id"),
            "ar_crane_id": llm.get("crane_id"),
            "ar_refining_route": _route(llm.get("refining_route")) or None,
            "ar_changed_from_ap": _transport_assignment_changed(base, llm),
            "ar_matches_factory_ladle": None if factory_ladle is None else _identifier(llm.get("ladle_id")) == factory_ladle,
            "ar_violations": list(llm.get("violations") or ()),
        })
    return rows


def _validate_matrix(records: list[dict[str, Any]], source_audit: dict[str, Any]) -> None:
    identifiers = [record.get("scenario_id") for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise BenchmarkContractError("benchmark contains duplicate scenario IDs")
    kinds = [_identifier(record.get("disturbance_kind")) for record in records]
    if len(records) != len(DISTURBANCE_KINDS) or set(kinds) != set(DISTURBANCE_KINDS):
        raise BenchmarkContractError("benchmark stress matrix does not exactly match the v1 disturbance catalog")
    if len(kinds) != len(set(kinds)):
        raise BenchmarkContractError("benchmark contains duplicate disturbance kinds")

    source_assignments, source_duplicates = _assignment_index(source_audit.get("assignments") or (), "source AP")
    if source_duplicates:
        raise BenchmarkContractError(f"source AP contains duplicates: {source_duplicates}")
    source_ladles = {_identifier(row.get("ladle_id")) for row in source_audit["scheduling_inputs"]["ladles"]}
    source_cranes = {_identifier(row.get("crane_id")) for row in source_audit["scheduling_inputs"]["cranes"]}
    for record in records:
        baseline, duplicates = _assignment_index(record["inputs"].get("baseline_assignments") or (), f"{record['scenario_id']}:AP")
        if duplicates:
            raise BenchmarkContractError(f"{record['scenario_id']} AP contains duplicates: {duplicates}")
        affected = {_identifier(row.get("heat_id")) for row in record["inputs"]["heats"]}
        if set(baseline) != affected:
            raise BenchmarkContractError(f"{record['scenario_id']} AP heat set differs from affected heat set")
        for heat_id, row in baseline.items():
            source = source_assignments.get(heat_id)
            if source is None or _assignment_changed(source, row):
                raise BenchmarkContractError(f"{record['scenario_id']} AP differs from location-aware source for {heat_id}")
            if _identifier(row.get("ladle_id")) not in source_ladles or _identifier(row.get("crane_id")) not in source_cranes:
                raise BenchmarkContractError(f"{record['scenario_id']} AP has untraceable resource for {heat_id}")


def build_benchmark(
    records: Iterable[dict[str, Any]],
    source_audit: dict[str, Any],
    factory_ladles: dict[str, str] | None = None,
    factory_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical cross-scenario benchmark result."""
    stress_records = [
        deepcopy(record) for record in records
        if record.get("category") == "llm_fallback_stress"
    ]
    _validate_matrix(stress_records, source_audit)
    factory = dict(factory_ladles or {})
    scenarios: list[dict[str, Any]] = []
    all_heat_rows: list[dict[str, Any]] = []
    source_routes = {
        _identifier(row.get("heat_id")): _route(row.get("refining_route"))
        for row in source_audit["scheduling_inputs"].get("heats") or ()
    }
    for record in sorted(stress_records, key=lambda item: item["scenario_id"]):
        baseline, _ = _assignment_index(record["inputs"]["baseline_assignments"], "AP")
        for heat_id, row in baseline.items():
            if not _route(row.get("refining_route")):
                row["refining_route"] = source_routes.get(heat_id, "")
        dt = _branch_evaluation(record, "decision_tree", baseline, factory)
        codex = _branch_evaluation(record, "llm", baseline, factory)
        recommendation, reason = recommend_branches(dt, codex)
        heat_rows = _heat_rows(record, baseline, dt, codex, factory)
        all_heat_rows.extend(heat_rows)
        factory_sample_count = sum(row["factory_comparison_available"] for row in heat_rows)
        ap_factory_matches = sum(row["ap_matches_factory_ladle"] is True for row in heat_rows)
        scenario = {
            "scenario_id": record["scenario_id"],
            "category": record["category"],
            "disturbance_kind": record["disturbance_kind"],
            "disturbance_group": record["disturbance_group"],
            "title": record["title"],
            "evidence_type": record["evidence_type"],
            "scenario_size_class": "primary_31_heat" if len(baseline) == 31 else "dynamic_local_window",
            "affected_heat_count": len(baseline),
            "source": deepcopy(record["source"]),
            "controlled_overrides": deepcopy(record["audit"].get("controlled_overrides") or {}),
            "external_api_called": bool(record["audit"].get("external_api_called")),
            "ap_baseline": list(baseline.values()),
            "branches": {"decision_tree": dt, "codex": codex},
            "recommendation": recommendation,
            "recommendation_label": RECOMMENDATION_LABELS[recommendation],
            "recommendation_reason": reason,
            "factory_comparison": {
                "ladle": {
                    "status": "available" if factory_sample_count else "not_available",
                    "sample_count": factory_sample_count,
                    "ap_match_count": ap_factory_matches,
                    "ap_agreement_rate": ap_factory_matches / factory_sample_count if factory_sample_count else None,
                    "aq_match_count": dt["metrics"]["factory_ladle_match_count"],
                    "aq_agreement_rate": dt["metrics"]["factory_ladle_agreement_rate"],
                    "ar_match_count": codex["metrics"]["factory_ladle_match_count"],
                    "ar_agreement_rate": codex["metrics"]["factory_ladle_agreement_rate"],
                },
                "crane": "not_available",
                "post_disturbance_manual_plan": "not_available",
                "execution_outcome": "not_available",
            },
            "heat_results": heat_rows,
        }
        scenarios.append(scenario)

    recommendation_counts = Counter(row["recommendation"] for row in scenarios)
    group_counts: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in scenarios:
        grouped[row["disturbance_group"]].append(row)
    for group, rows in sorted(grouped.items()):
        group_counts[group] = {
            "scenario_count": len(rows),
            "decision_tree_executable_count": sum(item["branches"]["decision_tree"]["executable"] for item in rows),
            "codex_executable_count": sum(item["branches"]["codex"]["executable"] for item in rows),
            "recommendation_counts": dict(Counter(item["recommendation"] for item in rows)),
        }

    factory_observations = [row for row in all_heat_rows if row["factory_comparison_available"]]
    factory_observation_count = len(factory_observations)
    factory_unique_heat_count = len({row["heat_id"] for row in factory_observations})
    factory_matches = {
        "ap": sum(row["ap_matches_factory_ladle"] is True for row in factory_observations),
        "aq": sum(row["aq_matches_factory_ladle"] is True for row in factory_observations),
        "ar": sum(row["ar_matches_factory_ladle"] is True for row in factory_observations),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": "location_aware_ap_dual_branch_v1",
        "source_audit": {
            "path": "outputs/real_data_location_aware/decision_tree_audit.json",
            "tree_version": source_audit.get("tree_version"),
            "heat_count": len(source_audit["scheduling_inputs"]["heats"]),
            "assignment_count": len(source_audit.get("assignments") or ()),
            "baseline_contract": source_audit.get("location", {}).get("baseline_contract", "location-aware-decision-tree-v1"),
        },
        "factory_reference": {
            **(factory_metadata or {}),
            "comparable_field": "preallocated_ladle",
            "unavailable_fields": {
                "factory_crane_assignment": "PLAN 未提供工厂天车任务",
                "post_disturbance_manual_plan": "未提供事故后人工重排记录",
                "execution_outcome": "未提供现场执行时间与验收结果",
            },
        },
        "evidence_boundary": {
            "source_backed": "PLAN、CRANE、loc_location、炉次和资源编号",
            "controlled": "20 类扰动状态、压缩窗口和部分路线策略",
            "codex": "离线审计候选方案，external_api_called=false",
            "claim_limit": "结果用于验证受控扰动下的求解可行性，不代表现场事故统计或人工替代结论",
        },
        "comparison_order": [name for name, _ in COMPARISON_ORDER],
        "summary": {
            "scenario_count": len(scenarios),
            "disturbance_kind_count": len({row["disturbance_kind"] for row in scenarios}),
            "primary_31_heat_scenario_count": sum(row["scenario_size_class"] == "primary_31_heat" for row in scenarios),
            "dynamic_local_window_scenario_count": sum(row["scenario_size_class"] == "dynamic_local_window" for row in scenarios),
            # Kept for older workbook consumers; new builds must not classify
            # dynamic windows as fixed two-heat fixtures.
            "focused_2_heat_scenario_count": sum(row["scenario_size_class"] == "focused_2_heat" for row in scenarios),
            "heat_observation_count": len(all_heat_rows),
            "unique_heat_count": len({row["heat_id"] for row in all_heat_rows}),
            "decision_tree_executable_count": sum(row["branches"]["decision_tree"]["executable"] for row in scenarios),
            "codex_executable_count": sum(row["branches"]["codex"]["executable"] for row in scenarios),
            "recommendation_counts": dict(recommendation_counts),
            "factory_ladle_observation_count": factory_observation_count,
            "factory_ladle_unique_heat_count": factory_unique_heat_count,
            "factory_ladle_match_count": factory_matches,
            "factory_ladle_agreement_rate": {
                key: value / factory_observation_count if factory_observation_count else None
                for key, value in factory_matches.items()
            },
            "group_results": group_counts,
        },
        "scenarios": scenarios,
    }


def scenario_csv_rows(benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    """Project canonical scenario results into a flat CSV contract."""
    rows: list[dict[str, Any]] = []
    for scenario in benchmark["scenarios"]:
        dt = scenario["branches"]["decision_tree"]
        codex = scenario["branches"]["codex"]
        row = {
            "scenario_id": scenario["scenario_id"],
            "disturbance_kind": scenario["disturbance_kind"],
            "disturbance_group": scenario["disturbance_group"],
            "title": scenario["title"],
            "scenario_size_class": scenario["scenario_size_class"],
            "affected_heat_count": scenario["affected_heat_count"],
            "external_api_called": scenario["external_api_called"],
            "recommendation": scenario["recommendation"],
            "recommendation_label": scenario["recommendation_label"],
            "recommendation_reason": scenario["recommendation_reason"],
            "factory_ladle_sample_count": scenario["factory_comparison"]["ladle"]["sample_count"],
            "ap_factory_ladle_agreement_rate": scenario["factory_comparison"]["ladle"]["ap_agreement_rate"],
        }
        for prefix, branch in (("aq", dt), ("ar", codex)):
            row[f"{prefix}_executable"] = branch["executable"]
            row[f"{prefix}_failed_hard_gates"] = ";".join(branch["failed_hard_gates"])
            for key, value in branch["metrics"].items():
                row[f"{prefix}_{key}"] = value
        rows.append(row)
    return rows


def heat_csv_rows(benchmark: dict[str, Any]) -> list[dict[str, Any]]:
    """Project canonical heat results into a flat CSV contract."""
    rows: list[dict[str, Any]] = []
    for scenario in benchmark["scenarios"]:
        for source in scenario["heat_results"]:
            row = deepcopy(source)
            row["aq_violations"] = ";".join(source["aq_violations"])
            row["ar_violations"] = ";".join(source["ar_violations"])
            rows.append(row)
    return rows
