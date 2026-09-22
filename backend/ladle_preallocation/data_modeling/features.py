"""Feature creation with explicit missing-value flags."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ladle_preallocation.data_modeling.assumptions import (
    DEFAULT_CRANE_SPEED_MPS,
    DEFAULT_SAFE_DISTANCE_COORDINATE,
    DEFAULT_X_LOWER_LIMIT,
    DEFAULT_X_UPPER_LIMIT,
)

TIME_FORMAT = "%Y-%m-%d-%H.%M.%S.%f"


def parse_time(value: Any) -> tuple[float | None, bool]:
    try:
        if value in (None, ""):
            return None, True
        return datetime.strptime(str(value), TIME_FORMAT).replace(tzinfo=timezone.utc).timestamp(), False
    except (TypeError, ValueError):
        return None, True


def relative_seconds(timestamp: float | None, t0: float | None) -> float | None:
    return None if timestamp is None or t0 is None else timestamp - t0


def compute_heat_features(heat: dict[str, Any], t0: float) -> dict[str, Any]:
    arrival, arrival_missing = parse_time(heat.get("ladle_arrival_at"))
    tap, tap_missing = parse_time(heat.get("tap_finish_at"))
    pour_finish, age_missing = parse_time(heat.get("ladle_pour_finish_at"))
    age = heat.get("ladle_age_seconds")
    inferred = age is None
    age = 0 if age is None or pour_finish is None else max(0, t0 - pour_finish)
    return {"heat_id": heat.get("heat_id"), "required_grade": heat.get("required_grade"), "priority": heat.get("priority", 0), "window_start": relative_seconds(arrival, t0), "window_end": relative_seconds(tap, t0), "ladle_age_seconds": age, "missing": {"arrival": arrival_missing, "tap": tap_missing, "ladle_age": inferred or age_missing}}


def crane_features(crane: dict[str, Any]) -> dict[str, Any]:
    def default(key: str, value: float) -> tuple[float, bool]:
        raw = crane.get(key)
        return (value, True) if raw in (None, "") else (float(raw), False)
    speed, speed_missing = default("speed_mps", DEFAULT_CRANE_SPEED_MPS)
    safe, safe_missing = default("safe_distance_m", DEFAULT_SAFE_DISTANCE_COORDINATE)
    length, length_missing = default("bay_length_m", DEFAULT_X_UPPER_LIMIT - DEFAULT_X_LOWER_LIMIT)
    lo, lo_missing = default("limit_0_m", DEFAULT_X_LOWER_LIMIT)
    hi, hi_missing = default("limit_1_m", length)
    return {**crane, "speed_mps": speed, "safe_distance_m": safe, "position_m": (lo + hi) / 2, "missing": {"speed": speed_missing, "safe_distance": safe_missing, "limits": lo_missing or hi_missing or length_missing}}
