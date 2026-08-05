"""Temporary, explicit operating assumptions for incomplete production data."""

# PLAN and CRANE X coordinates are processed in their supplied coordinate scale.
# The scale is treated as 1,000 coordinate units per metre until plant calibration arrives.
COORDINATE_UNITS_PER_METER = 1000.0
DEFAULT_CRANE_SPEED_MPS = 2.0
DEFAULT_CRANE_SPEED_COORDINATE_PER_SECOND = DEFAULT_CRANE_SPEED_MPS * COORDINATE_UNITS_PER_METER
DEFAULT_MAX_LOAD_TONNES = 300.0
DEFAULT_X_LOWER_LIMIT = 0.0
DEFAULT_X_UPPER_LIMIT = 48000.0
DEFAULT_SAFE_DISTANCE_COORDINATE = 10000.0
