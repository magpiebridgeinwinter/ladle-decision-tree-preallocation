from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from ladle_preallocation.real_data.pipeline import filter_plan_records, plan_key
from ladle_preallocation.real_data.xlsx_stream import iter_crane_rows, read_latest_online_cranes_stream

WORKBOOK = '''<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="CRANE_STATUS_HIS - 副本" sheetId="1" r:id="rId1"/></sheets></workbook>'''
RELS = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''


def _cell(column: str, row: int, value: str | int | float | None) -> str:
    return "" if value is None else f'<c r="{column}{row}" t="inlineStr"><is><t>{value}</t></is></c>'


def _crane_row(row: int, crane: str, updated: str, online: int = 1, position: int = 10000) -> str:
    values = [row, crane, position, 0, 0, "A", online, updated, 2, 300, 30, 45, 48, 10, 0, 48, 0, 1, 1, None]
    cells = []
    for index, value in enumerate(values):
        number, label = index + 1, ""
        while number:
            number, remainder = divmod(number - 1, 26)
            label = chr(65 + remainder) + label
        cells.append(_cell(label, row, value))
    return f'<row r="{row}">{"".join(cells)}</row>'


def _fixture(path: Path) -> None:
    rows = [
        '<row r="1"><c r="A1" t="inlineStr"><is><t>header</t></is></c></row>',
        _crane_row(2, "3170", "2026-03-06-08.00.00.000000", 1, 10000),
        _crane_row(3, "3170", "2026-03-06-09.00.00.000000", 1, 12000),
        _crane_row(4, "3180", "2026-03-06-08.30.00.000000", 0, 20000),
        _crane_row(5, "3190", "2025-03-24-08.30.00.000000", 1, 30000),
    ]
    sheet = '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(rows) + '</sheetData></worksheet>'
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", RELS)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


class RealDataTests(unittest.TestCase):
    def test_stream_reader_keeps_latest_online_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "CRANE.xlsx"
            _fixture(path)
            self.assertEqual(len(list(iter_crane_rows(path))), 4)
            snapshots, stats = read_latest_online_cranes_stream(path, 1772780000, 1772790000)
            self.assertEqual([row["crane_id"] for row in snapshots], ["3170"])
            self.assertEqual(snapshots[0]["position_x"], "12000")
            self.assertEqual(stats.source_rows_scanned, 4)

    def test_plan_filter_uses_dominant_month_and_explains_exclusion(self) -> None:
        rows = [
            {"heat_id": "H1", "plan_sequence": 1, "tap_finish_at": "2026-03-06-08.00.00", "location_mapping_status": "已匹配"},
            {"heat_id": "H2", "plan_sequence": 2, "tap_finish_at": "2026-03-07-08.00.00", "location_mapping_status": "已匹配"},
            {"heat_id": "H3", "plan_sequence": 3, "tap_finish_at": "2025-03-24-08.00.00", "location_mapping_status": "已匹配"},
        ]
        included, excluded, month = filter_plan_records(rows)
        self.assertEqual(month, "2026-03")
        self.assertEqual(len(included), 2)
        self.assertIn("不在评测月份", excluded["H3::3"])
        self.assertEqual(plan_key(rows[0]), "H1::1")


if __name__ == "__main__":
    unittest.main()
