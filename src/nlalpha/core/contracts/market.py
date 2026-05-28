"""Core data exchange format between strategy layer and backtest engines.

All engines connecting to the nlalpha backtest system must recognize and process these data structures.

Design principles:
- Pure data: no behavioral logic, only data fields and read-only properties
- Minimal fields: only information necessary for strategy generation and engine matching
- Engine-agnostic: not biased toward any specific backtest engine implementation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class MarketData(Protocol):
    """Market data interface.

    Strategy layer receives data through this interface without depending on concrete implementations.

    Any object implementing the following properties can be passed to on_bar:
    - contracts.market.Bar (current implementation)
    - Real-time market tick objects
    - NumPy structured array views
    """

    @property
    def symbol(self) -> str:
        """Trading symbol."""
        ...

    @property
    def datetime(self) -> datetime:
        """Data timestamp."""
        ...

    @property
    def open(self) -> float:
        """Opening price."""
        ...

    @property
    def high(self) -> float:
        """Highest price."""
        ...

    @property
    def low(self) -> float:
        """Lowest price."""
        ...

    @property
    def close(self) -> float:
        """Closing price."""
        ...

    @property
    def volume(self) -> float:
        """Trading volume."""
        ...


class OrderLike(Protocol):
    """Order interface.

    Strategy layer generates orders through this interface,
    and engines consume orders through this interface.

    Any object implementing the following properties is recognized as a valid order.
    """

    order_id: str
    symbol: str
    direction: str
    offset: str
    price: float
    volume: float


@dataclass(frozen=True, slots=True)
class Bar:
    """Bar (candlestick) data."""

    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None

    @property
    def vwap(self) -> float:
        """Approximate VWAP ((high+low+close)/3)."""
        return (self.high + self.low + self.close) / 3


@dataclass(slots=True)
class Order:
    """Order."""

    order_id: str
    symbol: str
    direction: str  # long / short
    offset: str  # open / close
    price: float
    volume: float
    order_type: str = "market"  # market / limit / stop / stop_limit
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"  # day / gtc / ioc / fok
    traded: float = 0.0
    status: str = "pending"
    created_at: datetime | None = None
    frozen_cash: float = 0.0

    @property
    def is_active(self) -> bool:
        """Whether the order is still active (matchable)."""
        return self.status in ("pending", "partial")


@dataclass(frozen=True, slots=True)
class Trade:
    """Trade record."""

    trade_id: str
    order_id: str
    symbol: str
    datetime: datetime
    direction: str
    offset: str
    price: float
    volume: float
    commission: float
    slippage_cost: float
    order_type: str = "market"
    limit_price_used: float | None = None


@dataclass(slots=True)
class Position:
    """Position.

    Supports long/short-separated model with net position shortcut.
    """

    symbol: str
    long_volume: float = 0.0
    short_volume: float = 0.0
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0
    long_frozen: float = 0.0
    short_frozen: float = 0.0
    margin_used: float = 0.0

    @property
    def net_volume(self) -> float:
        """Net position volume (long - short)."""
        return self.long_volume - self.short_volume

    @property
    def size(self) -> float:
        """Alias for net position volume.

        Positive = long, negative = short, zero = flat.
        """
        return self.net_volume

    @property
    def avg_price(self) -> float:
        """Weighted average entry price (based on net direction)."""
        if self.net_volume > 0:
            return self.long_avg_price
        elif self.net_volume < 0:
            return self.short_avg_price
        return 0.0

    @property
    def tradable_long(self) -> float:
        """Tradable long quantity (excluding frozen)."""
        return max(0, self.long_volume - self.long_frozen)

    @property
    def tradable_short(self) -> float:
        """Tradable short quantity (excluding frozen)."""
        return max(0, self.short_volume - self.short_frozen)
