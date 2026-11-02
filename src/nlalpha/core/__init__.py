"""Domain contracts and plugin framework for the quantitative strategy ecosystem.

Defines shared contracts between strategy family plugins, generation modules,
market data, capability registries, and security sandboxes.
"""

from importlib.metadata import version as _distribution_version

__version__ = _distribution_version("nlalpha-core")

__all__ = [
    "get_tracer",
    "start_span",
    "span",
    "is_enabled",
    "setup_logging",
    "Bar",
    "CancelOrder",
    "Order",
    "OrderEvent",
    "OrderSnapshot",
    "Position",
    "Trade",
    "BaseEventDrivenStrategy",
    "EventDrivenStrategy",
    "VectorizedStrategy",
    "StrategyFamilyPlugin",
    "BaseStrategyFamilyPlugin",
    "ErrorType",
    "ErrorStage",
    "ERROR_TYPES",
    "ERROR_STAGES",
    "RETRYABLE_ERROR_TYPES",
    "INVALID_REQUEST",
    "STRATEGY_ERROR",
    "DATA_ERROR",
    "EXECUTION_ERROR",
    "INFRASTRUCTURE_ERROR",
    "INTERNAL_ERROR",
    "NlAlphaError",
    "DataError",
    "StrategyRuntimeError",
    "AssumptionViolationError",
    "RESPONSE_BUDGET_BYTES",
    "ERROR_BUDGET_BYTES",
    "ERROR_MESSAGE_BUDGET_BYTES",
    "ERROR_SUGGESTION_BUDGET_BYTES",
    "ERROR_TRACEBACK_BUDGET_BYTES",
    "ERROR_DETAILS_BUDGET_BYTES",
    "build_error",
    "failure_response",
    "format_traceback_tail",
    "clip_utf8",
    "enforce_budget",
]

from nlalpha.core.telemetry import get_tracer, start_span, span, is_enabled, setup_logging
from nlalpha.core.contracts.market import Bar, CancelOrder, Order, OrderEvent, OrderSnapshot, Position, Trade
from nlalpha.core.strategy.runtime.base import BaseEventDrivenStrategy
from nlalpha.core.strategy.runtime.protocol import (
    EventDrivenStrategy,
    VectorizedStrategy,
)
from nlalpha.core.strategy.plugin.protocol import (
    StrategyFamilyPlugin,
    BaseStrategyFamilyPlugin,
)
from nlalpha.core.errors import (
    DATA_ERROR,
    ERROR_STAGES,
    ERROR_TYPES,
    EXECUTION_ERROR,
    INFRASTRUCTURE_ERROR,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    RETRYABLE_ERROR_TYPES,
    STRATEGY_ERROR,
    AssumptionViolationError,
    DataError,
    ErrorStage,
    ErrorType,
    NlAlphaError,
    StrategyRuntimeError,
)
from nlalpha.core.result_contract import (
    ERROR_BUDGET_BYTES,
    ERROR_DETAILS_BUDGET_BYTES,
    ERROR_MESSAGE_BUDGET_BYTES,
    ERROR_SUGGESTION_BUDGET_BYTES,
    ERROR_TRACEBACK_BUDGET_BYTES,
    RESPONSE_BUDGET_BYTES,
    build_error,
    clip_utf8,
    enforce_budget,
    failure_response,
    format_traceback_tail,
)
