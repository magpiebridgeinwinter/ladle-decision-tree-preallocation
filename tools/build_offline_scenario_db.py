"""Build the reproducible offline scenario database and compact audit summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ladle_preallocation.offline_scenarios import ScenarioRepository, build_scenario_records, write_database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-audit", type=Path, default=ROOT / "outputs/real_data_location_aware/decision_tree_audit.json")
    parser.add_argument("--database", type=Path, default=ROOT / "outputs/offline_scenarios/ladle_scenarios.sqlite3")
    parser.add_argument("--summary", type=Path, default=ROOT / "outputs/offline_scenarios/summary.json")
    args = parser.parse_args()

    records = build_scenario_records(args.source_audit)
    database = write_database(records, args.database)
    repository = ScenarioRepository(database)
    summary = repository.summary()
    summary["database"] = str(database.relative_to(ROOT) if database.is_relative_to(ROOT) else database)
    summary["source_audit"] = str(args.source_audit.relative_to(ROOT) if args.source_audit.is_relative_to(ROOT) else args.source_audit)
    summary["scenario_ids"] = [row["scenario_id"] for row in repository.list_scenarios()]
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
