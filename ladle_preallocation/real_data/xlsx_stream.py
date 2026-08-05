"""Low-memory XLSX row streaming for the production CRANE history."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterator
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ladle_preallocation.data_modeling.alignment import CRANE_COLUMNS, align_crane_row
from ladle_preallocation.real_data.reader import CRANE_SHEET, parse_production_time

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CELL_REFERENCE = re.compile(r"([A-Z]+)[0-9]+")


@dataclass(frozen=True)
class CraneStreamStats:
    source_rows_scanned: int
    rows_in_time_range: int
    online_rows_in_time_range: int
    real_crane_count: int
    observed_time_range: tuple[str, str] | None
    missing_counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_rows_scanned": self.source_rows_scanned,
            "rows_in_time_range": self.rows_in_time_range,
            "online_rows_in_time_range": self.online_rows_in_time_range,
            "real_crane_count": self.real_crane_count,
            "observed_time_range": list(self.observed_time_range) if self.observed_time_range else None,
            "missing_counts": self.missing_counts,
        }


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    values: list[str] = []
    with archive.open("xl/sharedStrings.xml") as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if element.tag == MAIN_NS + "si":
                values.append("".join(node.text or "" for node in element.iter(MAIN_NS + "t")))
                element.clear()
    return values


def _worksheet_path(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relation_id = None
    for sheet in workbook.iter(MAIN_NS + "sheet"):
        if sheet.get("name") == sheet_name:
            relation_id = sheet.get(REL_NS + "id")
            break
    if not relation_id:
        raise ValueError(f"未找到行车工作表: {sheet_name}")
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = None
    for relation in relationships.iter(PKG_REL_NS + "Relationship"):
        if relation.get("Id") == relation_id:
            target = relation.get("Target")
            break
    if not target:
        raise ValueError(f"未找到工作表关系: {sheet_name}")
    return str(PurePosixPath("xl") / target.lstrip("/"))


def _column_index(reference: str) -> int:
    match = CELL_REFERENCE.match(reference)
    if not match:
        raise ValueError(f"无效单元格引用: {reference}")
    result = 0
    for character in match.group(1):
        result = result * 26 + ord(character) - 64
    return result - 1


def _cell_value(cell: ET.Element, shared: list[str]) -> Any:
    raw = next((node.text or "" for node in cell.iter(MAIN_NS + "v")), "")
    if cell.get("t") == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(MAIN_NS + "t"))
    return raw or None


def iter_crane_rows(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield aligned CRANE records without materialising the full worksheet."""
    with ZipFile(path) as archive:
        shared = _shared_strings(archive)
        worksheet = _worksheet_path(archive, CRANE_SHEET)
        with archive.open(worksheet) as source:
            row_number = 0
            for _, element in ET.iterparse(source, events=("end",)):
                if element.tag != MAIN_NS + "row":
                    continue
                row_number += 1
                if row_number == 1:
                    element.clear()
                    continue
                values: list[Any] = [None] * len(CRANE_COLUMNS)
                for cell in element.findall(MAIN_NS + "c"):
                    index = _column_index(cell.get("r", ""))
                    if 0 <= index < len(values):
                        values[index] = _cell_value(cell, shared)
                element.clear()
                if any(value not in (None, "") for value in values):
                    yield align_crane_row(values)


def read_latest_online_cranes_stream(
    path: str | Path,
    start_at: float,
    end_at: float,
) -> tuple[list[dict[str, Any]], CraneStreamStats]:
    """Return the latest real online snapshot per crane in a Unix time range."""
    latest: dict[str, tuple[float, dict[str, Any]]] = {}
    scanned = in_range = online = 0
    observed: list[str] = []
    missing: Counter[str] = Counter()
    for record in iter_crane_rows(path):
        scanned += 1
        timestamp, invalid = parse_production_time(record.get("updated_at"))
        if invalid or timestamp is None or timestamp < start_at or timestamp > end_at:
            continue
        in_range += 1
        observed.append(str(record.get("updated_at")))
        if str(record.get("online_status")).strip() not in {"1", "1.0"}:
            continue
        online += 1
        for field in ("crane_id", "position_x", "updated_at", "max_load_tonnes"):
            if record.get(field) in (None, ""):
                missing[field] += 1
        identifier = str(record.get("crane_id") or "").strip()
        if not identifier:
            continue
        if identifier not in latest or timestamp > latest[identifier][0]:
            latest[identifier] = (timestamp, record)
    snapshots = [value[1] for value in sorted(latest.values(), key=lambda item: str(item[1]["crane_id"]))]
    stats = CraneStreamStats(
        source_rows_scanned=scanned,
        rows_in_time_range=in_range,
        online_rows_in_time_range=online,
        real_crane_count=len(snapshots),
        observed_time_range=(min(observed), max(observed)) if observed else None,
        missing_counts=dict(missing),
    )
    return snapshots, stats
