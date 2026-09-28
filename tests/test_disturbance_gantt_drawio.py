from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/build_disturbance_gantt_drawio.py"
AUDIT = ROOT / "outputs/real_data_codex_stress_demo/audit.json"


def test_real_stress_scenario_generates_traceable_drawio() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        output = subprocess.run(
            [sys.executable, str(SCRIPT), "--audit", str(AUDIT), "--out-dir", temp_dir],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(output.stdout)
        diagram_data = json.loads((Path(temp_dir) / "diagram_data.json").read_text(encoding="utf-8"))
        drawio = (Path(temp_dir) / "disturbance_gantt.drawio").read_text(encoding="utf-8")
        assert result["affected_heats"] == 31
        assert diagram_data["event_marker"]["resource_id"] == "2500"
        assert diagram_data["branch_summary"]["decision_tree"]["assigned"] == 30
        assert diagram_data["branch_summary"]["codex"]["assigned"] == 31
        assert len(diagram_data["heat_rows"]) == 31
        assert len(diagram_data["full_schedule"]) == 457
        assert len({row["color"] for row in diagram_data["full_schedule"]}) >= 450
        assert diagram_data["time_axis"]["display_time_basis"] == "normalized_demo_axis"
        assert diagram_data["time_axis"]["display_start_label"] == "10:00"
        assert diagram_data["time_axis"]["display_event_time"] == "11:00"
        assert diagram_data["time_axis"]["display_end_label"] == "20:00"
        assert diagram_data["time_axis"]["source_plan_start_at"].startswith("2026-03-06T00:19:53")
        affected_schedule = [row for row in diagram_data["full_schedule"] if row["affected"]]
        assert min(row["display_start_label"] for row in affected_schedule) == "11:26"
        assert max(row["display_end_label"] for row in affected_schedule) == "19:03"
        changed = [row["heat_id"] for row in diagram_data["heat_rows"] if row["codex"]["changed"]]
        assert changed == ["DT0142D1-300759", "DT0143D8-300767", "DT0164D1-300776"]
        assert all(diagram_data["scenario_id"] in row["element_key"] for row in diagram_data["heat_rows"])
        assert all(name in drawio for name in ("01-决策树重排-1炉失效", "02-Codex重排-补全失效炉次"))
        assert "2026-03-06 21:15:00" not in drawio
        assert "2026-03" not in drawio and "2026-03-07" not in drawio
        assert "真实时间" not in drawio and "演示标签" not in drawio
        assert "10:00" in drawio and "20:00" in drawio and "11:00" in drawio
        assert "行车 2500" in drawio and "Codex" in drawio
        assert drawio.count('id="schedule_badge_') == 62
        assert drawio.count('value="决策树失效"') == 1
        assert drawio.count('value="CODEX 补全"') == 1
        assert drawio.count('id="focus_row_') == 2
        assert drawio.count('id="focus_change_') == 2
        assert "决策树未完成：钢包、行车均未分配" in drawio
        assert "Codex 已补全：ST36 / 1520 / 路线 A1" in drawio
        assert "JU6310E7-300751" in drawio
        assert drawio.count('id="schedule_bar_') == 62
        assert "同一事故、同一 31 炉窗口、同一时间轴" in drawio


def test_invalid_audit_fails_without_partial_output() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        bad_audit = Path(temp_dir) / "bad.json"
        bad_audit.write_text(json.dumps({"scenario_id": "bad"}), encoding="utf-8")
        output_dir = Path(temp_dir) / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--audit", str(bad_audit), "--out-dir", str(output_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert not output_dir.exists()
