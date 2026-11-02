"""Declare shared strategy lifecycle and order collection contracts.

Event runtimes dispatch on_bar or an optional user-defined on_bars callback.
Strategy families extend the shared base and declare their supported lifecycle entries.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, Any

from nlalpha.core.contracts.market import CancelOrder, MarketData, Order, OrderEvent, Trade


@runtime_checkable
class EventDrivenStrategy(Protocol):
    """Declare common event lifecycle and queued order collection.

    A runtime may dispatch a user-defined on_bars callback for grouped market data.
    """

    def on_bar(self, bar: MarketData) -> None:
        """Receive each bar and implement trading logic."""
        ...

    def on_init(self, config: dict | None = None) -> None:
        """Strategy initialization (called after data load, before backtest start)."""
        ...

    def on_start(self) -> None:
        """Called when backtest starts."""
        ...

    def on_stop(self) -> None:
        """Called when backtest ends."""
        ...

    def collect_commands(self) -> list[Order | CancelOrder]:
        """Collect and clear submission and cancellation instructions in FIFO order."""
        ...

    def on_order(self, event: OrderEvent) -> None:
        """Receive an execution order event after snapshots are updated."""
        ...

    def on_trade(self, trade: Trade) -> None:
        """Receive an actual fill after snapshots are updated."""
        ...


@runtime_checkable
class VectorizedStrategy(Protocol):
    """Declare batch signal generation.

    The consuming runtime defines input and output schemas.
    The execution host owns code isolation.
    """

    def generate_signals(self, df: Any) -> Any:
        """Generate trading signals from full dataset."""
        ...

    def on_init(self, config: dict | None = None) -> None:
        """Strategy initialization (called after data load, before backtest start)."""
        ...

    def on_stop(self) -> None:
        """Called when backtest ends."""
        ...
