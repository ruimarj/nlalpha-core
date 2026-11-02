"""Define market data, immutable order commands, execution events, and position snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from nlalpha.core.contracts.time import get_timezone, normalize_utc
from nlalpha.core.errors import DataError


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
    price: float | None
    volume: float


@dataclass(frozen=True, slots=True)
class Bar:
    """Store canonical UTC close time and the original market timestamp contract."""

    symbol: str
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float | None = None
    open_time: datetime | None = None
    session_date: date | None = None
    source_timezone: str | None = None
    source_utc_offset_seconds: int | None = None
    source_timestamp_semantics: str = "close"
    calendar_id: str | None = None

    def __post_init__(self) -> None:
        """Normalize exact timestamps while preserving explicit original source metadata."""
        def invalid(field: str, message: str) -> DataError:
            return DataError(message, details={"time_contract": True, "field": field})

        if not isinstance(self.source_timestamp_semantics, str) or self.source_timestamp_semantics not in {"open", "close", "trading_date"}:
            raise invalid("source_timestamp_semantics", "source_timestamp_semantics must be open, close, or trading_date")
        if self.session_date is not None and (not isinstance(self.session_date, date) or isinstance(self.session_date, datetime)):
            raise invalid("session_date", "session_date must be a date label")
        if self.source_timestamp_semantics == "trading_date" and self.session_date is None:
            raise invalid("session_date", "trading_date semantics require an explicit session_date")
        if self.calendar_id is not None and (not isinstance(self.calendar_id, str) or not self.calendar_id or self.calendar_id != self.calendar_id.strip()):
            raise invalid("calendar_id", "calendar_id must be a non-empty trimmed string")
        source_zone = self.source_timezone
        if source_zone is not None:
            get_timezone(source_zone)
        close = normalize_utc(self.datetime, source_timezone=source_zone)
        opened = None if self.open_time is None else normalize_utc(self.open_time, source_timezone=source_zone)
        if opened is not None and opened >= close:
            raise invalid("open_time", "open_time must precede the canonical UTC close timestamp")
        for original in (self.datetime, self.open_time):
            if original is not None:
                offset = original.utcoffset()
                if offset is not None and offset.microseconds:
                    raise invalid("source_utc_offset_seconds", "source UTC offset must have exact second precision")
        use_open = self.source_timestamp_semantics == "open" and self.open_time is not None
        original_source = self.open_time if use_open else self.datetime
        source_instant = opened if use_open else close
        original_offset = original_source.utcoffset()
        if source_zone is not None:
            original_offset = source_instant.astimezone(get_timezone(source_zone)).utcoffset()
        if original_offset.microseconds:
            raise invalid("source_utc_offset_seconds", "source UTC offset must have exact second precision")
        if source_zone is None and self.source_utc_offset_seconds is None:
            source_zone = getattr(original_source.tzinfo, "key", None)
            if source_zone is not None:
                get_timezone(source_zone)
            elif not (original_offset.days or original_offset.seconds or original_offset.microseconds):
                source_zone = "UTC"
        source_offset = self.source_utc_offset_seconds
        if source_offset is None:
            source_offset = original_offset.days * 86_400 + original_offset.seconds
        if isinstance(source_offset, bool) or not isinstance(source_offset, int) or not -86_400 < source_offset < 86_400:
            raise invalid("source_utc_offset_seconds", "source_utc_offset_seconds must be an integer within one day")
        object.__setattr__(self, "datetime", close)
        object.__setattr__(self, "open_time", opened)
        object.__setattr__(self, "source_timezone", source_zone)
        object.__setattr__(self, "source_utc_offset_seconds", source_offset)

    @property
    def vwap(self) -> float:
        """Approximate VWAP ((high+low+close)/3)."""
        return (self.high + self.low + self.close) / 3


@dataclass(frozen=True, slots=True)
class Order:
    """Submit an order with an optional reference price and explicit execution prices."""

    order_id: str
    symbol: str
    direction: str  # long / short
    offset: str  # open / close
    volume: float
    price: float | None = None
    order_type: str = "market"  # market / limit / stop / stop_limit
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "day"  # day / gtc / ioc / fok


_CLOSED_ORDER_STATUSES = frozenset({"denied", "rejected", "canceled", "expired", "filled"})


@dataclass(frozen=True, slots=True, kw_only=True)
class OrderSnapshot(Order):
    """Expose an immutable submitted order and its execution-engine state."""

    status: str
    filled_volume: float
    remaining_volume: float
    avg_price: float | None = None
    timestamp_ns: int | None = None
    reason: str | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the order has yet to reach a terminal state."""
        return self.status not in _CLOSED_ORDER_STATUSES

    @property
    def is_closed(self) -> bool:
        """Return whether the order has reached a terminal state."""
        return self.status in _CLOSED_ORDER_STATUSES


@dataclass(frozen=True, slots=True)
class CancelOrder:
    """Request cancellation of a strategy order by its identifier."""

    order_id: str


@dataclass(frozen=True, slots=True)
class OrderEvent:
    """Notify a strategy of an execution event and the corresponding order state."""

    kind: str
    order: OrderSnapshot
    timestamp_ns: int
    reason: str | None = None


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
    slippage_cost: float | None
    order_type: str = "market"
    limit_price_used: float | None = None
    timestamp_ns: int | None = None


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
