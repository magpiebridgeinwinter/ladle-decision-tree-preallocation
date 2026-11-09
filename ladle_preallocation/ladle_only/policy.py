"""Load the program-owned steel dictionary and validate simulation policy."""

from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any

from .errors import PolicyError

POLICY_PATH = Path(__file__).with_name("assumed_policy.json")
COUNTER_FIELDS = (
    "small_repair_age_heats", "major_repair_age_heats", "usage_count",
    "nozzle_used_heats", "slide_used_heats", "frame_used_heats",
)
CANDIDATE_DEFAULT_FIELDS = {
    "condition_code", "usage_count", "nozzle_used_heats", "slide_used_heats",
    "frame_used_heats", "argon_ready",
}


def _integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def _string_list(value: Any, *, empty: bool = False) -> bool:
    return isinstance(value, list) and (empty or bool(value)) and all(
        isinstance(v, str) and bool(v.strip()) for v in value
    )


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Validate independently of client JSON; return an unshared copy."""
    try:
        if not isinstance(policy, dict) or not isinstance(policy.get("version"), str) or not policy["version"]:
            raise ValueError
        if policy.get("source") not in {"assumed", "confirmed"}:
            raise ValueError
        candidate_defaults = policy["candidate_fact_defaults"]
        if not isinstance(candidate_defaults, dict) or set(candidate_defaults) != CANDIDATE_DEFAULT_FIELDS:
            raise ValueError
        if not isinstance(candidate_defaults["condition_code"], str) or not re.fullmatch(r"2[0-9][A-F]", candidate_defaults["condition_code"]):
            raise ValueError
        if any(not _integer(candidate_defaults[field]) for field in CANDIDATE_DEFAULT_FIELDS - {"condition_code", "argon_ready"}):
            raise ValueError
        if type(candidate_defaults["argon_ready"]) is not bool or type(policy["assume_clean_history_when_absent"]) is not bool:
            raise ValueError
        materials = policy["lining_materials"]
        if not isinstance(materials, dict) or not materials:
            raise ValueError
        for key, material in materials.items():
            if not isinstance(key, str) or not key or not isinstance(material, dict):
                raise ValueError
            if not isinstance(material.get("name"), str) or not material["name"] or material.get("source") not in {"assumed", "confirmed"}:
                raise ValueError
        estimates = policy["casting_minutes"]
        if not isinstance(estimates, dict) or set(estimates) != set(map(str, range(5))):
            raise ValueError
        if not all(_integer(v, 1) for v in estimates.values()):
            raise ValueError
        profiles = policy["profiles"]
        if not isinstance(profiles, dict) or not profiles:
            raise ValueError
        for key, profile in profiles.items():
            if not isinstance(key, str) or not key or not isinstance(profile, dict):
                raise ValueError
            if not isinstance(profile.get("name"), str) or not profile["name"]:
                raise ValueError
            if not _string_list(profile["allowed_materials"]):
                raise ValueError
            bands = profile["allowed_condition_bands"]
            if not isinstance(bands, list) or not bands or any(not _integer(v) or v > 9 for v in bands):
                raise ValueError
            suffixes = profile["allowed_cold_steel_suffixes"]
            if not _string_list(suffixes) or not set(suffixes) <= set("ABCDEF"):
                raise ValueError
            if type(profile["allow_new_ladle"]) is not bool:
                raise ValueError
            previous = profile["allowed_previous_grades"]
            if previous is not None and not _string_list(previous, empty=True):
                raise ValueError
            if "T" in profile["allowed_materials"] and "T" not in materials:
                raise ValueError
        limits = policy["limits"]
        if not isinstance(limits, dict) or set(limits) - set(COUNTER_FIELDS) or "usage_count" in limits:
            raise ValueError
        if not limits or not all(_integer(v, 1) for v in limits.values()):
            raise ValueError
        if not _string_list(policy["argon_operations"], empty=True):
            raise ValueError
        if not _string_list(policy["first_cast_allowed_condition_codes"]):
            raise ValueError
        if any(len(code) != 3 or code[0] != "2" or not code[1].isdigit() or code[2] not in "ABCDEF"
               for code in policy["first_cast_allowed_condition_codes"]):
            raise ValueError
        boundaries = policy["thermal_boundaries_seconds"]
        if not isinstance(boundaries, list) or len(boundaries) != 6 or any(not _integer(v, 1) for v in boundaries):
            raise ValueError
        if boundaries != sorted(set(boundaries)) or policy["thermal_stop_after_seconds"] != boundaries[-1]:
            raise ValueError
        preferences = policy["material_preference"]
        # Keep configurable ranking weights well within CP-SAT's integer
        # arithmetic, including sums across a full planning window.
        if not isinstance(preferences, dict) or not all(
            isinstance(k, str) and _integer(v) and v <= 1_000_000 for k, v in preferences.items()
        ):
            raise ValueError
        defaults = policy["solver_defaults"]
        if not _integer(defaults["time_limit_seconds"], 1) or defaults["time_limit_seconds"] > 60:
            raise ValueError
        deterministic = defaults["max_deterministic_time"]
        if isinstance(deterministic, bool) or not isinstance(deterministic, (int, float)) or not math.isfinite(deterministic) or not .001 <= deterministic <= 60:
            raise ValueError
        if not _string_list(policy["assumptions"], empty=True):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PolicyError("内部配包规则配置无效") from exc
    return copy.deepcopy(policy)


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Read the current local configuration without importing the solver."""
    try:
        with (path or POLICY_PATH).open(encoding="utf-8") as stream:
            policy = json.load(stream)
    except (OSError, ValueError) as exc:
        raise PolicyError("内部配包规则配置不可用") from exc
    return validate_policy(policy)
