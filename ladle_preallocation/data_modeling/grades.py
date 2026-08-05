"""Conservative, auditable temporary grade rules pending process confirmation."""
from __future__ import annotations

import logging
import re
from typing import Any

LOG = logging.getLogger(__name__)
NUMERIC_GRADES = {0: "不限", 1: "弱", 4: "中等", 5: "最高"}


def parse_grade(value: Any) -> tuple[str, int | str | None]:
    if value is None or value == "":
        return "missing", None
    text = str(value).strip().upper()
    if text in {"0", "1", "4", "5"}:
        return "numeric", int(text)
    match = re.search(r"(\d{1,2})A", text)
    return ("alpha", int(match.group(1))) if match else ("unknown", text)


def grade_matches(required: Any, current: Any) -> bool:
    rk, rv = parse_grade(required)
    ck, cv = parse_grade(current)
    if rk == "numeric" and rv == 0:
        return True
    # Requirement level 5 is the explicit high-grade exception: 29A is the
    # temporary top of the letter-grade system until the process map arrives.
    if rk == "numeric" and rv == 5 and ck == "alpha":
        return bool(cv >= 29)
    if rk == ck == "numeric":
        return bool(cv >= rv)
    if rk == ck == "alpha":
        return bool(cv >= rv)
    LOG.debug("数值等级与字母等级不可比: required=%r current=%r", required, current)
    return False
