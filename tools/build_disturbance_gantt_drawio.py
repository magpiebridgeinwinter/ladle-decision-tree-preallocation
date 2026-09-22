#!/usr/bin/env python3
"""Build a traceable disturbance Gantt and decision-flow draw.io file.

The source audit is the single source of truth.  This tool only projects the
audit into diagram data; it does not run or alter any allocation algorithm.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import html
import json
import colorsys
import sys
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "outputs/real_data_codex_stress_demo/audit.json"
DEFAULT_OUTPUT = ROOT / "outputs/disturbance_gantt_drawio"
SCHEMA_VERSION = 3
DISPLAY_AXIS_START_MINUTE = 0.0
DISPLAY_AXIS_END_MINUTE = 600.0
DISPLAY_EVENT_MINUTE = 60.0


COLORS = {
    "paper": "#f5f5f5",
    "ink": "#2d3142",
    "muted": "#4f5d75",
    "soft": "#7a8399",
    "rule": "#d9dce3",
    "accent": "#eb6c36",
    "accent_tint": "#fff0e8",
    "blue": "#2e5aa8",
    "blue_tint": "#eaf1ff",
    "green": "#3c7a57",
    "green_tint": "#eaf5ee",
    "danger": "#b94747",
    "danger_tint": "#fff0f0",
}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        fail(f"audit file not found: {path}")
        raise exc
    except json.JSONDecodeError as exc:
        fail(f"invalid audit JSON {path}: {exc}")
    if not isinstance(value, dict):
        fail("audit root must be an object")
    return value


def _rows_by_heat(rows: Iterable[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        heat_id = str(row.get("heat_id") or "").strip()
        if not heat_id:
            fail(f"{label} contains a row without heat_id")
        if heat_id in result:
            fail(f"{label} contains duplicate heat_id: {heat_id}")
        result[heat_id] = row
    return result


def _assignment_text(row: dict[str, Any] | None) -> str:
    if not row or row.get("action") != "assign" or not row.get("ladle_id"):
        return "未分配"
    ladle = str(row.get("ladle_id"))
    crane = str(row.get("crane_id") or "-")
    return f"{ladle} / {crane}"


def _assignment_pair(row: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not row or row.get("action") != "assign":
        return None, None
    return (
        str(row.get("ladle_id")) if row.get("ladle_id") else None,
        str(row.get("crane_id")) if row.get("crane_id") else None,
    )


def _changed(base: dict[str, Any] | None, candidate: dict[str, Any] | None) -> bool:
    return _assignment_pair(base) != _assignment_pair(candidate)


def _short_reason(row: dict[str, Any] | None) -> str:
    if not row:
        return "缺少结果"
    violations = list(row.get("violations") or [])
    if violations:
        return "、".join(str(item) for item in violations[:2])
    reason = str(row.get("reason") or "").strip()
    return reason[:42] if reason else "通过"


def _display_window(
    heat: dict[str, Any],
    source_start: float,
    source_end: float,
    display_start: float,
    display_end: float,
) -> tuple[float, float]:
    start = float(heat.get("window_start") or source_start)
    end = float(heat.get("window_end") or start)
    span = max(source_end - source_start, 1.0)
    scale = (display_end - display_start) / span
    left = display_start + (start - source_start) * scale
    right = display_start + (end - source_start) * scale
    return max(display_start, left), min(display_end, max(left + 0.12, right))


def _load_source_audit(audit: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    source_value = str((audit.get("stress_audit") or {}).get("source_audit") or "").strip()
    source_path = ROOT / source_value if source_value else ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"
    if not source_path.is_file():
        fail(f"source location-aware audit not found: {source_path}")
    return load_json(source_path), source_path


def _source_datetime(origin: datetime, seconds: float | None) -> datetime | None:
    if seconds is None:
        return None
    return origin + timedelta(seconds=float(seconds))


def _time_label(value: datetime | None) -> str:
    return value.strftime("%m-%d %H:%M") if value else "未知时间"


def _precise_time_label(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "未知时间"


def _demo_time_label(minute: float) -> str:
    total_minutes = 10 * 60 + int(round(minute))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def _heat_color(index: int, total: int, used: set[str] | None = None) -> str:
    """Generate a deterministic distinct color for each heat row."""
    # Golden-ratio stepping keeps adjacent rows visually separated instead of
    # placing the first and last rows next to the same hue.
    attempt = 0
    while True:
        hue = (index * 0.61803398875 + 0.04 + attempt * 0.0007) % 1.0
        red, green, blue = colorsys.hsv_to_rgb(hue, 0.55, 0.92)
        value = "#%02x%02x%02x" % (round(red * 255), round(green * 255), round(blue * 255))
        if used is None or value not in used:
            return value
        attempt += 1


def _full_plan_rows(
    source_audit: dict[str, Any],
    baseline: dict[str, dict[str, Any]],
    affected: dict[str, dict[str, Any]],
    codex: dict[str, dict[str, Any]],
    origin: datetime,
) -> list[dict[str, Any]]:
    heats = (source_audit.get("scheduling_inputs") or {}).get("heats") or []
    rows: list[dict[str, Any]] = []
    used_colors: set[str] = set()
    for index, heat in enumerate(heats):
        heat_id = str(heat.get("heat_id") or "").strip()
        if not heat_id:
            fail("source scheduling_inputs.heats contains a row without heat_id")
        start_seconds = float(heat.get("window_start") or 0.0)
        end_seconds = float(heat.get("window_end") or start_seconds)
        start_at = _source_datetime(origin, start_seconds)
        end_at = _source_datetime(origin, end_seconds)
        base_row = baseline.get(heat_id)
        final_row = base_row
        branch = "AP 原计划"
        if heat_id in affected:
            final_row = codex.get(heat_id) or base_row
            branch = "AR Codex" if final_row is not base_row and final_row else "AP 原计划"
        if not final_row or final_row.get("action") != "assign":
            final_display = "未分配"
        else:
            final_display = _assignment_text(final_row)
        baseline_display = _assignment_text(base_row)
        rows.append({
            "element_key": f"plan_{heat_id}",
            "heat_id": heat_id,
            "sequence": index + 1,
            "required_grade": str(heat.get("required_grade") or "").strip(),
            "refining_route": str(heat.get("refining_route") or "").strip(),
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "duration_seconds": max(0.0, end_seconds - start_seconds),
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
            "start_label": _precise_time_label(start_at),
            "end_label": _precise_time_label(end_at),
            "baseline_assignment": baseline_display,
            "final_assignment": final_display,
            "assignment": final_display,
            "ladle_id": _assignment_pair(final_row)[0],
            "crane_id": _assignment_pair(final_row)[1],
            "branch": branch,
            "affected": heat_id in affected,
            "status": "Codex改配" if heat_id in affected and _changed(base_row, final_row) else "受扰动但保持原计划" if heat_id in affected else "正常计划",
            "color": _heat_color(index, len(heats), used_colors),
        })
        used_colors.add(rows[-1]["color"])
    return rows


def build_diagram_data(audit: dict[str, Any], source_path: Path) -> dict[str, Any]:
    scenario_id = str(audit.get("scenario_id") or "").strip()
    stress = audit.get("stress_audit") or {}
    scenario_inputs = audit.get("scenario_inputs") or {}
    window = stress.get("window") or {}
    event = stress.get("event") or {}
    if not scenario_id:
        fail("missing required field: scenario_id")
    affected_ids = [str(value).strip() for value in window.get("affected_heat_ids") or []]
    if not affected_ids:
        fail("missing required field: stress_audit.window.affected_heat_ids")
    if len(set(affected_ids)) != len(affected_ids):
        fail("affected_heat_ids contains duplicates")
    if not event.get("kind") or not event.get("resource_id"):
        fail("missing required event kind or resource_id")

    heat_rows = _rows_by_heat(scenario_inputs.get("heats") or [], "scenario_inputs.heats")
    missing_heats = [heat_id for heat_id in affected_ids if heat_id not in heat_rows]
    if missing_heats:
        fail(f"affected heat not found in scenario_inputs.heats: {missing_heats[0]}")

    baseline_source = audit.get("baseline_full_assignments") or scenario_inputs.get("source_baseline_assignments") or []
    baseline = _rows_by_heat(baseline_source, "baseline assignments")
    source_audit, source_audit_path = _load_source_audit(audit)
    source_time_range = source_audit.get("time_range") or []
    if not source_time_range:
        fail("source location-aware audit is missing time_range")
    try:
        origin = datetime.fromisoformat(str(source_time_range[0]).replace("Z", "+00:00"))
    except ValueError as exc:
        fail(f"invalid source time_range start: {source_time_range[0]}")
        raise exc
    decision_tree = _rows_by_heat((audit.get("decision_tree") or {}).get("assignments") or [], "decision_tree assignments")
    codex = _rows_by_heat((audit.get("codex_llm") or {}).get("assignments") or [], "codex_llm assignments")
    for label, rows in (("baseline", baseline), ("decision_tree", decision_tree), ("codex_llm", codex)):
        missing = [heat_id for heat_id in affected_ids if heat_id not in rows]
        if missing:
            fail(f"{label} result missing affected heat: {missing[0]}")

    display_start = float(window.get("start_minute") if window.get("start_minute") is not None else 60.0)
    display_end = float(window.get("end_minute") if window.get("end_minute") is not None else 80.0)
    source_starts = [float(heat_rows[heat_id].get("window_start") or 0.0) for heat_id in affected_ids]
    source_ends = [float(heat_rows[heat_id].get("window_end") or 0.0) for heat_id in affected_ids]
    source_start = min(source_starts)
    source_end = max(source_ends)

    changed_by_audit = {
        str(row.get("heat_id")): row
        for row in stress.get("changed_assignments") or []
        if row.get("heat_id")
    }
    heat_output: list[dict[str, Any]] = []
    for heat_id in affected_ids:
        heat = heat_rows[heat_id]
        plan_start, plan_end = _display_window(heat, source_start, source_end, display_start, display_end)
        base_row = baseline[heat_id]
        dt_row = decision_tree[heat_id]
        llm_row = codex[heat_id]
        dt_changed = _changed(base_row, dt_row)
        codex_changed = _changed(base_row, llm_row)
        dt_assigned = dt_row.get("action") == "assign" and bool(dt_row.get("ladle_id"))
        codex_assigned = llm_row.get("action") == "assign" and bool(llm_row.get("ladle_id"))
        if not dt_assigned:
            status = "决策树未分配，Codex补全" if codex_assigned else "两条线路均未分配"
        elif codex_changed:
            status = "Codex改配" if dt_assigned else "Codex补全"
        elif dt_changed:
            status = "决策树改配"
        else:
            status = "保持原计划"
        heat_output.append({
            "element_key": f"heat_{scenario_id}_{heat_id}",
            "heat_id": heat_id,
            "required_grade": str(heat.get("required_grade") or "").strip(),
            "refining_route": str(heat.get("refining_route") or "").strip(),
            "plan_start": round(plan_start, 3),
            "plan_end": round(plan_end, 3),
            "source_window_start": heat.get("window_start"),
            "source_window_end": heat.get("window_end"),
            "source_pour_at": heat.get("pour_at"),
            "plan_start_at": _precise_time_label(_source_datetime(origin, heat.get("window_start"))),
            "plan_end_at": _precise_time_label(_source_datetime(origin, heat.get("window_end"))),
            "baseline": {"ladle_id": _assignment_pair(base_row)[0], "crane_id": _assignment_pair(base_row)[1], "display": _assignment_text(base_row)},
            "decision_tree": {"ladle_id": _assignment_pair(dt_row)[0], "crane_id": _assignment_pair(dt_row)[1], "display": _assignment_text(dt_row), "assigned": dt_assigned, "changed": dt_changed, "reason": _short_reason(dt_row)},
            "codex": {"ladle_id": _assignment_pair(llm_row)[0], "crane_id": _assignment_pair(llm_row)[1], "display": _assignment_text(llm_row), "assigned": codex_assigned, "changed": codex_changed, "reason": _short_reason(llm_row)},
            "status": status,
            "changed_by": [name for name, changed in (("decision_tree", dt_changed), ("codex", codex_changed)) if changed],
            "audit_change": changed_by_audit.get(heat_id),
            "validation_status": {
                "decision_tree": "通过" if dt_assigned and not dt_row.get("violations") else "失败" if not dt_assigned or dt_row.get("violations") else "通过",
                "codex": "通过" if codex_assigned and not llm_row.get("violations") else "失败",
            },
        })

    expected_changes = sorted(changed_by_audit)
    actual_codex_changes = sorted(row["heat_id"] for row in heat_output if row["codex"]["changed"])
    if expected_changes and expected_changes != actual_codex_changes:
        fail(f"changed_assignments mismatch: audit={expected_changes}, derived={actual_codex_changes}")

    dt_result = audit.get("decision_tree") or {}
    codex_result = audit.get("codex_llm") or {}
    full_schedule = _full_plan_rows(source_audit, baseline, {row["heat_id"]: row for row in heat_output}, codex, origin)
    full_start = min(row["start_at"] for row in full_schedule if row["start_at"])
    full_end = max(row["end_at"] for row in full_schedule if row["end_at"])
    event_at = datetime.fromtimestamp(float(event["occurred_at"]), timezone.utc) if event.get("occurred_at") is not None else None
    if event_at is None:
        fail("event occurred_at is required for the normalized demo time axis")
    for row in full_schedule:
        if not row["affected"]:
            continue
        row_start = datetime.fromisoformat(row["start_at"])
        row_end = datetime.fromisoformat(row["end_at"])
        display_start_minute = DISPLAY_EVENT_MINUTE + (row_start - event_at).total_seconds() / 60.0
        display_end_minute = DISPLAY_EVENT_MINUTE + (row_end - event_at).total_seconds() / 60.0
        row["display_start_minute"] = round(display_start_minute, 3)
        row["display_end_minute"] = round(display_end_minute, 3)
        row["display_start_label"] = _demo_time_label(display_start_minute)
        row["display_end_label"] = _demo_time_label(display_end_minute)
    source_range_end = source_time_range[1] if len(source_time_range) > 1 else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": "tools/build_disturbance_gantt_drawio.py",
        "source_audit": str(source_path.relative_to(ROOT) if source_path.is_relative_to(ROOT) else source_path),
        "plan_source_audit": str(source_audit_path.relative_to(ROOT) if source_audit_path.is_relative_to(ROOT) else source_audit_path),
        "scenario_id": scenario_id,
        "scenario_kind": stress.get("scenario_kind"),
        "evidence_boundary": stress.get("evidence_boundary"),
        "time_axis": {
            "display_time_basis": "normalized_demo_axis",
            "display_start_minute": DISPLAY_AXIS_START_MINUTE,
            "display_end_minute": DISPLAY_AXIS_END_MINUTE,
            "display_start_label": _demo_time_label(DISPLAY_AXIS_START_MINUTE),
            "display_end_label": _demo_time_label(DISPLAY_AXIS_END_MINUTE),
            "display_event_minute": DISPLAY_EVENT_MINUTE,
            "display_event_time": _demo_time_label(DISPLAY_EVENT_MINUTE),
            "source_plan_start_at": full_start,
            "source_plan_end_at": full_end,
            "source_range_start": source_time_range[0],
            "source_range_end": source_range_end,
            "source_occurred_at": event_at.isoformat(),
            "tick_interval": "1h",
            "scale_note": "可见横轴固定为 10:00–20:00；源计划时间相对事故时刻整体平移，使事故在演示轴上固定为 11:00，持续时长与相对先后保持不变。",
        },
        "event_marker": {
            "kind": event.get("kind"),
            "resource_id": str(event.get("resource_id")),
            "occurred_at": event.get("occurred_at"),
            "event_at": event_at.isoformat() if event_at else None,
            "source_display_label": _precise_time_label(event_at),
            "display_label": _demo_time_label(DISPLAY_EVENT_MINUTE),
            "description": event.get("description"),
            "scenario_description_time_label": "11:00" if "11:00" in str(event.get("description") or "") else None,
            "controlled_scenario": True,
        },
        "impact_window": {
            "start_minute": display_start,
            "end_minute": display_end,
            "heat_count": len(affected_ids),
            "affected_heat_ids": affected_ids,
        },
        "branch_summary": {
            "baseline": {"heat_count": len(affected_ids), "source": "AP / baseline_full_assignments"},
            "decision_tree": {"assigned": dt_result.get("num_assigned"), "success": dt_result.get("success"), "path": dt_result.get("path"), "metrics": dt_result.get("metrics") or {}},
            "codex": {"assigned": codex_result.get("num_assigned"), "success": codex_result.get("success"), "path": codex_result.get("path"), "metrics": codex_result.get("metrics") or {}, "external_api_called": (audit.get("llm_invocation") or {}).get("external_api_called")},
        },
        "full_schedule": full_schedule,
        "heat_rows": heat_output,
        "assumptions": [
            "炉次→钢包表示预配包；转运任务→天车表示运输调度资源分配。",
            "当前审计没有取包点、落包点、实际任务时长和PLC连续坐标，图中不表示真实天车运动轨迹。",
            "受控压力输入与真实生产事故日志分开标记，行车2500离线用于可复现演示。",
            "图中统一使用 10:00–20:00 演示生产时间轴；源 occurred_at 仅保留在审计 JSON，不在图中混用。",
        ],
    }


def _value(text: str) -> str:
    escaped = html.escape(text, quote=True).replace("\n", "<br>")
    # draw.io interprets a literal <br> in an html=1 value. Keep only this
    # intentional tag unescaped; ElementTree escapes it once for XML.
    return escaped.replace("&lt;br&gt;", "<br>")


def _add_cell(root: ET.Element, cell_id: str, value: str = "", style: str = "", *, x: float = 0, y: float = 0, width: float = 0, height: float = 0, parent: str = "1", tooltip: str | None = None, vertex: bool = True, edge: bool = False, source: str | None = None, target: str | None = None) -> ET.Element:
    attrs = {"id": cell_id, "value": _value(value), "style": style, "parent": parent}
    if tooltip:
        attrs["tooltip"] = tooltip
    if vertex:
        attrs["vertex"] = "1"
    if edge:
        attrs["edge"] = "1"
        if source:
            attrs["source"] = source
        if target:
            attrs["target"] = target
    cell = ET.SubElement(root, "mxCell", attrs)
    geometry_attrs = {"x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry"}
    if edge:
        geometry_attrs = {"relative": "1", "as": "geometry"}
    ET.SubElement(cell, "mxGeometry", geometry_attrs)
    return cell


def _text_style(size: int = 12, color: str = COLORS["ink"], bold: bool = False, align: str = "left") -> str:
    return f"text;html=1;strokeColor=none;fillColor=none;align={align};verticalAlign=middle;fontSize={size};fontColor={color};fontStyle={1 if bold else 0};whiteSpace=wrap;"


def _box_style(fill: str, stroke: str, size: int = 12, bold: bool = True, align: str = "center") -> str:
    return f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor={COLORS['ink']};fontSize={size};fontStyle={1 if bold else 0};align={align};verticalAlign=middle;spacing=8;"


def _bar_style(fill: str, stroke: str, size: int = 11, color: str = COLORS["ink"]) -> str:
    return f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};fontColor={color};fontSize={size};fontStyle=1;align=left;verticalAlign=middle;spacingLeft=8;"


def _edge_style(color: str = COLORS["muted"], dashed: bool = False) -> str:
    return f"edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={color};strokeWidth=1.2;endArrow=block;{'dashed=1;' if dashed else ''}"


def _new_page(page_name: str, page_id: str, width: int, height: int) -> tuple[ET.Element, ET.Element]:
    diagram = ET.Element("diagram", {"id": page_id, "name": page_name})
    model = ET.SubElement(diagram, "mxGraphModel", {"dx": "1200", "dy": "800", "grid": "1", "gridSize": "4", "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1", "page": "1", "pageScale": "1", "pageWidth": str(width), "pageHeight": str(height), "math": "0", "shadow": "0"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return diagram, root


def _add_header(root: ET.Element, title: str, subtitle: str, width: int) -> None:
    _add_cell(root, "header_title", title, _text_style(24, COLORS["ink"], True), x=40, y=24, width=width - 80, height=36)
    _add_cell(root, "header_subtitle", subtitle, _text_style(11, COLORS["muted"]), x=40, y=62, width=width - 80, height=24)


def _add_legend(root: ET.Element, y: int, width: int) -> None:
    _add_cell(root, "legend_rule", "", f"line;strokeColor={COLORS['rule']};strokeWidth=1;", x=40, y=y, width=width - 80, height=1)
    entries = [("AP 原计划", COLORS["muted"]), ("AQ 决策树", COLORS["blue"]), ("AR Codex", COLORS["accent"]), ("事故/失败", COLORS["danger"])]
    x = 48
    for idx, (label, color) in enumerate(entries):
        _add_cell(root, f"legend_{idx}", label, _box_style(color, color, 10, True), x=x, y=y + 16, width=108, height=26)
        x += 128
    _add_cell(root, "legend_note", "模型边界：当前图展示计划调度状态，不是 PLC 实测天车运动轨迹。", _text_style(10, COLORS["muted"]), x=560, y=y + 16, width=width - 608, height=26)


def _build_global_page(data: dict[str, Any]) -> ET.Element:
    width, height = 1360, 760
    diagram, root = _new_page("01-全局甘特", "global", width, height)
    event = data["event_marker"]
    axis = data["time_axis"]
    scenario = data["scenario_id"]
    _add_header(root, "扰动响应甘特图", f"受控压力场景 · {scenario} · 计划时间轴 11:00–11:20", width)
    cards = [("受影响炉次", str(data["impact_window"]["heat_count"]), COLORS["muted"]), ("决策树", f"{data['branch_summary']['decision_tree']['assigned']}/31", COLORS["blue"]), ("Codex", f"{data['branch_summary']['codex']['assigned']}/31", COLORS["accent"]), ("Codex改配", str(sum(1 for row in data["heat_rows"] if row["codex"]["changed"])), COLORS["accent"]), ("事故资源", f"行车 {event['resource_id']}", COLORS["danger"])]
    for idx, (label, value, color) in enumerate(cards):
        x = 40 + idx * 256
        _add_cell(root, f"summary_{idx}", f"{label}<br>{value}", _box_style(COLORS["paper"], color, 14, True), x=x, y=104, width=232, height=60)

    left, timeline_x, timeline_w = 40, 260, 1040
    axis_y = 214
    _add_cell(root, "axis_label", "演示时间", _text_style(10, COLORS["muted"], True), x=40, y=axis_y - 20, width=200, height=20)
    for minute in range(60, 81):
        x = timeline_x + (minute - 60) / 20 * timeline_w
        _add_cell(root, f"tick_{minute}", f"{minute // 60:02d}:{minute % 60:02d}", _text_style(9, COLORS["soft"], False, "center"), x=x - 24, y=axis_y - 20, width=48, height=20)
        _add_cell(root, f"grid_{minute}", "", f"line;strokeColor={COLORS['rule']};strokeWidth=1;dashed=1;", x=x, y=axis_y, width=1, height=310)
    rows = [
        ("AP 全量预配计划", 244, 60, 80, COLORS["muted"], "457 炉基线；炉次→钢包"),
        ("事故：行车 2500 离线", 292, 60, 80, COLORS["danger"], "11:00 受控压力输入"),
        ("局部影响窗口", 340, 60, 80, COLORS["blue"], "31 炉；未影响炉次保持冻结"),
        ("AQ 决策树局部重排", 388, 60, 66, COLORS["blue"], "30/31；有 1 炉未分配"),
        ("AR Codex 介入与重排", 436, 60.5, 70, COLORS["accent"], "31/31；改配 3 炉"),
        ("最终可执行方案", 484, 60, 80, COLORS["green"], "通过校验后合并"),
    ]
    for idx, (label, y, start, end, color, note) in enumerate(rows):
        _add_cell(root, f"row_label_{idx}", label, _text_style(11, COLORS["ink"], True), x=40, y=y, width=200, height=28)
        x = timeline_x + (start - 60) / 20 * timeline_w
        w = max(16, (end - start) / 20 * timeline_w)
        fill = COLORS["accent_tint"] if color == COLORS["accent"] else COLORS["paper"]
        if color == COLORS["danger"]:
            fill = COLORS["danger_tint"]
        _add_cell(root, f"gantt_bar_{idx}", note, _bar_style(fill, color, 10), x=x, y=y, width=w, height=28, tooltip=f"scenario={scenario}; {label}; {note}")
    event_x = timeline_x
    _add_cell(root, "event_line", "", f"line;strokeColor={COLORS['danger']};strokeWidth=2;dashed=1;", x=event_x, y=axis_y - 12, width=2, height=326)
    _add_cell(root, "event_label", "事故发生 · 11:00", _box_style(COLORS["danger_tint"], COLORS["danger"], 10, True), x=event_x + 12, y=axis_y + 8, width=120, height=28, tooltip=f"event={event['kind']}; resource={event['resource_id']}")
    _add_cell(root, "window_bracket", "31 炉局部窗口", f"rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor={COLORS['blue']};dashed=1;fontColor={COLORS['blue']};fontSize=10;align=center;verticalAlign=top;", x=timeline_x, y=axis_y + 342, width=timeline_w, height=32)
    _add_cell(root, "global_takeaway", "阅读顺序：事故发生 → 影响窗口锁定 → 决策树先行 → 决策树不完整 → Codex 补全 → 校验后形成可执行方案", _box_style(COLORS["accent_tint"], COLORS["accent"], 12, True, "left"), x=40, y=590, width=1040, height=48)
    _add_cell(root, "global_side", "本图展示什么？<br>• AP：扰动前的全量预配包<br>• AQ：决策树局部重排<br>• AR：Codex 独立重排<br>• 天车字段：转运任务资源，不是连续运动轨迹", _box_style(COLORS["paper"], COLORS["rule"], 11, False, "left"), x=1120, y=214, width=200, height=232)
    _add_legend(root, 672, width)
    return diagram


def _build_heat_page(data: dict[str, Any]) -> ET.Element:
    width, height = 1540, 1320
    diagram, root = _new_page("02-受影响炉次", "affected-heats", width, height)
    _add_header(root, "受影响炉次与重排去向", f"{data['impact_window']['heat_count']} 炉 · 每行显示 AP 原计划 / AQ 决策树 / AR Codex", width)
    headers = [(40, 200, "炉次 / 时间"), (250, 190, "计划窗口"), (460, 190, "AP 原计划"), (670, 190, "AQ 决策树"), (880, 190, "AR Codex"), (1090, 390, "状态 / 校验")]
    for x, w, label in headers:
        _add_cell(root, f"table_header_{x}", label, _box_style(COLORS["ink"], COLORS["ink"], 11, True), x=x, y=104, width=w, height=32)
    for idx, row in enumerate(data["heat_rows"]):
        y = 144 + idx * 32
        status = row["status"]
        is_codex = row["codex"]["changed"]
        is_failed = not row["decision_tree"]["assigned"]
        row_fill = COLORS["accent_tint"] if is_codex else COLORS["danger_tint"] if is_failed else COLORS["paper"]
        stroke = COLORS["accent"] if is_codex else COLORS["danger"] if is_failed else COLORS["rule"]
        tip = f"scenario={data['scenario_id']}; heat={row['heat_id']}; AP={row['baseline']['display']}; AQ={row['decision_tree']['display']}; AR={row['codex']['display']}"
        _add_cell(root, f"heat_{data['scenario_id']}_{row['heat_id']}", f"{row['heat_id']}<br>{row['refining_route'] or '-'}", _box_style(row_fill, stroke, 9, is_codex, "left"), x=40, y=y, width=200, height=28, tooltip=tip)
        _add_cell(root, f"heat_{data['scenario_id']}_{row['heat_id']}_timeline", f"{row['plan_start']:.1f}–{row['plan_end']:.1f}", _bar_style(COLORS["blue_tint"], COLORS["blue"], 9), x=250, y=y, width=190, height=28, tooltip=f"source window={row['source_window_start']}–{row['source_window_end']}")
        for branch, x, color, fill in (("baseline", 460, COLORS["muted"], COLORS["paper"]), ("decision_tree", 670, COLORS["blue"], COLORS["blue_tint"]), ("codex", 880, COLORS["accent"], COLORS["accent_tint"] if is_codex else COLORS["paper"])):
            branch_row = row[branch]
            _add_cell(root, f"heat_{data['scenario_id']}_{row['heat_id']}_{branch}", branch_row["display"], _bar_style(fill, color, 9), x=x, y=y, width=190, height=28, tooltip=f"{branch}; heat={row['heat_id']}; reason={branch_row.get('reason')}")
        validation = f"{status} · AQ {row['validation_status']['decision_tree']} / AR {row['validation_status']['codex']}"
        _add_cell(root, f"heat_{data['scenario_id']}_{row['heat_id']}_status", validation, _text_style(9, COLORS["accent"] if is_codex else COLORS["danger"] if is_failed else COLORS["muted"], is_codex or is_failed), x=1090, y=y, width=390, height=28)
    _add_legend(root, height - 84, width)
    return diagram


def _build_branch_page(data: dict[str, Any]) -> ET.Element:
    width, height = 1360, 760
    diagram, root = _new_page("03-双线路决策", "branches", width, height)
    _add_header(root, "两条独立响应线路", "同一 AP 基线与事故快照；AQ 与 AR 不互相读取分配结果", width)
    boxes = {
        "ap": (48, 180, 190, 84, "AP\n扰动前预配包\n炉次 → 钢包", COLORS["muted"], COLORS["paper"]),
        "impact": (300, 180, 190, 84, "事故裁剪\n行车 2500 离线\n31 炉进入局部窗口", COLORS["danger"], COLORS["danger_tint"]),
        "dt": (560, 112, 210, 84, "AQ 决策树\n局部重排", COLORS["blue"], COLORS["blue_tint"]),
        "dtv": (840, 112, 210, 84, "AQ 共享校验\n30/31", COLORS["blue"], COLORS["blue_tint"]),
        "codex": (560, 300, 210, 84, "AR Codex\n决策树失败后介入", COLORS["accent"], COLORS["accent_tint"]),
        "codexv": (840, 300, 210, 84, "AR 共享校验\n31/31", COLORS["accent"], COLORS["accent_tint"]),
        "final": (1120, 206, 190, 96, "最终方案\n合并冻结结果\n可执行", COLORS["green"], COLORS["green_tint"]),
    }
    edge_specs = [("e_ap_impact", "", "ap", "impact", COLORS["muted"], False), ("e_impact_dt", "同一事故快照", "impact", "dt", COLORS["blue"], False), ("e_dt_validate", "校验", "dt", "dtv", COLORS["blue"], False), ("e_impact_codex", "DT 不完整", "impact", "codex", COLORS["accent"], True), ("e_codex_validate", "校验", "codex", "codexv", COLORS["accent"], False), ("e_dt_final", "通过/合并", "dtv", "final", COLORS["green"], False), ("e_codex_final", "通过/合并", "codexv", "final", COLORS["green"], False)]
    for edge_id, label, source, target, color, dashed in edge_specs:
        _add_cell(root, edge_id, label, _edge_style(color, dashed), parent="1", edge=True, source=source, target=target, vertex=False)
    for node_id, (x, y, w, h, label, stroke, fill) in boxes.items():
        _add_cell(root, node_id, label, _box_style(fill, stroke, 13, True), x=x, y=y, width=w, height=h, tooltip=f"scenario={data['scenario_id']}; node={node_id}")
    changed = [row for row in data["heat_rows"] if row["codex"]["changed"]]
    card_x = 48
    for idx, row in enumerate(changed):
        _add_cell(root, f"change_card_{idx}", f"Codex 改配 {row['heat_id']}<br>AP {row['baseline']['display']} → AR {row['codex']['display']}", _box_style(COLORS["accent_tint"], COLORS["accent"], 10, True, "left"), x=48 + idx * 300, y=500, width=276, height=58, tooltip=f"heat={row['heat_id']}; audit={row['audit_change']}")
    _add_cell(root, "branch_note", "关键语义：预配包先回答“哪个炉次用哪个钢包”；天车字段回答“由哪台天车执行转运任务”。当前审计没有实际取包/落包轨迹，因此不能把这张图理解为连续运动仿真。", _box_style(COLORS["paper"], COLORS["rule"], 11, False, "left"), x=48, y=610, width=1264, height=58)
    _add_legend(root, 690, width)
    return diagram


def _affected_schedule_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    affected_ids = set(data["impact_window"]["affected_heat_ids"])
    return [row for row in data["full_schedule"] if row["heat_id"] in affected_ids]


def _chart_x(value: float, start: float, end: float, left: int, width: int) -> float:
    span = max(end - start, 1.0)
    return left + (value - start) / span * width


def _add_schedule_axis(root: ET.Element, data: dict[str, Any], *, start: float, end: float, left: int, width: int, top: int, bottom: int) -> None:
    tick = int(start)
    while tick <= end:
        x = _chart_x(tick, start, end, left, width)
        if left <= x <= left + width:
            label = _demo_time_label(tick)
            _add_cell(root, f"axis_{tick}", label, _text_style(10, COLORS["soft"], False, "center"), x=x - 48, y=top - 28, width=96, height=22)
            _add_cell(root, f"axis_grid_{tick}", "", f"line;strokeColor={COLORS['rule']};strokeWidth=1;dashed=1;", x=x, y=top, width=1, height=bottom - top)
        tick += 60
    _add_cell(root, "axis_caption", "演示生产时间", _text_style(10, COLORS["muted"], True), x=40, y=top - 28, width=left - 56, height=22)


def _schedule_page(data: dict[str, Any], *, post_event: bool) -> ET.Element:
    rows = _affected_schedule_rows(data)
    start = float(data["time_axis"]["display_start_minute"])
    end = float(data["time_axis"]["display_end_minute"])
    width = 1840
    left = 540
    chart_width = 1240
    top = 240
    row_height = 40
    bottom = top + len(rows) * row_height
    height = bottom + 120
    page_name = "02-离线后受影响炉次" if post_event else "01-离线前受影响炉次"
    page_id = "post-event-plan" if post_event else "pre-event-plan"
    diagram, root = _new_page(page_name, page_id, width, height)
    title = "行车离线后：受影响炉次重排结果" if post_event else "行车离线前：受影响炉次原计划"
    subtitle = (
        f"仅展开 {len(rows)} 个受影响炉次 · 演示生产时间 10:00–20:00 · 其余 {len(data['full_schedule']) - len(rows)} 炉省略"
        if not post_event else
        f"仅展开 {len(rows)} 个受影响炉次 · 事故 11:00 · Codex 改配 {sum(1 for row in rows if row['status'] == 'Codex改配')} 炉"
    )
    _add_header(root, title, subtitle, width)
    context = f"此前/此后正常计划共 {len(data['full_schedule']) - len(rows)} 炉，未受本次扰动影响，图中省略。"
    if post_event:
        context += " 蓝色标签＝受扰动但保持计划；红色整行＝Codex 改配。"
    _add_cell(root, "omitted_context", context, _box_style(COLORS["paper"], COLORS["rule"], 10, False, "left"), x=40, y=100, width=left + chart_width - 40, height=36)
    if post_event:
        event_minute = float(data["time_axis"]["display_event_minute"])
        event_x = _chart_x(event_minute, start, end, left, chart_width)
        _add_cell(root, "offline_line", "", f"line;strokeColor={COLORS['danger']};strokeWidth=3;dashed=1;", x=event_x, y=top - 20, width=2, height=bottom - top + 20)
        label = f"11:00\n行车 {data['event_marker']['resource_id']} 离线"
        _add_cell(root, "offline_label", label, _box_style(COLORS["danger_tint"], COLORS["danger"], 11, True), x=min(event_x + 12, left + chart_width - 172), y=top - 92, width=160, height=48, tooltip=data["event_marker"].get("description"))
        if rows:
            affected_start = min(float(row["display_start_minute"]) for row in rows)
            affected_end = max(float(row["display_end_minute"]) for row in rows)
            x1 = _chart_x(affected_start, start, end, left, chart_width)
            x2 = _chart_x(affected_end, start, end, left, chart_width)
            _add_cell(root, "affected_window_band", "", f"rounded=0;whiteSpace=wrap;html=1;fillColor={COLORS['blue_tint']};fillOpacity=24;strokeColor={COLORS['blue']};strokeWidth=2;dashed=1;", x=x1, y=top - 8, width=max(12, x2 - x1), height=bottom - top + 16, tooltip=f"演示时间 {_demo_time_label(affected_start)} → {_demo_time_label(affected_end)}")
            _add_cell(root, "affected_window", f"31 炉受影响区 · {_demo_time_label(affected_start)}–{_demo_time_label(affected_end)}", f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['blue_tint']};strokeColor={COLORS['blue']};strokeWidth=2;fontColor={COLORS['blue']};fontSize=11;fontStyle=1;align=center;verticalAlign=middle;", x=x1, y=top - 60, width=max(160, x2 - x1), height=32)
    _add_schedule_axis(root, data, start=start, end=end, left=left, width=chart_width, top=top, bottom=bottom)
    for index, row in enumerate(rows):
        y = top + index * row_height
        row_start = float(row["display_start_minute"])
        row_end = float(row["display_end_minute"])
        x1 = _chart_x(row_start, start, end, left, chart_width)
        x2 = _chart_x(row_end, start, end, left, chart_width)
        bar_width = max(5, x2 - x1)
        is_codex = post_event and row["status"] == "Codex改配"
        if is_codex:
            _add_cell(root, f"codex_row_{row['heat_id']}", "", f"rounded=1;whiteSpace=wrap;html=1;fillColor={COLORS['danger_tint']};strokeColor={COLORS['danger']};strokeWidth=2;", x=24, y=y + 2, width=width - 48, height=36)
        stroke = COLORS["danger"] if is_codex else row["color"]
        fill = row["color"]
        label = row["heat_id"]
        compact_time = f"{row['display_start_label']}–{row['display_end_label']}"
        assignment_label = row["final_assignment"] if post_event else row["baseline_assignment"]
        if post_event and row["affected"]:
            if is_codex:
                assignment_label = f"AP {row['baseline_assignment']} → AR {row['final_assignment']}"
            else:
                assignment_label = f"{assignment_label} · {row['branch']}"
        left_text = f"{label}\n{compact_time} · {assignment_label}"
        badge_text = "CODEX 改配" if is_codex else "保持原计划" if post_event else "受影响范围"
        badge_fill = COLORS["danger"] if is_codex else COLORS["blue_tint"]
        badge_text_color = "#ffffff" if is_codex else COLORS["blue"]
        badge_stroke = COLORS["danger"] if is_codex else COLORS["blue"]
        _add_cell(root, f"schedule_badge_{row['heat_id']}", badge_text, f"rounded=1;whiteSpace=wrap;html=1;fillColor={badge_fill};strokeColor={badge_stroke};strokeWidth={2 if is_codex else 1};fontColor={badge_text_color};fontSize=9;fontStyle=1;align=center;verticalAlign=middle;", x=40, y=y + 7, width=96, height=24)
        _add_cell(root, f"schedule_label_{row['heat_id']}", left_text, _text_style(9, COLORS["ink"], is_codex), x=148, y=y, width=372, height=36)
        bar_style = _bar_style(fill, stroke, 9, COLORS["ink"]) + ("strokeWidth=4;" if is_codex else "strokeWidth=1;")
        _add_cell(root, f"schedule_bar_{row['heat_id']}", "", bar_style, x=x1, y=y + 7, width=bar_width, height=24, tooltip=(
            f"炉次={row['heat_id']}\n演示开始={row['display_start_label']}\n演示结束={row['display_end_label']}\n"
            f"钢包={row['ladle_id'] or '未分配'}\n行车={row['crane_id'] or '未分配'}\n状态={row['status']}"
        ))
        if is_codex:
            change_text = f"Codex：AP {row['baseline_assignment']} → AR {row['final_assignment']}"
            change_x = x2 + 8
            change_width = 276
            if change_x + change_width > left + chart_width:
                change_x = max(left + 8, x1 - change_width - 8)
            _add_cell(
                root,
                f"codex_change_{row['heat_id']}",
                change_text,
                _box_style(COLORS["danger_tint"], COLORS["danger"], 9, True, "left"),
                x=change_x,
                y=y + 4,
                width=change_width,
                height=30,
                tooltip=f"AP 原计划={row['baseline_assignment']}; AR Codex={row['final_assignment']}",
            )
    note_y = bottom + 18
    note = "每行是一个受影响炉次；左侧为炉次号和计划起止时间，彩色条表示该炉次的完整计划窗口。"
    if post_event:
        note += " 蓝色状态标签表示保持计划；红色整行、红色粗框和 AP→AR 说明框共同标出模型改配炉次。时间条保持不变，表示炉次生产窗口未被改动。"
    _add_cell(root, "chart_note", note, _box_style(COLORS["paper"], COLORS["rule"], 11, False, "left"), x=40, y=note_y, width=left + chart_width - 40, height=42)
    _add_cell(root, "chart_boundary", "条内 STxx / 行车号是钢包与转运资源分配；这不是 PLC 实测天车连续运动轨迹。", _text_style(10, COLORS["muted"]), x=40, y=note_y + 52, width=left + chart_width - 40, height=22)
    return diagram


def build_drawio(data: dict[str, Any]) -> ET.ElementTree:
    root = ET.Element("mxfile", {"host": "app.diagrams.net", "agent": "steel-ladle-gantt", "version": "24.0.0", "type": "device"})
    root.append(_schedule_page(data, post_event=False))
    root.append(_schedule_page(data, post_event=True))
    return ET.ElementTree(root)


def validate_semantics(data: dict[str, Any]) -> None:
    if data["impact_window"]["heat_count"] != len(data["heat_rows"]):
        fail("diagram heat count does not match heat_rows")
    if data["event_marker"]["resource_id"] != "2500":
        fail(f"expected fixture event resource 2500, got {data['event_marker']['resource_id']}")
    heat_ids = [row["heat_id"] for row in data["heat_rows"]]
    if len(set(heat_ids)) != len(heat_ids):
        fail("diagram heat_rows contains duplicate heat IDs")
    if len(data.get("full_schedule") or []) != 457:
        fail(f"full schedule must contain 457 heats, got {len(data.get('full_schedule') or [])}")
    if len({row["color"] for row in data["full_schedule"]}) < 450:
        fail("full schedule heat colors are not sufficiently distinct")
    affected_schedule = [row for row in data["full_schedule"] if row["affected"]]
    if any(
        float(row["display_start_minute"]) < DISPLAY_AXIS_START_MINUTE
        or float(row["display_end_minute"]) > DISPLAY_AXIS_END_MINUTE
        for row in affected_schedule
    ):
        fail("affected heat falls outside the normalized 10:00-20:00 display axis")
    if any("heat_" not in row["element_key"] or data["scenario_id"] not in row["element_key"] for row in data["heat_rows"]):
        fail("unstable heat element key")


def write_outputs(data: dict[str, Any], output_dir: Path) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "diagram_data.json"
    drawio_path = output_dir / "disturbance_gantt.drawio"
    readme_path = output_dir / "README.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tree = build_drawio(data)
    ET.indent(tree, space="  ")
    tree.write(drawio_path, encoding="utf-8", xml_declaration=True)
    readme_path.write_text(
        "# 扰动响应甘特图\n\n"
        f"- 场景：`{data['scenario_id']}`\n"
        f"- 数据来源：`{data['source_audit']}`\n"
        f"- 全量计划来源：`{data['plan_source_audit']}`\n"
        "- 页面：`01-离线前受影响炉次`、`02-离线后受影响炉次`\n"
        f"- 只展开受影响炉次：`{data['impact_window']['heat_count']}`；其余 `{len(data['full_schedule']) - data['impact_window']['heat_count']}` 炉压缩为上下文说明。\n"
        "- 语义：AP/AQ/AR 分别表示原计划、决策树重排和 Codex 重排；炉次到钢包是预配包，转运任务到天车是资源调度。\n"
        "- 横轴：统一使用 10:00–20:00 演示生产时间；事故固定为 11:00，炉次持续时长与相对先后取自源数据。\n"
        "- 时间审计：源 occurred_at 和源炉次时间保留在 diagram_data.json 与图形 tooltip，不与可见演示时间混用。\n"
        "- 视觉区分：蓝色标签表示受扰动但保持计划；红色整行、粗框与 CODEX 改配标签表示模型改配。\n"
        "- 边界：当前源数据没有取包点、落包点、任务持续时间或 PLC 连续坐标，因此图中天车不是实测运动轨迹。\n",
        encoding="utf-8",
    )
    return drawio_path, json_path, readme_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        data = build_diagram_data(load_json(args.audit), args.audit)
        validate_semantics(data)
        paths = write_outputs(data, args.out_dir)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"drawio": str(paths[0]), "diagram_data": str(paths[1]), "readme": str(paths[2]), "affected_heats": len(data["heat_rows"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
