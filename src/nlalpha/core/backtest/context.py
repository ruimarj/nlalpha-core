"""Shared event-driven and batch backtest execution contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TypeAlias

from nlalpha.core.backtest.input import BATCH_SIGNALS, EVENT_DRIVEN, BatchBacktestInput


@dataclass
class BacktestContext:
    """Strategy instance, market data, and configuration for one event-driven run."""

    job_id: str
    strategy_instance: Any
    data: list
    execution_config: dict = field(default_factory=dict)
    capital_config: dict = field(default_factory=dict)
    contract_config: dict = field(default_factory=dict)
    progress_callback: Callable[[float, str], None] | None = None

    @property
    def runtime_mode(self) -> str:
        """Return the runtime mode represented by this context."""
        return EVENT_DRIVEN

    @property
    def input_schema(self) -> None:
        """Return no batch input schema for event-driven data."""
        return None


@dataclass
class BatchBacktestContext:
    """Batch inputs and configuration for one backtest run."""

    job_id: str
    inputs: BatchBacktestInput
    execution_config: dict = field(default_factory=dict)
    capital_config: dict = field(default_factory=dict)
    contract_config: dict = field(default_factory=dict)
    progress_callback: Callable[[float, str], None] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.inputs, BatchBacktestInput):
            raise TypeError("inputs must be a BatchBacktestInput")

    @property
    def runtime_mode(self) -> str:
        """Return the runtime mode represented by this context."""
        return BATCH_SIGNALS

    @property
    def input_schema(self) -> str:
        """Return the input schema declared by the batch inputs."""
        return self.inputs.schema_id


EngineRunContext: TypeAlias = BacktestContext | BatchBacktestContext
