"""Provide shared event strategy lifecycle, account snapshots, and an order queue.

Runtimes dispatch on_bar or a user-defined on_bars callback and execute collected orders.
"""

from __future__ import annotations

from dataclasses import fields, replace
import math
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping

from nlalpha.core.contracts.market import CancelOrder, MarketData, Order, OrderEvent, OrderSnapshot, Position, Trade

from nlalpha.core.strategy.runtime.protocol import EventDrivenStrategy


class BaseEventDrivenStrategy(EventDrivenStrategy):
    """Provide runtime-configured symbols, account snapshots, and queued trading instructions.

    Runtimes call on_bar or an optional user-defined on_bars callback and collect orders.
    Indicator methods are supplied by injected capability providers.
    """

    _providers: list[Any] = []

    def __init__(self, symbols: list[str] | tuple[str, ...] | None = None):
        self._symbols: tuple[str, ...] = ()
        self._positions: dict[str, Position] = {}
        self._set_symbols(tuple(symbols or ()))
        # 账户快照（引擎每根 bar 后更新）
        self._initial_cash: float = 1_000_000.0
        self._available_cash: float = 1_000_000.0
        self._current_equity: float = 1_000_000.0
        # 引擎按顺序消费提交与撤单请求
        self._commands: list[Order | CancelOrder] = []
        self._order_snapshots: dict[str, OrderSnapshot] = {}
        self._pending_order_snapshots: dict[str, OrderSnapshot] = {}
        self._cancel_requested: set[str] = set()
        self._order_seq: int = 0

    def __getattr__(self, name: str) -> Any:
        """Return the named method from the first matching capability provider."""
        for provider in self._providers:
            if hasattr(provider, name):
                return getattr(provider, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    # 引擎注入的账户与持仓快照

    @property
    def symbols(self) -> tuple[str, ...]:
        """Return the symbols configured by the execution runtime."""
        return self._symbols

    @property
    def positions(self) -> Mapping[str, Position]:
        """Return detached position snapshots for every configured symbol."""
        return MappingProxyType({symbol: replace(position) for symbol, position in self._positions.items()})

    def position_for(self, symbol: str) -> Position:
        """Return a detached position snapshot for a configured symbol."""
        if symbol not in self._positions:
            raise ValueError(f"Unknown strategy symbol: {symbol!r}")
        return replace(self._positions[symbol])

    def _set_symbols(self, symbols: tuple[str, ...]) -> None:
        """Configure the runtime symbol set and initialize flat positions."""
        if any(not isinstance(symbol, str) or not symbol for symbol in symbols):
            raise ValueError("Strategy symbols must be non-empty strings")
        if len(set(symbols)) != len(symbols):
            raise ValueError("Strategy symbols must be unique")
        self._symbols = tuple(symbols)
        self._positions = {symbol: Position(symbol=symbol) for symbol in self._symbols}

    def _update_positions_snapshot(self, positions: dict[str, Position]) -> None:
        """Replace position state with snapshots supplied by the execution engine."""
        unknown = positions.keys() - self._positions.keys()
        if unknown:
            raise ValueError(f"Unknown strategy symbols in position snapshot: {sorted(unknown)!r}")
        for symbol, position in positions.items():
            if not isinstance(position, Position) or position.symbol != symbol:
                raise ValueError(f"Position snapshot must match its symbol key: {symbol!r}")
        self._positions = {
            symbol: replace(positions[symbol]) if symbol in positions else Position(symbol=symbol)
            for symbol in self._symbols
        }

    @property
    def initial_cash(self) -> float:
        return self._initial_cash

    @property
    def available_cash(self) -> float:
        return self._available_cash

    @property
    def current_equity(self) -> float:
        return self._current_equity

    def _set_initial_cash(self, value: float) -> None:
        self._initial_cash = value
        self._available_cash = value
        self._current_equity = value

    def _update_account_snapshot(self, cash: float, equity: float) -> None:
        self._available_cash = cash
        self._current_equity = equity

    # 核心接口：数据处理（策略必须重写）

    def on_bar(self, bar: MarketData) -> None:
        """Receive each bar. Subclasses override this to implement strategy logic."""
        raise NotImplementedError

    # 提交请求与实际订单状态

    @property
    def orders(self) -> Mapping[str, OrderSnapshot]:
        """Return an immutable view of detached order snapshots."""
        return MappingProxyType(dict(self._order_snapshots))

    @property
    def pending_orders(self) -> Mapping[str, OrderSnapshot]:
        """Return active order snapshots, including locally queued submissions."""
        return MappingProxyType(dict(self._pending_order_snapshots))

    def order_for(self, order_id: str) -> OrderSnapshot:
        """Return one known order's immutable execution snapshot."""
        if not isinstance(order_id, str):
            raise ValueError(f"Unknown strategy order: {order_id!r}")
        try:
            return self._order_snapshots[order_id]
        except KeyError:
            raise ValueError(f"Unknown strategy order: {order_id!r}") from None

    @staticmethod
    def _positive_number(value: float, field: str) -> float:
        """Normalize a finite positive real number for a submitted order."""
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{field} must be a finite positive number")
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise ValueError(f"{field} must be a finite positive number") from None
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"{field} must be a finite positive number")
        return number

    def submit_order(
        self, *, symbol: str, direction: str, offset: str, volume: float,
        order_type: str = "market", price: float | None = None,
        limit_price: float | None = None, stop_price: float | None = None,
        time_in_force: str = "day",
    ) -> str:
        """Validate and queue an immutable submission, returning its strategy order ID."""
        if not isinstance(symbol, str):
            raise ValueError(f"Specify a configured strategy symbol: {symbol!r}")
        if symbol == "" and len(self.symbols) == 1:
            symbol = self.symbols[0]
        if symbol not in self.symbols:
            raise ValueError(f"Specify a configured strategy symbol: {symbol!r}")
        if not isinstance(direction, str) or direction not in {"long", "short"}:
            raise ValueError("direction must be 'long' or 'short'")
        if not isinstance(offset, str) or offset not in {"open", "close"}:
            raise ValueError("offset must be 'open' or 'close'")
        if not isinstance(order_type, str) or order_type not in {"market", "limit", "stop", "stop_limit"}:
            raise ValueError("order_type must be 'market', 'limit', 'stop', or 'stop_limit'")
        if not isinstance(time_in_force, str) or time_in_force not in {"day", "gtc", "ioc", "fok"}:
            raise ValueError("time_in_force must be 'day', 'gtc', 'ioc', or 'fok'")
        volume = self._positive_number(volume, "volume")
        if price is not None:
            price = self._positive_number(price, "price")
        requires_limit = order_type in {"limit", "stop_limit"}
        requires_stop = order_type in {"stop", "stop_limit"}
        if requires_limit != (limit_price is not None):
            raise ValueError(f"{order_type!r} requires limit_price" if requires_limit else f"{order_type!r} does not accept limit_price")
        if requires_stop != (stop_price is not None):
            raise ValueError(f"{order_type!r} requires stop_price" if requires_stop else f"{order_type!r} does not accept stop_price")
        if limit_price is not None:
            limit_price = self._positive_number(limit_price, "limit_price")
        if stop_price is not None:
            stop_price = self._positive_number(stop_price, "stop_price")
        self._order_seq += 1
        order = Order(
            order_id=f"o_{self._order_seq}", symbol=symbol, direction=direction, offset=offset,
            volume=volume, price=price, order_type=order_type, limit_price=limit_price,
            stop_price=stop_price, time_in_force=time_in_force,
        )
        self._order_snapshots[order.order_id] = OrderSnapshot(
            **{field.name: getattr(order, field.name) for field in fields(Order)},
            status="queued", filled_volume=0.0, remaining_volume=volume,
        )
        self._pending_order_snapshots[order.order_id] = self._order_snapshots[order.order_id]
        self._commands.append(order)
        return order.order_id

    def cancel_order(self, order_id: str) -> None:
        """Queue a cancellation intent for a known active order."""
        order = self.order_for(order_id)
        if order.is_closed:
            raise ValueError(f"Cannot cancel closed order: {order_id!r}")
        if order_id in self._cancel_requested:
            raise ValueError(f"Cancellation already requested for order: {order_id!r}")
        self._cancel_requested.add(order_id)
        self._commands.append(CancelOrder(order_id=order_id))

    def _clear_cancel_request(self, order_id: str) -> None:
        """Release a known order's cancellation intent after an execution response."""
        self.order_for(order_id)
        self._cancel_requested.discard(order_id)

    def _update_order_snapshot(self, snapshot: OrderSnapshot) -> None:
        """Replace a known strategy order with an execution-engine snapshot."""
        if not isinstance(snapshot, OrderSnapshot):
            raise TypeError("Order updates must be core OrderSnapshot instances")
        previous = self.order_for(snapshot.order_id)
        if any(getattr(snapshot, field.name) != getattr(previous, field.name) for field in fields(Order)):
            raise ValueError(f"Order snapshot changed submission fields: {snapshot.order_id!r}")
        self._order_snapshots[snapshot.order_id] = snapshot
        if snapshot.is_closed:
            self._pending_order_snapshots.pop(snapshot.order_id, None)
            self._cancel_requested.discard(snapshot.order_id)
        else:
            self._pending_order_snapshots[snapshot.order_id] = snapshot

    def collect_commands(self) -> list[Order | CancelOrder]:
        """Collect and clear submission and cancellation requests in FIFO order."""
        commands = self._commands[:]
        self._commands.clear()
        return commands

    def buy(self, price: float | None, volume: float, symbol: str = "", *, order_type: str = "market",
            limit_price: float | None = None, stop_price: float | None = None, time_in_force: str = "day") -> str:
        """Queue a long-opening order and return its strategy order ID."""
        return self.submit_order(symbol=symbol, direction="long", offset="open", price=price, volume=volume,
                                 order_type=order_type, limit_price=limit_price, stop_price=stop_price, time_in_force=time_in_force)

    def sell(self, price: float | None, volume: float, symbol: str = "", *, order_type: str = "market",
             limit_price: float | None = None, stop_price: float | None = None, time_in_force: str = "day") -> str:
        """Queue a long-closing order and return its strategy order ID."""
        return self.submit_order(symbol=symbol, direction="short", offset="close", price=price, volume=volume,
                                 order_type=order_type, limit_price=limit_price, stop_price=stop_price, time_in_force=time_in_force)

    def short(self, price: float | None, volume: float, symbol: str = "", *, order_type: str = "market",
              limit_price: float | None = None, stop_price: float | None = None, time_in_force: str = "day") -> str:
        """Queue a short-opening order and return its strategy order ID."""
        return self.submit_order(symbol=symbol, direction="short", offset="open", price=price, volume=volume,
                                 order_type=order_type, limit_price=limit_price, stop_price=stop_price, time_in_force=time_in_force)

    def cover(self, price: float | None, volume: float, symbol: str = "", *, order_type: str = "market",
              limit_price: float | None = None, stop_price: float | None = None, time_in_force: str = "day") -> str:
        """Queue a short-closing order and return its strategy order ID."""
        return self.submit_order(symbol=symbol, direction="long", offset="close", price=price, volume=volume,
                                 order_type=order_type, limit_price=limit_price, stop_price=stop_price, time_in_force=time_in_force)

    # 生命周期（可选重写）

    def on_init(self, config: dict | None = None) -> None:
        """Strategy initialization (called after data load, before backtest start)."""
        pass

    def on_start(self) -> None:
        """Called when backtest starts."""
        pass

    def on_stop(self) -> None:
        """Called when backtest ends."""
        pass

    def on_order(self, event: OrderEvent) -> None:
        """Receive an execution order event after the runtime updates its snapshots."""
        pass

    def on_trade(self, trade: Trade) -> None:
        """Receive an actual fill after the runtime updates account and position snapshots."""
        pass
