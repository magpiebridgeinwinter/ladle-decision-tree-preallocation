"""Strict JSON boundary for transport-independent ladle preallocation.

Dates are normalized once to UTC integer seconds. The domain package owns
process policy, allocation and replay; this adapter never reserves resources.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
import math
import re
from typing import Any
from uuid import uuid4

from ladle_preallocation.ladle_only.policy import COUNTER_FIELDS


LOGGER = logging.getLogger(__name__)
PUBLIC_AVAILABILITY = {
    "available": "AVAILABLE", "occupied": "BUSY", "maintenance": "MAINTENANCE",
    "offline": "OFFLINE", "scrapped": "SCRAPPED", "unknown": "UNKNOWN",
}
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z"
)
STATUS_VALUES = {"AVAILABLE", "BUSY", "MAINTENANCE", "OFFLINE", "SCRAPPED", "UNKNOWN"}
REFINING_OPERATIONS = {"LF", "RH", "VD", "VOD"}
TOP_FIELDS = {
    "request_id", "plan_start_at", "snapshot_at", "turnaround_seconds", "heats",
    "casts", "ladles", "confirmed_bindings", "solver_options",
}
HEAT_FIELDS = {"heat_id", "grade", "seq", "operations", "tap_finish_at", "cast_finish_at"}
LADLE_FIELDS = {
    "ladle_id", "status", "available_at", "condition_code", "material_code",
    "small_repair_age_heats", "major_repair_age_heats", "usage_count",
    "nozzle_used_heats", "slide_used_heats", "frame_used_heats", "argon_ready",
    "temperature_celsius", "empty_weight_tonnes", "location_code",
    "empty_storage_location_code", "last_use", "history_assumption", "reservations",
    "data_source",
}
class LadleOnlyInputError(ValueError):
    """A malformed public field, described without its raw value."""

    def __init__(self, field: str, description: str, code: str = "invalid_input") -> None:
        super().__init__(f"{field}：{description}")
        self.field = field
        self.code = code


class LadleOnlyConflictError(ValueError):
    """A contradiction between snapshot records."""

    def __init__(self, field: str, description: str, code: str = "snapshot_conflict") -> None:
        super().__init__(f"{field}：{description}")
        self.field = field
        self.code = code


def load_policy() -> dict[str, Any]:
    """Load internal configuration lazily, without loading the solver."""
    from ladle_preallocation.ladle_only.policy import load_policy as domain_load_policy

    return domain_load_policy()


def build_plan(request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Keep the domain dependency lazy and independently replaceable in tests."""
    from ladle_preallocation.ladle_only.optimizer import build_plan as domain_build_plan

    return domain_build_plan(request, policy)


def _object(value: Any, field: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LadleOnlyInputError(field, "必须是对象")
    if set(value) - allowed:
        raise LadleOnlyInputError(field, "包含未支持的字段", "unknown_fields")
    return value


def _array(value: Any, field: str, *, minimum: int = 0, maximum: int = 500) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise LadleOnlyInputError(field, f"必须是含 {minimum} 至 {maximum} 项的数组")
    return value


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LadleOnlyInputError(field, "必须是非空字符串")
    return value.strip()


def _integer(value: Any, field: str, *, optional: bool = False,
             minimum: int = 0, maximum: int | None = None) -> int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise LadleOnlyInputError(field, f"必须是大于等于 {minimum} 的整数")
    if maximum is not None and value > maximum:
        raise LadleOnlyInputError(field, f"必须小于等于 {maximum}")
    return value


def _number(value: Any, field: str, *, optional: bool = False,
            minimum: float | None = None, maximum: float | None = None) -> float | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LadleOnlyInputError(field, "必须是有限数值")
    try:
        parsed = float(value)
    except (OverflowError, ValueError) as exc:
        raise LadleOnlyInputError(field, "必须是有限数值") from exc
    if not math.isfinite(parsed):
        raise LadleOnlyInputError(field, "必须是有限数值")
    if (minimum is not None and parsed < minimum) or (maximum is not None and parsed > maximum):
        raise LadleOnlyInputError(field, "数值超出允许范围")
    return parsed


def _grade(value: Any, field: str, *, optional: bool = False) -> int | str | None:
    if optional and value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise LadleOnlyInputError(field, "必须是非负整数或非空钢种编码字符串")


def _datetime(value: Any, field: str) -> tuple[datetime, int]:
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value) or value.endswith("-00:00"):
        raise LadleOnlyInputError(field, "必须是带已知时区的整秒 RFC3339 时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        seconds = int(parsed.astimezone(timezone.utc).timestamp())
    except (ValueError, OverflowError, OSError) as exc:
        raise LadleOnlyInputError(field, "时间格式或日期无效") from exc
    return parsed, seconds


def _timestamp(value: Any, field: str, *, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    return _datetime(value, field)[1]


def _future_time(start: int, duration: int, field: str) -> int:
    result = start + duration
    try:
        datetime.fromtimestamp(result, timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise LadleOnlyInputError(field, "计算后的时间超出支持的日期范围") from exc
    return result


def _enum(value: Any, field: str, values: set[str]) -> str:
    if not isinstance(value, str) or value not in values:
        raise LadleOnlyInputError(field, "必须使用约定的枚举值")
    return value


def _unique(identifier: str, seen: set[str], field: str) -> None:
    if identifier in seen:
        raise LadleOnlyConflictError(field, "标识重复", "duplicate_identity")
    seen.add(identifier)


def _normalize_model_request(payload: Any, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate the contract and derive per-converter times without mutation."""
    source = _object(payload, "request", TOP_FIELDS)
    policy = load_policy() if policy is None else policy
    request_id = _text(source.get("request_id"), "request_id")
    local_anchor, anchor = _datetime(source.get("plan_start_at"), "plan_start_at")
    if (local_anchor.hour, local_anchor.minute, local_anchor.second) != (8, 0, 0):
        raise LadleOnlyInputError("plan_start_at", "计划起点必须是所给时区的 08:00:00")
    snapshot = _timestamp(source.get("snapshot_at"), "snapshot_at", optional=True)
    snapshot = anchor if snapshot is None else snapshot
    if snapshot > anchor:
        raise LadleOnlyInputError("snapshot_at", "不能晚于计划起点")
    turnaround = _integer(source.get("turnaround_seconds"), "turnaround_seconds")
    raw_heats = _array(source.get("heats"), "heats", minimum=1)
    raw_ladles = _array(source.get("ladles"), "ladles", maximum=200)
    raw_casts = _array(source.get("casts"), "casts", minimum=1)
    solver = _object(source.get("solver_options", {}), "solver_options", {
        "time_limit_seconds", "max_deterministic_time",
    })
    defaults = policy.get("solver_defaults", {"time_limit_seconds": 10, "max_deterministic_time": 5})
    solver_options = {
        "time_limit_seconds": _integer(solver.get("time_limit_seconds", defaults["time_limit_seconds"]),
                                       "solver_options.time_limit_seconds", minimum=1, maximum=60),
        "max_deterministic_time": _number(solver.get("max_deterministic_time", defaults["max_deterministic_time"]),
                                          "solver_options.max_deterministic_time", minimum=0.001, maximum=60),
    }
    assumptions: list[str] = ["converter_first_start_08:00", "converter_interheat_preparation_seconds=0"]
    heats: list[dict[str, Any]] = []
    heat_ids: set[str] = set()
    converters: dict[str, list[dict[str, Any]]] = {}
    for index, raw in enumerate(raw_heats):
        context = f"heats[{index}]"
        raw = _object(raw, context, HEAT_FIELDS)
        heat_id = _text(raw.get("heat_id"), f"{context}.heat_id")
        _unique(heat_id, heat_ids, f"{context}.heat_id")
        grade = _grade(raw.get("grade"), f"{context}.grade")
        operations: list[dict[str, str]] = []
        for op_index, op in enumerate(_array(raw.get("operations"), f"{context}.operations", minimum=2, maximum=6)):
            op_context = f"{context}.operations[{op_index}]"
            op = _object(op, op_context, {"operation", "machine_id"})
            operations.append({
                "operation": _enum(op.get("operation"), f"{op_context}.operation", {"BOF", "CC"} | REFINING_OPERATIONS),
                "machine_id": _text(op.get("machine_id"), f"{op_context}.machine_id"),
            })
        if operations[0]["operation"] != "BOF" or operations[-1]["operation"] != "CC":
            raise LadleOnlyInputError(f"{context}.operations", "必须以 BOF 开始并以 CC 结束")
        if any(op["operation"] not in REFINING_OPERATIONS for op in operations[1:-1]):
            raise LadleOnlyInputError(f"{context}.operations", "中间工序必须是 LF、RH、VD 或 VOD")
        tapping = _timestamp(raw.get("tap_finish_at"), f"{context}.tap_finish_at")
        if tapping <= anchor:
            raise LadleOnlyInputError(f"{context}.tap_finish_at", "必须晚于计划起点")
        casting = _timestamp(raw.get("cast_finish_at"), f"{context}.cast_finish_at", optional=True)
        casting_source = "provided"
        if casting is None:
            minutes = policy["casting_minutes"][str(len(operations) - 2)]
            casting = _future_time(tapping, minutes * 60, f"{context}.cast_finish_at")
            casting_source = "estimated"
            assumptions.append(f"casting_finish_estimated:{heat_id}:{minutes}min")
        if casting <= tapping:
            raise LadleOnlyInputError(f"{context}.cast_finish_at", "必须晚于转炉完成时间")
        heat = {
            "heat_id": heat_id, "grade": grade,
            "seq": _integer(raw.get("seq"), f"{context}.seq", optional=True),
            "operations": operations, "tap_finish_at": tapping, "cast_finish_at": casting,
            "cast_finish_source": casting_source,
            "ready_at": _future_time(casting, turnaround, "turnaround_seconds"),
        }
        heats.append(heat)
        converters.setdefault(operations[0]["machine_id"], []).append(heat)
    for group in converters.values():
        previous = anchor
        for heat in sorted(group, key=lambda row: row["tap_finish_at"]):
            if heat["tap_finish_at"] == previous:
                raise LadleOnlyConflictError("heats.tap_finish_at", "同一转炉存在相同完成时间", "ambiguous_converter_order")
            heat["use_start_at"] = previous
            previous = heat["tap_finish_at"]
    by_heat = {row["heat_id"]: row for row in heats}
    cast_ids: set[str] = set()
    cast_heat_ids: set[str] = set()
    casts: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_casts):
        context = f"casts[{index}]"
        raw = _object(raw, context, {"cast_id", "heat_ids"})
        cast_id = _text(raw.get("cast_id"), f"{context}.cast_id")
        _unique(cast_id, cast_ids, f"{context}.cast_id")
        members: list[str] = []
        machines: set[str] = set()
        for member in _array(raw.get("heat_ids"), f"{context}.heat_ids", minimum=1):
            member = _text(member, f"{context}.heat_ids")
            if member not in by_heat:
                raise LadleOnlyConflictError(f"{context}.heat_ids", "引用了请求外炉次", "unknown_heat_reference")
            _unique(member, cast_heat_ids, f"{context}.heat_ids")
            heat = by_heat[member]
            heat["cast_id"] = cast_id
            heat["is_cast_first"] = not members
            machines.add(heat["operations"][-1]["machine_id"])
            members.append(member)
        if len(machines) != 1:
            raise LadleOnlyConflictError(f"{context}.heat_ids", "同一浇次必须使用同一连铸机", "cast_machine_conflict")
        casts.append({"cast_id": cast_id, "heat_ids": members})
    if cast_heat_ids != heat_ids:
        raise LadleOnlyConflictError("casts", "浇次分组必须覆盖每个请求炉次", "incomplete_cast_partition")
    ladles: list[dict[str, Any]] = []
    ladle_ids: set[str] = set()
    reservation_ids: set[str] = set()
    for index, raw in enumerate(raw_ladles):
        context = f"ladles[{index}]"
        raw = _object(raw, context, LADLE_FIELDS)
        ladle_id = _text(raw.get("ladle_id"), f"{context}.ladle_id")
        _unique(ladle_id, ladle_ids, f"{context}.ladle_id")
        status = _enum(raw.get("status"), f"{context}.status", STATUS_VALUES)
        available = _timestamp(raw.get("available_at"), f"{context}.available_at")
        data_source = _enum(raw.get("data_source", "provided"), f"{context}.data_source", {"provided", "assumed"})
        history_assumption = _enum(raw.get("history_assumption", "unknown"), f"{context}.history_assumption", {"unknown", "clean"})
        last_raw = raw.get("last_use")
        if history_assumption == "clean" and (data_source != "assumed" or last_raw is not None):
            raise LadleOnlyInputError(f"{context}.history_assumption", "clean 仅适用于显式假设数据且 last_use 为空")
        last_use = None
        if last_raw is not None:
            last_raw = _object(last_raw, f"{context}.last_use", {"heat_id", "grade", "cast_finish_at"})
            last_use = {
                "heat_id": _text(last_raw.get("heat_id"), f"{context}.last_use.heat_id", optional=True),
                "grade": _grade(last_raw.get("grade"), f"{context}.last_use.grade", optional=True),
                "cast_finish_at": _timestamp(last_raw.get("cast_finish_at"), f"{context}.last_use.cast_finish_at", optional=True),
            }
            last_finish = last_use["cast_finish_at"]
            if last_finish is not None and (last_finish > available or last_finish > snapshot and status != "BUSY"):
                raise LadleOnlyConflictError(f"{context}.last_use.cast_finish_at", "上次使用时间与快照可用状态矛盾", "history_time_conflict")
            if last_use["heat_id"] in heat_ids:
                raise LadleOnlyConflictError(f"{context}.last_use.heat_id", "上次使用不能同时是本请求待配炉次", "history_heat_conflict")
        ladle = {
            "ladle_id": ladle_id, "status": status, "available_at": available,
            "data_source": data_source, "history_assumption": history_assumption,
            "last_use": last_use,
        }
        for field in COUNTER_FIELDS:
            ladle[field] = _integer(raw.get(field), f"{context}.{field}", optional=True)
        for field in ("condition_code", "material_code", "location_code", "empty_storage_location_code"):
            ladle[field] = _text(raw.get(field), f"{context}.{field}", optional=True)
        ladle["temperature_celsius"] = _number(raw.get("temperature_celsius"), f"{context}.temperature_celsius", optional=True)
        ladle["empty_weight_tonnes"] = _number(raw.get("empty_weight_tonnes"), f"{context}.empty_weight_tonnes", optional=True, minimum=0)
        argon = raw.get("argon_ready")
        if argon is not None and not isinstance(argon, bool):
            raise LadleOnlyInputError(f"{context}.argon_ready", "必须是布尔值或 null")
        ladle["argon_ready"] = argon
        reservations: list[dict[str, Any]] = []
        for res_index, res in enumerate(_array(raw.get("reservations", []), f"{context}.reservations")):
            res_context = f"{context}.reservations[{res_index}]"
            res = _object(res, res_context, {"heat_id", "grade", "use_start_at", "cast_finish_at", "turnaround_seconds"})
            res_id = _text(res.get("heat_id"), f"{res_context}.heat_id", optional=True)
            if res_id is not None:
                if res_id in heat_ids:
                    raise LadleOnlyConflictError(f"{res_context}.heat_id", "外部预约不能重复本请求炉次", "reservation_heat_conflict")
                _unique(res_id, reservation_ids, f"{res_context}.heat_id")
            start = _timestamp(res.get("use_start_at"), f"{res_context}.use_start_at")
            finish = _timestamp(res.get("cast_finish_at"), f"{res_context}.cast_finish_at")
            duration = _integer(res.get("turnaround_seconds", turnaround), f"{res_context}.turnaround_seconds")
            if finish <= start:
                raise LadleOnlyInputError(f"{res_context}.cast_finish_at", "必须晚于预约开始时间")
            if snapshot <= start < available:
                raise LadleOnlyConflictError(f"{res_context}.use_start_at", "未来预约早于钢包快照可用时间", "reservation_availability_conflict")
            reservations.append({
                "heat_id": res_id, "grade": _grade(res.get("grade"), f"{res_context}.grade", optional=True),
                "use_start_at": start, "cast_finish_at": finish,
                "turnaround_seconds": duration,
                "ready_at": _future_time(finish, duration, f"{res_context}.turnaround_seconds"),
            })
        reservations.sort(key=lambda row: row["use_start_at"])
        for previous, current in zip(reservations, reservations[1:]):
            if previous["ready_at"] > current["use_start_at"]:
                raise LadleOnlyConflictError(f"{context}.reservations", "同一钢包的预约占用重叠", "reservation_overlap")
        ladle["reservations"] = reservations
        ladles.append(ladle)
        if data_source == "assumed":
            assumptions.append(f"candidate_assumed:{ladle_id}")
        if history_assumption == "clean":
            assumptions.append(f"history_assumed_clean:{ladle_id}")
    bindings: dict[str, str] = {}
    for index, raw in enumerate(_array(source.get("confirmed_bindings", []), "confirmed_bindings")):
        context = f"confirmed_bindings[{index}]"
        raw = _object(raw, context, {"heat_id", "ladle_id"})
        heat_id = _text(raw.get("heat_id"), f"{context}.heat_id")
        ladle_id = _text(raw.get("ladle_id"), f"{context}.ladle_id")
        if heat_id not in heat_ids or ladle_id not in ladle_ids:
            raise LadleOnlyConflictError(context, "绑定必须引用请求中的炉次和钢包", "unknown_binding_reference")
        if heat_id in bindings:
            raise LadleOnlyConflictError(f"{context}.heat_id", "一个炉次只能有一条确认绑定", "duplicate_binding")
        bindings[heat_id] = ladle_id
    return {
        "request_id": request_id, "plan_start_at": anchor, "snapshot_at": snapshot,
        "turnaround_seconds": turnaround, "source_heats": deepcopy(raw_heats),
        "heats": heats, "casts": casts, "ladles": ladles,
        "confirmed_bindings": bindings, "solver_options": solver_options,
        "assumptions": assumptions,
    }


def _format_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _state_output(value: Any, field: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _state_output(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [_state_output(item) for item in value]
    if field.endswith("_at") and isinstance(value, int) and not isinstance(value, bool):
        return _format_timestamp(value)
    return deepcopy(value)


def _response(request: dict[str, Any], policy: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    selected = result["assignments"]
    heat_ids = {heat["heat_id"] for heat in request["heats"]}
    ladle_ids = {ladle["ladle_id"] for ladle in request["ladles"]}
    if set(selected) - heat_ids or set(selected.values()) - ladle_ids:
        raise ValueError("domain output identity mismatch")
    if any(selected.get(heat_id) != ladle_id for heat_id, ladle_id in request["confirmed_bindings"].items()):
        raise ValueError("domain output fixed-binding mismatch")
    if result["objectives"]["assigned_heats"] != len(selected) or result["objectives"]["distinct_ladles"] != len(set(selected.values())):
        raise ValueError("domain output objective mismatch")
    if result["optimization_status"] not in {"optimal", "feasible"}:
        raise ValueError("domain output proof status mismatch")
    if result["optimization_status"] == "optimal":
        phases = result["solver"].get("phase_statuses", [])
        if (len(phases) != 3
                or {phase.get("objective") for phase in phases} != {"assigned_heats", "distinct_ladles", "preference"}
                or any(phase.get("proven") is not True or phase.get("status") != "OPTIMAL" for phase in phases)):
            raise ValueError("domain output optimality lacks complete proof")
    if result["validation"].get("passed") is not True:
        raise ValueError("domain output did not pass replay")
    transitions = result.get("transitions", {})
    rejections = result.get("rejections", {})
    rows: list[dict[str, Any]] = []
    for source, heat in zip(request["source_heats"], request["heats"]):
        heat_id = heat["heat_id"]
        ladle_id = selected.get(heat_id)
        transition = transitions.get(heat_id, {})
        reasons = rejections.get(heat_id, [])
        row = {
            "heat_id": heat_id, "grade": deepcopy(source["grade"]),
            "steel_profile": policy["profiles"].get(str(heat["grade"]), {}).get("name"),
            "seq": source.get("seq"), "operations": deepcopy(source["operations"]),
            "cast_id": heat["cast_id"], "is_cast_first": heat["is_cast_first"],
            "status": "assigned" if ladle_id is not None else "unassigned", "ladle_id": ladle_id,
            "use_deadline_at": _format_timestamp(heat["use_start_at"]),
            "tap_finish_at": _format_timestamp(heat["tap_finish_at"]),
            "cast_finish_at": _format_timestamp(heat["cast_finish_at"]),
            "cast_finish_source": heat["cast_finish_source"],
            "release_at": _format_timestamp(heat["cast_finish_at"]) if ladle_id is not None else None,
            "next_available_at": _format_timestamp(heat["ready_at"]) if ladle_id is not None else None,
            "selection_reasons": deepcopy(transition.get("selection_reasons", [])),
            "rule_outcomes": deepcopy(transition.get("rule_outcomes", [])),
            "state_transition": _state_output({"before": transition.get("before"), "after": transition.get("after")}),
            "candidate_rejections": deepcopy(reasons),
        }
        if ladle_id is None:
            codes = sorted({code for rejection in reasons for code in rejection.get("codes", [])})
            excluded_ids = {rejection.get("ladle_id") for rejection in reasons if rejection.get("codes")}
            if not ladle_ids:
                row["reason_codes"] = ["no_candidates"]
            elif excluded_ids == ladle_ids and codes:
                row["reason_codes"] = codes
            else:
                row["reason_codes"] = ["not_selected"]
            if result["optimization_status"] == "feasible":
                row["reason_codes"].append("search_incomplete")
        rows.append(row)
    count = len(selected)
    assumptions: list[str] = []
    for assumption in request["assumptions"] + policy.get("assumptions", []) + result.get("assumptions", []):
        if assumption not in assumptions:
            assumptions.append(assumption)
    response = {
        "request_id": request["request_id"],
        "status": "complete" if count == len(rows) else "partial" if count else "unassigned",
        "optimization_status": result["optimization_status"], "policy_version": policy["version"],
        "objectives": deepcopy(result["objectives"]), "solver": deepcopy(result["solver"]),
        "assignments": rows, "assumptions": assumptions,
        "validation": deepcopy(result["validation"]),
        "execution": {"reservation_owner": "execution_system", "reservations_committed": False},
    }
    if count != len(rows):
        response["error"] = "存在未分配炉次，请查看逐炉原因及求解状态"
    return response


def _allocate_model_ladles(payload: Any) -> tuple[int, dict[str, Any]]:
    """Compute one stateless proposal with stable redacted error responses."""
    request: dict[str, Any] | None = None
    request_id = None
    if isinstance(payload, dict) and isinstance(payload.get("request_id"), str) and payload["request_id"].strip():
        request_id = payload["request_id"].strip()
    try:
        policy = load_policy()
        request = _normalize_model_request(payload, policy)
        result = build_plan(request, policy)
        response = _response(request, policy, result)
        return (200 if response["status"] == "complete" else 422), response
    except LadleOnlyInputError as exc:
        body = {"error": str(exc), "error_code": exc.code, "field": exc.field}
        if request_id is not None:
            body["request_id"] = request_id
        return 400, body
    except LadleOnlyConflictError as exc:
        body = {"error": str(exc), "error_code": exc.code, "field": exc.field}
        if request_id is not None:
            body["request_id"] = request_id
        return 409, body
    except ImportError:
        body = {"error": "配包所需本地依赖不可用，请安装项目依赖", "error_code": "dependency_unavailable"}
        if request_id is not None:
            body["request_id"] = request_id
        return 503, body
    except Exception as exc:
        from ladle_preallocation.ladle_only.errors import (
            BindingConflictError, PolicyError, SearchIncompleteError, SolverUnavailableError,
        )

        if isinstance(exc, SearchIncompleteError):
            status, code, message = 503, "search_incomplete", "求解预算内尚未得到满足全部确认绑定的可复核方案，请重试"
        elif isinstance(exc, (PolicyError, SolverUnavailableError)):
            status, code, message = 503, "dependency_unavailable", "配包依赖或内部工艺配置不可用"
        elif isinstance(exc, BindingConflictError):
            status, code, message = 409, "binding_conflict", "已确认绑定与工艺或占用条件矛盾"
        else:
            status, code, message = 500, "calculation_failed", "配包计算或结果复核失败"
            LOGGER.exception("ladle-only allocation failed: %s", type(exc).__name__)
        body: dict[str, Any] = {"error": message, "error_code": code}
        if request is not None:
            body["request_id"] = request["request_id"]
        elif request_id is not None:
            body["request_id"] = request_id
        return status, body


def apply_candidate_fact_defaults(candidate: dict[str, Any], policy: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply the program-owned fact policy before missing values become null."""
    from ladle_preallocation.ladle_only.candidate_facts import apply_candidate_fact_defaults as apply_defaults

    return apply_defaults(candidate, policy)


def _path_text(path: tuple[str | int, ...]) -> str:
    result = ""
    for part in path:
        result += f"[{part}]" if isinstance(part, int) else ("." if result else "") + part
    return result


def _find_plan(payload: Any) -> tuple[dict[str, Any], tuple[str | int, ...], list[tuple[dict[str, Any], tuple[str | int, ...]]]]:
    if not isinstance(payload, dict):
        raise LadleOnlyInputError("request", "必须是对象")
    found = []
    malformed_heat_paths = []
    pending = [(payload, (), [])]
    while pending:
        item, path, parents = pending.pop()
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise LadleOnlyInputError(_path_text(path) or "request", "JSON 对象字段名必须是字符串")
            if isinstance(item.get("heats"), list):
                found.append((item, path, parents))
                if len(found) > 1:
                    raise LadleOnlyInputError("heats", "请求必须且只能包含一个炉次计划", "ambiguous_plan")
            elif "heats" in item:
                malformed_heat_paths.append(path + ("heats",))
            chain = parents + [(item, path)]
            pending.extend((value, path + (key,), chain) for key, value in item.items())
        elif isinstance(item, list):
            pending.extend((value, path + (index,), parents) for index, value in enumerate(item))
        elif isinstance(item, float) and not math.isfinite(item):
            raise LadleOnlyInputError(_path_text(path), "JSON 数值必须有限")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise LadleOnlyInputError(_path_text(path), "必须是合法 JSON 值")
    if not found:
        if len(malformed_heat_paths) == 1:
            raise LadleOnlyInputError(_path_text(malformed_heat_paths[0]), "必须是含 1 至 500 项的数组")
        raise LadleOnlyInputError("heats", "缺少炉次计划")
    return found[0]


def _inherited_field(scopes: list[tuple[dict[str, Any], tuple[str | int, ...]]], names: tuple[str, ...]) -> tuple[dict[str, Any], tuple[str | int, ...]]:
    for source, path in reversed(scopes):
        if any(name in source for name in names):
            return source, path
    return {}, scopes[-1][1]


def _alias_fact(raw: dict[str, Any], primary: str, alias: str, context: str,
                *, integer: bool = False) -> tuple[Any, str] | None:
    present = [name for name in (primary, alias) if name in raw]
    if not present:
        return None
    parsed = [_integer(raw[name], f"{context}.{name}", optional=True) if integer
              else _text(raw[name], f"{context}.{name}", optional=True) for name in present]
    if len(parsed) == 2 and parsed[0] != parsed[1]:
        raise LadleOnlyConflictError(f"{context}.{primary}", "别名字段与原字段不一致", "alias_conflict")
    return parsed[0], present[0]


def _translate_candidate(raw: Any, context: str, model_context: str, paths: dict[str, str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LadleOnlyInputError(context, "必须是对象")
    result = {name: deepcopy(raw[name]) for name in LADLE_FIELDS
              if name in raw and name not in {"status", "material_code", "small_repair_age_heats", "condition_code"}}
    for public_name, model_name in (("lining_material_code", "material_code"),
                                    ("minor_repair_age_heats", "small_repair_age_heats"),
                                    ("grade", "condition_code")):
        fact = _alias_fact(raw, public_name, model_name, context, integer=model_name == "small_repair_age_heats")
        paths[f"{model_context}.{model_name}"] = f"{context}.{public_name}"
        if fact is not None:
            result[model_name] = fact[0]
            paths[f"{model_context}.{model_name}"] = f"{context}.{fact[1]}"
    paths[f"{model_context}.status"] = f"{context}.availability_status"
    if "availability_status" in raw:
        status = _enum(raw["availability_status"], f"{context}.availability_status", set(PUBLIC_AVAILABILITY))
        result["status"] = PUBLIC_AVAILABILITY[status]
        if "status" in raw and _enum(raw["status"], f"{context}.status", STATUS_VALUES) != result["status"]:
            raise LadleOnlyConflictError(f"{context}.availability_status", "别名字段与原字段不一致", "alias_conflict")
    elif "status" in raw:
        result["status"] = raw["status"]
        paths[f"{model_context}.status"] = f"{context}.status"
    if isinstance(result.get("last_use"), dict):
        result["last_use"] = {key: value for key, value in result["last_use"].items()
                              if key in {"heat_id", "grade", "cast_finish_at"}}
    if isinstance(result.get("reservations"), list):
        result["reservations"] = [
            {key: value for key, value in reservation.items()
             if key in {"heat_id", "grade", "use_start_at", "cast_finish_at", "turnaround_seconds"}}
            if isinstance(reservation, dict) else reservation for reservation in result["reservations"]
        ]
    return result


def _public_error(exc: LadleOnlyInputError | LadleOnlyConflictError, paths: dict[str, str]) -> Exception:
    field = exc.field
    for model_path in sorted(paths, key=len, reverse=True):
        if field == model_path or field.startswith(model_path + ".") or field.startswith(model_path + "["):
            field = paths[model_path] + field[len(model_path):]
            break
    description = str(exc).split("：", 1)[-1]
    return type(exc)(field, description, exc.code)


def normalize_ladle_only_request(payload: Any, policy: dict[str, Any] | None = None,
                                 *, service_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Translate consumed public facts while retaining the entire source message.

    ``service_config`` belongs to the embedding service, never to client metadata.
    It can supply an explicit schedule anchor and solver budgets.
    """
    policy = load_policy() if policy is None else policy
    plan, plan_path, parents = _find_plan(payload)
    scopes = parents + [(plan, plan_path)]
    config = {} if service_config is None else service_config
    try:
        _object(config, "service_config", {"schedule_start_at", "solver_options"})
    except LadleOnlyInputError as exc:
        from ladle_preallocation.ladle_only.errors import PolicyError

        raise PolicyError("内部接口配置无效") from exc
    paths = {"heats": _path_text(plan_path + ("heats",))}
    anchor_source, anchor_path = _inherited_field(scopes, ("schedule_start_at",))
    anchor = anchor_source.get("schedule_start_at", config.get("schedule_start_at"))
    paths["plan_start_at"] = _path_text(anchor_path + ("schedule_start_at",))
    turnaround_source, turnaround_path = _inherited_field(scopes, ("turnaround_seconds", "turnaround_time"))
    present_turnaround = [name for name in ("turnaround_seconds", "turnaround_time") if name in turnaround_source]
    turnaround_name = present_turnaround[0] if present_turnaround else "turnaround_seconds"
    paths["turnaround_seconds"] = _path_text(turnaround_path + (turnaround_name,))
    durations = [_integer(turnaround_source[name], _path_text(turnaround_path + (name,))) for name in present_turnaround]
    if len(durations) == 2 and durations[0] != durations[1]:
        raise LadleOnlyConflictError(paths["turnaround_seconds"], "周转字段与别名不一致", "alias_conflict")
    model = {
        "request_id": "ladle-" + uuid4().hex, "plan_start_at": anchor,
        "turnaround_seconds": durations[0] if durations else None,
        "solver_options": deepcopy(config.get("solver_options", {})),
    }
    snapshot_source, snapshot_path = _inherited_field(scopes, ("snapshot_at",))
    if "snapshot_at" in snapshot_source:
        model["snapshot_at"] = snapshot_source["snapshot_at"]
        paths["snapshot_at"] = _path_text(snapshot_path + ("snapshot_at",))
    heats = _array(plan.get("heats"), paths["heats"], minimum=1)
    model_heats = []
    converter_orders: dict[str, list[tuple[int | None, int, str]]] = {}
    heat_bindings: list[tuple[dict[str, str], str]] = []
    for index, raw in enumerate(heats):
        context = f"{paths['heats']}[{index}]"
        model_context = f"heats[{index}]"
        paths[model_context] = context
        if not isinstance(raw, dict):
            raise LadleOnlyInputError(context, "必须是对象")
        route = _array(raw.get("route"), f"{context}.route", minimum=2, maximum=6)
        paths[f"{model_context}.operations"] = f"{context}.route"
        operations = []
        for op_index, operation in enumerate(route):
            if not isinstance(operation, dict):
                raise LadleOnlyInputError(f"{context}.route[{op_index}]", "必须是对象")
            operations.append({key: operation.get(key) for key in ("operation", "machine_id")})
        translated = {key: raw[key] for key in ("heat_id", "grade", "tap_finish_at", "cast_finish_at") if key in raw}
        translated["operations"] = operations
        model_heats.append(translated)
        machine = _text(route[0].get("machine_id"), f"{context}.route[0].machine_id")
        sequence = (_integer(route[0]["sequence_on_machine"], f"{context}.route[0].sequence_on_machine", minimum=1)
                    if "sequence_on_machine" in route[0] else None)
        tapping = _timestamp(raw.get("tap_finish_at"), f"{context}.tap_finish_at")
        converter_orders.setdefault(machine, []).append((sequence, tapping, context))
        if raw.get("ladle_id") is not None:
            heat_bindings.append(({"heat_id": _text(raw.get("heat_id"), f"{context}.heat_id"),
                                   "ladle_id": _text(raw["ladle_id"], f"{context}.ladle_id")}, context))
    for group in converter_orders.values():
        if any(sequence is not None for sequence, _, _ in group):
            if any(sequence is None for sequence, _, _ in group):
                raise LadleOnlyConflictError(f"{group[0][2]}.route[0].sequence_on_machine", "同一转炉的显式顺序必须完整", "incomplete_converter_sequence")
            ordered = sorted(group, key=lambda row: row[0])
            if len({row[0] for row in ordered}) != len(ordered):
                raise LadleOnlyConflictError(f"{ordered[0][2]}.route[0].sequence_on_machine", "同一转炉的顺序标识重复", "duplicate_converter_sequence")
            if any(left[1] >= right[1] for left, right in zip(ordered, ordered[1:])):
                raise LadleOnlyConflictError(f"{ordered[0][2]}.route[0].sequence_on_machine", "转炉顺序与完成时间不一致", "converter_sequence_time_conflict")
    model["heats"] = model_heats
    cast_source, cast_path = _inherited_field(scopes, ("casts",))
    if "casts" in cast_source:
        paths["casts"] = _path_text(cast_path + ("casts",))
        casts = _array(cast_source["casts"], paths["casts"], minimum=1)
        model["casts"] = [{key: value for key, value in cast.items() if key in {"cast_id", "heat_ids"}}
                          if isinstance(cast, dict) else cast for cast in casts]
    else:
        model["casts"] = [{"cast_id": f"private-qualification-{index}", "heat_ids": [heat.get("heat_id")]}
                          for index, heat in enumerate(model_heats)]
    candidate_source, candidate_path = _inherited_field(scopes, ("ladles",))
    paths["ladles"] = _path_text(candidate_path + ("ladles",))
    candidates = _array(candidate_source.get("ladles"), paths["ladles"], maximum=200)
    model_candidates, provenance, trusted_clean = [], [], []
    for index, candidate in enumerate(candidates):
        context, model_context = f"{paths['ladles']}[{index}]", f"ladles[{index}]"
        paths[model_context] = context
        translated = _translate_candidate(candidate, context, model_context, paths)
        completed, sources = apply_candidate_fact_defaults(translated, policy)
        internally_clean = sources.get("history_assumption") == "assumed" and completed.get("history_assumption") == "clean"
        if internally_clean:
            # The strict model boundary forbids caller-provided clean history on
            # provided data. Restore the trusted helper fact only after it runs.
            completed.pop("history_assumption")
        model_candidates.append(completed)
        provenance.append(sources)
        trusted_clean.append(internally_clean)
    model["ladles"] = model_candidates
    binding_source, binding_path = _inherited_field(scopes, ("confirmed_bindings",))
    paths["confirmed_bindings"] = _path_text(binding_path + ("confirmed_bindings",))
    bindings = _array(binding_source.get("confirmed_bindings", []), paths["confirmed_bindings"])
    model_bindings = []
    explicit_bindings = {}
    for index, binding in enumerate(bindings):
        context = f"{paths['confirmed_bindings']}[{index}]"
        if not isinstance(binding, dict):
            raise LadleOnlyInputError(context, "必须是对象")
        heat_id = _text(binding.get("heat_id"), f"{context}.heat_id")
        ladle_id = _text(binding.get("ladle_id"), f"{context}.ladle_id")
        if heat_id in explicit_bindings:
            raise LadleOnlyConflictError(f"{context}.heat_id", "一个炉次只能有一条确认绑定", "duplicate_binding")
        explicit_bindings[heat_id] = ladle_id
        model_bindings.append({"heat_id": heat_id, "ladle_id": ladle_id})
    for binding, context in heat_bindings:
        if binding["heat_id"] in explicit_bindings:
            if explicit_bindings[binding["heat_id"]] != binding["ladle_id"]:
                raise LadleOnlyConflictError(f"{context}.ladle_id", "炉次钢包与确认绑定不一致", "binding_conflict")
        else:
            paths[f"confirmed_bindings[{len(model_bindings)}].heat_id"] = f"{context}.heat_id"
            paths[f"confirmed_bindings[{len(model_bindings)}].ladle_id"] = f"{context}.ladle_id"
            paths[f"confirmed_bindings[{len(model_bindings)}]"] = f"{context}.ladle_id"
            model_bindings.append(binding)
    model["confirmed_bindings"] = model_bindings
    try:
        normalized = _normalize_model_request(model, policy)
    except (LadleOnlyInputError, LadleOnlyConflictError) as exc:
        if exc.field.startswith("solver_options") or (exc.field == "plan_start_at"
                and "schedule_start_at" not in anchor_source and "schedule_start_at" in config):
            from ladle_preallocation.ladle_only.errors import PolicyError

            raise PolicyError("内部接口配置无效") from exc
        raise _public_error(exc, paths) from exc
    normalized["candidate_provenance"] = {}
    for index, candidate in enumerate(normalized["ladles"]):
        normalized["candidate_provenance"][candidate["ladle_id"]] = provenance[index]
        normalized["assumptions"].extend(f"candidate_fact_assumed:{candidate['ladle_id']}:{field}"
                                         for field, source in provenance[index].items() if source == "assumed")
        if trusted_clean[index]:
            candidate["history_assumption"] = "clean"
    normalized["_source_message"] = deepcopy(payload)
    normalized["_plan_path"] = plan_path
    normalized["_public_paths"] = paths
    return normalized


def _merge_public_response(request: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    response = deepcopy(request["_source_message"])
    plan = response
    for part in request["_plan_path"]:
        plan = plan[part]
    for original, allocation in zip(plan["heats"], verified["assignments"]):
        original["ladle_id"] = allocation["ladle_id"]
        if allocation["ladle_id"] is not None:
            original.pop("allocation_reason", None)
        else:
            codes = allocation["reason_codes"]
            if "no_candidates" in codes:
                reason = "本次没有候选钢包（no_candidates）。"
            elif "unknown_steel_grade" in codes:
                reason = "钢种未配置适配规则（unknown_steel_grade）。"
            else:
                local_codes = [code for code in codes if code != "search_incomplete"]
                details = "、".join(local_codes[:3]) + ("等" if len(local_codes) > 3 else "")
                reason = "当前方案未选出满足工艺和时间要求的钢包" + (f"（{details}）" if details else "") + "。"
            if "search_incomplete" in codes:
                reason = "搜索尚未完成（search_incomplete），不能据当前方案断定全批无解；" + reason
            original["allocation_reason"] = reason
    return response


def allocate_ladles(payload: Any, *, service_config: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Calculate and merge ladle bindings without replacing the upstream message."""
    request_id = None
    if isinstance(payload, dict) and isinstance(payload.get("request_id"), str) and payload["request_id"].strip():
        request_id = payload["request_id"].strip()
    try:
        policy = load_policy()
        request = normalize_ladle_only_request(payload, policy, service_config=service_config)
        result = build_plan(request, policy)
        verified = _response(request, policy, result)
        LOGGER.info("ladle-only allocation policy=%s assigned=%s distinct=%s proof=%s",
                    verified["policy_version"], verified["objectives"]["assigned_heats"],
                    verified["objectives"]["distinct_ladles"], verified["optimization_status"])
        return (200 if verified["status"] == "complete" else 422), _merge_public_response(request, verified)
    except Exception as exc:
        return _allocation_error_response(exc, request_id)


def _allocation_error_response(exc: Exception, request_id: str | None) -> tuple[int, dict[str, Any]]:
    from ladle_preallocation.ladle_only.errors import BindingConflictError, PolicyError, SearchIncompleteError, SolverUnavailableError

    if isinstance(exc, (LadleOnlyInputError, LadleOnlyConflictError)):
        status = 400 if isinstance(exc, LadleOnlyInputError) else 409
        body = {"error": str(exc), "error_code": exc.code, "field": exc.field}
    else:
        if isinstance(exc, SearchIncompleteError):
            status, code, message = 503, "search_incomplete", "求解预算内尚未得到满足全部确认绑定的可复核方案，请重试"
        elif isinstance(exc, (ImportError, PolicyError, SolverUnavailableError)):
            status, code, message = 503, "dependency_unavailable", "配包依赖或内部工艺配置不可用"
        elif isinstance(exc, BindingConflictError):
            status, code, message = 409, "binding_conflict", "已确认绑定与工艺或占用条件矛盾"
        else:
            status, code, message = 500, "calculation_failed", "配包计算或结果复核失败"
            LOGGER.exception("ladle-only allocation failed: %s", type(exc).__name__)
        body = {"error": message, "error_code": code}
    if request_id is not None:
        body["request_id"] = request_id
    return status, body
