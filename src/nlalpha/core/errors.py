"""Minimal error taxonomy.

Under the agentic architecture, the agent judges recovery strategy from exception
messages itself; no fine-grained human-predefined taxonomy is needed.
Keep base class + 3 subclasses actually used in production code.
"""


class NlAlphaError(Exception):
    """Base class for all errors."""

    failure_type: str = "internal_error"

    def __init__(self, message: str = "", *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DataError(NlAlphaError):
    """Data access error."""

    failure_type = "data_access_error"


class StrategyRuntimeError(NlAlphaError):
    """Strategy runtime error."""

    failure_type = "strategy_runtime_error"


class AssumptionViolationError(NlAlphaError):
    """Assumption declaration incomplete or invalid."""

    failure_type = "assumption_violation"
