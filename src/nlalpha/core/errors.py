"""Shared error taxonomy and the six canonical agent-facing error codes.

Each exception class declares its canonical code on the ``error_type`` class
variable; the result contract reads it through ``getattr`` and falls back to
``internal_error`` for unannotated or unknown exceptions. Developers attach
optional ``suggestion``, ``details``, ``retryable``, ``stage``, and
``traceback_tail`` hints.
"""

from typing import Literal

ErrorType = Literal[
    "invalid_request",
    "strategy_error",
    "data_error",
    "execution_error",
    "infrastructure_error",
    "internal_error",
]

INVALID_REQUEST: ErrorType = "invalid_request"
STRATEGY_ERROR: ErrorType = "strategy_error"
DATA_ERROR: ErrorType = "data_error"
EXECUTION_ERROR: ErrorType = "execution_error"
INFRASTRUCTURE_ERROR: ErrorType = "infrastructure_error"
INTERNAL_ERROR: ErrorType = "internal_error"

ERROR_TYPES: frozenset[str] = frozenset(
    {
        INVALID_REQUEST,
        STRATEGY_ERROR,
        DATA_ERROR,
        EXECUTION_ERROR,
        INFRASTRUCTURE_ERROR,
        INTERNAL_ERROR,
    }
)

ErrorStage = Literal["request", "validate", "load", "run", "finalize"]

REQUEST_STAGE: ErrorStage = "request"
VALIDATE_STAGE: ErrorStage = "validate"
LOAD_STAGE: ErrorStage = "load"
RUN_STAGE: ErrorStage = "run"
FINALIZE_STAGE: ErrorStage = "finalize"

ERROR_STAGES: frozenset[str] = frozenset(
    {REQUEST_STAGE, VALIDATE_STAGE, LOAD_STAGE, RUN_STAGE, FINALIZE_STAGE}
)

RETRYABLE_ERROR_TYPES: frozenset[str] = frozenset({INFRASTRUCTURE_ERROR})


class NlAlphaError(Exception):
    """Base class for all errors."""

    error_type: str = INTERNAL_ERROR

    def __init__(
        self,
        message: str = "",
        *,
        suggestion: str | None = None,
        details: dict | None = None,
        retryable: bool | None = None,
        stage: ErrorStage | None = None,
        traceback_tail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion
        self.details = details or {}
        self.retryable = retryable
        self.stage = stage
        self.traceback_tail = traceback_tail


class DataError(NlAlphaError):
    """Data access error."""

    error_type: str = DATA_ERROR


class InvalidRequestError(NlAlphaError):
    """Invalid agent-facing request parameters."""

    error_type: str = INVALID_REQUEST


class StrategyRuntimeError(NlAlphaError):
    """Strategy runtime error."""

    error_type: str = STRATEGY_ERROR


class AssumptionViolationError(NlAlphaError):
    """Assumption declaration incomplete or invalid."""

    error_type: str = STRATEGY_ERROR
