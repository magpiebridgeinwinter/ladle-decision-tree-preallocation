"""Expected, redacted domain failures at the ladle-only boundary."""


class PolicyError(ValueError):
    """The internal policy is unavailable or invalid."""


class SolverUnavailableError(RuntimeError):
    """A required solver or verified solution is unavailable."""


class SearchIncompleteError(RuntimeError):
    """The search budget ended without a verified fixed-binding solution."""


class BindingConflictError(ValueError):
    """Confirmed bindings cannot satisfy the fixed snapshot."""


class ReplayError(RuntimeError):
    """A proposed result fails independent domain replay."""
