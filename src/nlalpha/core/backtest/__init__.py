"""Shared backtest contracts, independent of engine implementations."""

from nlalpha.core.backtest.context import BacktestContext, BatchBacktestContext, EngineRunContext
from nlalpha.core.backtest.input import BATCH_SIGNALS, EVENT_DRIVEN, BatchBacktestInput
from nlalpha.core.backtest.protocol import BacktestEngineProvider, EngineManifest
from nlalpha.core.backtest.result import (
    BACKTEST_FAILED,
    BACKTEST_SUCCEEDED,
    BacktestResult,
    BacktestResultStatus,
)

__all__ = [
    "BATCH_SIGNALS",
    "BACKTEST_FAILED",
    "BACKTEST_SUCCEEDED",
    "BacktestResultStatus",
    "EVENT_DRIVEN",
    "BacktestContext",
    "BacktestEngineProvider",
    "BacktestResult",
    "BatchBacktestContext",
    "BatchBacktestInput",
    "EngineManifest",
    "EngineRunContext",
]
