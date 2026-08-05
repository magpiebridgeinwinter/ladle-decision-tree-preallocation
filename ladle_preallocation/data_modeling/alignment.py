"""Explicit source-column contracts; raw rows never enter scheduling unchanged."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class FieldDefinition:
    field: str
    meaning: str
    example: str
    data_type: str
    critical: bool = False


_CRANE = (
    ("sequence_id", "流水号", "346", "int", True), ("crane_id", "行车号", "3170", "str", True),
    ("position_x", "物理位置X", "38105", "float", False), ("position_y", "物理位置Y", "1064", "float", False),
    ("position_z", "物理位置Z", "0", "float", False), ("bay", "所在跨", "Z3", "str", False),
    ("online_status", "行车状态(0离线/1在线)", "1", "int", False), ("updated_at", "更新时刻", "2026-03-06-23.20.27.000000", "timestamp", True),
    ("speed_mps", "运行速度(m/s)", "2.0", "float", False), ("max_load_tonnes", "最大载重(吨)", "300", "float", True),
    ("lift_lower_seconds", "吊起/放下时间(秒)", "30", "float", False), ("load_balance_pct", "负载均衡系数(%)", "45", "float", False),
    ("bay_length_m", "所在跨长度", "100", "float", False), ("safe_distance_m", "行车间安全距离(m)", "10", "float", True),
    ("limit_0_m", "该行车运行极限位0(m)", "0", "float", False), ("limit_1_m", "该行车运行极限位1(m)", "100", "float", False),
    ("weight_tonnes", "重量", "160", "float", True), ("trigger_type", "触发类型(1自动/2手动)", "1", "int", False),
    ("record_type", "记录类型(1定周期/2时间触发)", "1", "int", False), ("ladle_id", "包号", "L001", "str", True),
)
CRANE_COLUMNS = tuple(FieldDefinition(*item) for item in _CRANE)

_MASTER_NAMES = [
    "plan_sequence", "manufacturing_order", "heat_id", "smelting_method", "dephos_furnace", "converter_furnace", "refining_route", "cast_id", "heats_in_cast", "cast_segment", "tundish_change", "decant_finish_at", "pretreatment_finish_at", "raw_material_start_at", "dephos_blow_start_at", "dephos_hotmetal_finish_at", "decarb_blow_start_at", "tap_finish_at", "refining_1_finish_at", "refining_2_finish_at", "refining_3_finish_at", "refining_4_finish_at", "ladle_arrival_at", "ladle_pour_start_at", "required_grade", "dephos_ladle_id", "decarb_ladle_id", "current_ladle_grade", "empty_ladle_weight", "ladle_position", "plan_flag", "allocation_flag", "hotmetal_ladle_id", "plan_heat_status", "ladle_pour_finish_at", "refining_1_finish_extra_at", "refining_2_finish_extra_at", "refining_3_finish_extra_at", "refining_4_finish_extra_at", "preallocated_ladle", "preallocation_at", "manual_change_reason", "steel_group", "manual_auto_mode", "preallocated_ladle_grade", "preallocated_ladle_2", "preallocated_ladle_2_at", "priority", "preallocated_hotmetal_ladle", "preallocated_hotmetal_ladle_at", "preallocated_ladle_3", "preallocated_ladle_3_at",
]
_MASTER_MEANINGS = ["计划顺序号", "制造命令号", "出钢记号", "冶炼方式", "脱磷炉号", "转炉炉号", "精炼路径", "Cast号", "cast内总炉数", "Cast分割号", "中间包更换标记"] + ["时间字段"] * 13 + ["钢包等级要求", "脱磷包号", "脱碳包号", "当前钢包等级", "钢包空包重", "包位置", "计划标志", "配包标志", "铁包包号", "计划炉次状态", "钢包浇注终时刻", "精炼1终时刻(新增)", "精炼2终时刻(新增)", "精炼3终时刻(新增)", "精炼4终时刻(新增)", "钢包预配包", "钢包预配包时刻", "人工修改原因", "钢种组信息", "人工/自动模式", "钢包预配包等级（原名预配包状态）", "预配包2", "预配包2时刻", "优先级", "预配铁包", "预配铁包时刻", "预配包3", "预配包3时刻"]
MASTER_COLUMNS = tuple(FieldDefinition(name, meaning, "", "str", name in {"heat_id", "tap_finish_at", "required_grade", "current_ladle_grade", "ladle_position"}) for name, meaning in zip(_MASTER_NAMES, _MASTER_MEANINGS))


def markdown_field_table(fields: Sequence[FieldDefinition]) -> str:
    rows = ["| 字段 | 含义 | 样例 | 数据类型 | 是否关键 |", "| --- | --- | --- | --- | --- |"]
    rows.extend(f"| {x.field} | {x.meaning} | {x.example or '-'} | {x.data_type} | {'是' if x.critical else '否'} |" for x in fields)
    return "\n".join(rows)


def _align(row: Sequence[Any], columns: Sequence[FieldDefinition], source: str) -> dict[str, Any]:
    if len(row) != len(columns):
        raise ValueError(f"{source}列序不一致：期望{len(columns)}列，实际{len(row)}列")
    return {column.field: value if value not in (None, "") else None for column, value in zip(columns, row)}


def align_crane_row(row: Sequence[Any]) -> dict[str, Any]:
    """Align exactly 20 crane columns; a missing trailing ladle id is represented by None."""
    if len(row) == 19:
        row = [*row, None]
    return _align(row, CRANE_COLUMNS, "行车数据")


def align_master_row(row: Sequence[Any], headers: Sequence[str] | None = None) -> dict[str, Any]:
    """Reject shifted Column1..Column52 input instead of applying a silent mapping."""
    if headers is not None and list(headers) != [f"Column{i}" for i in range(1, 53)]:
        raise ValueError("列序不一致：主数据表应为 Column1~Column52")
    return _align(row, MASTER_COLUMNS, "主数据")
