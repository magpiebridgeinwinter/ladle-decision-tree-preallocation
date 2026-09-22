"""Supported disturbance taxonomy for audited offline demonstrations."""
from __future__ import annotations

from dataclasses import asdict, dataclass


CRANE_OFFLINE = "crane_offline"
CRANE_SPEED_DEGRADED = "crane_speed_degraded"
CRANE_LOAD_RESTRICTED = "crane_load_restricted"
CRANE_RANGE_RESTRICTED = "crane_range_restricted"
TRANSPORT_CORRIDOR_BLOCKED = "transport_corridor_blocked"
LADLE_UNAVAILABLE = "ladle_unavailable"
LADLE_DAMAGE = "ladle_damage"
LADLE_LINING_ALARM = "ladle_lining_alarm"
LADLE_OVER_AGE = "ladle_over_age"
LADLE_GRADE_CONFLICT = "ladle_grade_conflict"
FACILITY_UNAVAILABLE = "facility_unavailable"
ARGON_STATION_UNAVAILABLE = "argon_station_unavailable"
REFINING_ROUTE_CHANGE = "refining_route_change"
SCHEDULE_DEVIATION = "schedule_deviation"
CONVERTER_DELAY = "converter_delay"
CASTER_DELAY = "caster_delay"
URGENT_HEAT_INSERTED = "urgent_heat_inserted"
PRIORITY_ESCALATION = "priority_escalation"
CRANE_TELEMETRY_STALE = "crane_telemetry_stale"
COMPOUND_DISTURBANCE = "compound_disturbance"


@dataclass(frozen=True)
class DisturbanceDefinition:
    kind: str
    group: str
    title: str
    description: str
    visual_cue: str
    state_change: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


_DEFINITIONS = (
    DisturbanceDefinition(CRANE_OFFLINE, "equipment", "行车突然离线", "原计划行车失去在线状态，局部候选行车需重新组合。", "crane_power_off", "remove_assigned_crane"),
    DisturbanceDefinition(CRANE_SPEED_DEGRADED, "equipment", "行车速度下降", "行车降速后原运输时间窗不再可行。", "crane_slow", "reduce_crane_speed"),
    DisturbanceDefinition(CRANE_LOAD_RESTRICTED, "equipment", "行车限载", "临时限载使原钢包重量超过行车可用载荷。", "crane_load_alarm", "reduce_crane_capacity"),
    DisturbanceDefinition(CRANE_RANGE_RESTRICTED, "equipment", "行车作业范围受限", "检修边界变化使原钢包位置超出可达范围。", "crane_range_block", "narrow_crane_limits"),
    DisturbanceDefinition(TRANSPORT_CORRIDOR_BLOCKED, "logistics_safety", "运输通道封锁", "安全隔离或通道占用导致原运输走廊不可用。", "safety_barrier", "block_transport_corridor"),
    DisturbanceDefinition(LADLE_UNAVAILABLE, "ladle", "钢包临时不可用", "原配钢包进入维护或清理状态。", "ladle_maintenance", "remove_assigned_ladle"),
    DisturbanceDefinition(LADLE_DAMAGE, "ladle", "钢包损坏", "钢包壳体或机构异常，禁止继续承运。", "ladle_damage", "quarantine_assigned_ladle"),
    DisturbanceDefinition(LADLE_LINING_ALARM, "ladle", "钢包内衬报警", "耐材状态报警触发钢包隔离和替包。", "lining_temperature_alarm", "quarantine_lining_alarm"),
    DisturbanceDefinition(LADLE_OVER_AGE, "ladle", "钢包超龄", "钢包周转龄超过受控上限，需要选择替代钢包。", "ladle_clock_alarm", "enforce_ladle_age"),
    DisturbanceDefinition(LADLE_GRADE_CONFLICT, "ladle", "钢包等级冲突", "原钢包等级与临时强化的炉次等级约束冲突。", "grade_conflict", "enforce_grade_compatibility"),
    DisturbanceDefinition(FACILITY_UNAVAILABLE, "process_facility", "精炼设施停机", "原工艺路线包含的设施不可用，必须选择已配置备用路线。", "facility_offline", "reroute_around_facility"),
    DisturbanceDefinition(ARGON_STATION_UNAVAILABLE, "process_facility", "氩站不可用", "原路线的吹氩站不可用，需改走已配置备用精炼路线。", "argon_station_alarm", "reroute_around_argon_station"),
    DisturbanceDefinition(REFINING_ROUTE_CHANGE, "process_facility", "精炼路径临时变更", "工艺约束变化要求两个炉次改走新的允许路线。", "route_switch", "replace_refining_route"),
    DisturbanceDefinition(SCHEDULE_DEVIATION, "plan_timing", "生产计划偏差", "实际节拍偏离预配计划，打开二十分钟局部窗口重排。", "timeline_shift", "shift_local_windows"),
    DisturbanceDefinition(CONVERTER_DELAY, "plan_timing", "转炉延迟", "上游转炉晚点压缩后续钢包运输衔接时间。", "converter_delay", "delay_upstream_heat"),
    DisturbanceDefinition(CASTER_DELAY, "plan_timing", "连铸机延迟", "下游连铸节拍变化造成局部炉次顺序和时间窗冲突。", "caster_delay", "delay_casting_sequence"),
    DisturbanceDefinition(URGENT_HEAT_INSERTED, "plan_timing", "紧急炉次插入", "临时插入的高优先级炉次与原局部计划竞争资源。", "urgent_heat", "insert_priority_heat"),
    DisturbanceDefinition(PRIORITY_ESCALATION, "plan_timing", "炉次优先级提升", "质量或交付要求使待产炉次优先级即时上调。", "priority_up", "raise_heat_priority"),
    DisturbanceDefinition(CRANE_TELEMETRY_STALE, "data_control", "行车遥测陈旧", "原行车位置和载荷快照超时，调度只能使用新鲜候选快照。", "telemetry_warning", "exclude_stale_crane_snapshot"),
    DisturbanceDefinition(COMPOUND_DISTURBANCE, "compound", "多资源复合扰动", "行车、钢包和工艺路线同时受限，形成跨资源全局冲突。", "compound_alarm", "combine_crane_ladle_route_failures"),
)

DISTURBANCE_CATALOG = {item.kind: item for item in _DEFINITIONS}
DISTURBANCE_KINDS = frozenset(DISTURBANCE_CATALOG)


def catalog_rows() -> list[dict[str, str]]:
    """Return the stable ordered catalog used by persistence and the frontend."""
    return [item.as_dict() for item in _DEFINITIONS]
