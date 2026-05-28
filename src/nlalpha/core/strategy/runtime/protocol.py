"""Event-driven strategy contract.

The sole requirement the core system imposes on strategies.
Strategies only need to implement on_bar(bar) to receive data and generate orders via buy/sell;
the engine handles order matching, account updates, and progress reporting.

Design principles:
- Minimal contract: core only requires on_bar + collect_orders, no implementation details forced
- LLM-friendly: minimal interface, strategy code focuses only on trading logic
- Plugin autonomy: CTA/Portfolio/Spread each defines its own strategy base class in plugins,
  as long as this Protocol is satisfied, it can plug into the core backtest system

Note: This module only defines the Protocol, no implementation provided.
BaseEventDrivenStrategy is the shared event-driven strategy base class provided by core;
each family plugin extends via inheritance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, Any

from nlalpha.core.contracts.market import MarketData, OrderLike


@runtime_checkable
class EventDrivenStrategy(Protocol):
    """Event-driven strategy protocol.

    All strategies connecting to the backtest system must satisfy this protocol.
    The core backtest engine pushes data via on_bar() and collects trading instructions via collect_orders().
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

    def collect_orders(self) -> list[OrderLike]:
        """Collect and clear the current order queue.

        The engine calls this after each on_bar to consume strategy-generated orders,
        then clears the queue for the next bar.
        """
        ...


@runtime_checkable
class VectorizedStrategy(Protocol):
    """Vectorized backtest strategy protocol.

    Mutually exclusive with EventDrivenStrategy — a strategy is either event-driven or vectorized.

    Strategies receive a full DataFrame and return signal/weight series via pure functions.
    The engine handles batch matching and performance calculation.
    No subprocess isolation needed (no side effects); suitable for Portfolio / factor selection.
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
