"""Load and validate the location-aware decision-tree audit contract."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


class LocationAwareAuditError(ValueError):
    """Raised when a replay is given an audit without mapped location inputs."""


def load_location_aware_audit(path: str | Path) -> dict[str, Any]:
    """Load one complete location-aware baseline and reject legacy audits.

    The returned value is a deep copy so disturbance builders can safely mutate
    their local event projection without changing the source evidence.
    """
    source_path = Path(path)
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocationAwareAuditError(f"无法读取位置映射审计: {source_path}") from exc
    if not isinstance(source, dict):
        raise LocationAwareAuditError("位置映射审计必须是 JSON 对象")
    if source.get("algorithm") != "decision_tree":
        raise LocationAwareAuditError("位置映射审计要求 algorithm=decision_tree")
    if not str(source.get("tree_version") or "").strip():
        raise LocationAwareAuditError("位置映射审计缺少 tree_version")

    location = source.get("location")
    mapping = location.get("mapping") if isinstance(location, dict) else None
    if not isinstance(location, dict) or not str(location.get("path") or "").strip() or not isinstance(mapping, dict):
        raise LocationAwareAuditError(
            "当前回放必须使用位置映射决策树审计；旧的未映射审计不可作为扰动基线"
        )

    inputs = source.get("scheduling_inputs")
    required_inputs = ("heats", "ladles", "cranes")
    if not isinstance(inputs, dict) or any(not isinstance(inputs.get(key), list) or not inputs[key] for key in required_inputs):
        raise LocationAwareAuditError("位置映射审计缺少完整 scheduling_inputs")
    assignments = source.get("assignments")
    if not isinstance(assignments, list) or not assignments:
        raise LocationAwareAuditError("位置映射审计缺少全量 baseline assignments")

    heat_ids = [str(row.get("heat_id") or "") for row in inputs["heats"]]
    assignment_ids = [str(row.get("heat_id") or "") for row in assignments]
    if not heat_ids or len(set(heat_ids)) != len(heat_ids):
        raise LocationAwareAuditError("位置映射审计的 heat_id 不完整或重复")
    if len(assignment_ids) != len(heat_ids) or set(assignment_ids) != set(heat_ids) or len(set(assignment_ids)) != len(assignment_ids):
        raise LocationAwareAuditError("位置映射审计必须为每个真实炉次保存且仅保存一条基线分配")

    ladle_ids = {str(row.get("ladle_id") or "") for row in inputs["ladles"]}
    crane_ids = {str(row.get("crane_id") or "") for row in inputs["cranes"]}
    if "" in ladle_ids or "" in crane_ids:
        raise LocationAwareAuditError("位置映射审计包含空钢包或行车编号")
    for row in assignments:
        if row.get("action") != "assign":
            continue
        if str(row.get("ladle_id") or "") not in ladle_ids or str(row.get("crane_id") or "") not in crane_ids:
            raise LocationAwareAuditError("位置映射审计存在无法追溯的基线资源")

    statuses = {str(row.get("location_mapping_status") or "") for row in inputs["ladles"]}
    if "legacy_fallback" in statuses:
        raise LocationAwareAuditError("禁止使用 legacy_fallback 钢包坐标作为扰动基线")
    mapped_ladles = {
        str(row.get("ladle_id")): row
        for row in inputs["ladles"]
        if row.get("location_mapping_status") == "mapped"
    }
    assigned_ladle_ids = {str(row.get("ladle_id")) for row in assignments if row.get("action") == "assign"}
    if not assigned_ladle_ids.issubset(mapped_ladles):
        raise LocationAwareAuditError("基线分配使用了缺少位置坐标的钢包")
    for ladle_id in assigned_ladle_ids:
        try:
            float(mapped_ladles[ladle_id]["position_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise LocationAwareAuditError(f"钢包 {ladle_id} 缺少有效位置坐标") from exc

    normalized = deepcopy(source)
    normalized.setdefault("location", {})["audit_path"] = str(source_path.resolve())
    normalized["location"]["baseline_contract"] = "location-aware-decision-tree-v1"
    normalized["location"]["algorithm_version"] = source["tree_version"]
    return normalized

