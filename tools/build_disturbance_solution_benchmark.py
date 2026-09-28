"""Build the audited cross-scenario disturbance solution benchmark."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ladle_preallocation.evaluation.benchmark import (
    build_benchmark,
    heat_csv_rows,
    load_factory_ladle_mapping,
    scenario_csv_rows,
)
from ladle_preallocation.offline_scenarios import build_scenario_records
from ladle_preallocation.real_data.audit import load_location_aware_audit


DEFAULT_AUDIT = ROOT / "outputs/real_data_location_aware/decision_tree_audit.json"
DEFAULT_FACTORY_PLAN = ROOT / "data/desktop_data/PLAN(1).xlsx"
DEFAULT_OUTPUT = ROOT / "outputs/disturbance_solution_benchmark"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"cannot write an empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_outputs(source_audit: Path, factory_plan: Path, output_dir: Path) -> dict[str, Any]:
    source = load_location_aware_audit(source_audit)
    records = build_scenario_records(source_audit)
    factory_ladles, factory_metadata = load_factory_ladle_mapping(factory_plan)
    benchmark = build_benchmark(records, source, factory_ladles, factory_metadata)
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark_path = output_dir / "benchmark.json"
    scenario_path = output_dir / "scenario_comparison.csv"
    heat_path = output_dir / "heat_comparison.csv"
    benchmark_path.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(scenario_path, scenario_csv_rows(benchmark))
    _write_csv(heat_path, heat_csv_rows(benchmark))
    return {
        "benchmark": str(benchmark_path),
        "scenario_csv": str(scenario_path),
        "heat_csv": str(heat_path),
        "summary": benchmark["summary"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--factory-plan", type=Path, default=DEFAULT_FACTORY_PLAN)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build_outputs(args.source_audit, args.factory_plan, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
