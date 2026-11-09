"""Supplement absent process facts without rewriting supplied candidate facts."""

from __future__ import annotations

import copy
from typing import Any


def apply_candidate_fact_defaults(
    candidate: dict[str, Any], policy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Return a copy and field provenance before normalization loses presence.

    Candidate keys use the internal model names, but only keys actually
    supplied by the caller should exist on entry. Explicit null/unknown,
    false and zero never receive an assumed replacement. Basic identity,
    material, availability and repair-age facts are not policy defaults.
    """
    result = copy.deepcopy(candidate)
    sources = {
        field: "unknown" if value is None or isinstance(value, str) and value.strip().lower() == "unknown" else "provided"
        for field, value in candidate.items()
    }
    if policy["source"] != "assumed":
        return result, sources
    for field, value in policy["candidate_fact_defaults"].items():
        if field not in candidate:
            result[field] = copy.deepcopy(value)
            sources[field] = "assumed"
    if (policy["assume_clean_history_when_absent"]
            and "last_use" not in candidate and "history_assumption" not in candidate):
        # This is an explicit simulation premise, not invented previous-use
        # data and not a relabeling of supplied material or repair counters.
        result["history_assumption"] = "clean"
        sources["history_assumption"] = "assumed"
    return result, sources
