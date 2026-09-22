"""Known position codes are decoded; unknown codes remain usable raw values."""
from __future__ import annotations

KNOWN_POSITIONS = {"4QF5": "4跨-Q行-F区域-5排位", "3QF5": "3跨-Q行-F区域-5排位", "1TF6": "1跨-T行-F区域-6排位", "1GF6": "1跨-G行-F区域-6排位", "2QF5": "2跨-Q行-F区域-5排位", "3CC7": "3跨-C行-C区域-7排位", "4CC7": "4跨-C行-C区域-7排位"}


def decode_position(code: object) -> dict[str, str | bool]:
    raw = "" if code is None else str(code)
    return {"raw": raw, "description": KNOWN_POSITIONS.get(raw, "位置码-未知"), "known": raw in KNOWN_POSITIONS}
