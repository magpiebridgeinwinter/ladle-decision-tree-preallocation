"""Rule-tree preallocation default and audit records."""

from .allocator import DecisionTreeAssignment, allocate
from .validation import validate_output

__all__ = ["DecisionTreeAssignment", "allocate", "validate_output"]
