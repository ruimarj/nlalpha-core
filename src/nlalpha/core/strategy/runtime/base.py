"""Engine-agnostic strategy base class.

All strategy code must inherit from this class, implement trading logic via on_bar(bar),
and generate orders through buy()/sell()/short()/cover(). The engine handles execution.
"""

from __future__ import annotations

from typing import Any

from nlalpha.core.contracts.market import MarketData, Order

from nlalpha.core.strategy.runtime.protocol import EventDrivenStrategy


class BaseEventDrivenStrategy(EventDrivenStrategy):
    """Engine-agnostic strategy base class.

    Strategies receive data via on_bar and generate orders via buy/sell;
    the engine is responsible for execution.

    Indicators and statistical methods are no longer hard-coded in the base class;
    they are dynamically proxied to registered providers via __getattr__.
    Providers are injected into _providers by the backtest engine before strategy execution.
    """

    _providers: list[Any] = []

    def __init__(self, symbols: list[str] | None = None):
        self.symbols = symbols or []
        # 账户快照（引擎每根 bar 后更新）
        self._initial_cash: float = 1_000_000.0
        self._available_cash: float = 1_000_000.0
        self._current_equity: float = 1_000_000.0
        # 订单队列（策略通过 buy/sell 生成，引擎通过 collect_orders 消费）
        self._orders: list = []
        self._order_seq: int = 0

    def __getattr__(self, name: str) -> Any:
        """Dynamic proxy to registered providers.

        Traverse _providers to find the first object that implements `name`,
        and return that method. If not found, raise AttributeError.
        """
        for provider in self._providers:
            if hasattr(provider, name):
                return getattr(provider, name)
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

    # 兼容属性

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

    # 交易动作（生成 Order 对象）

    def buy(self, price: float, volume: float, symbol: str = "") -> None:
        """Open long (buy to open)."""
        self._order_seq += 1
        self._orders.append(
            Order(
                order_id=f"o_{self._order_seq}",
                symbol=symbol,
                direction="long",
                offset="open",
                price=price,
                volume=volume,
            )
        )

    def sell(self, price: float, volume: float, symbol: str = "") -> None:
        """Close long (sell to close)."""
        self._order_seq += 1
        self._orders.append(
            Order(
                order_id=f"o_{self._order_seq}",
                symbol=symbol,
                direction="short",
                offset="close",
                price=price,
                volume=volume,
            )
        )

    def short(self, price: float, volume: float, symbol: str = "") -> None:
        """Open short (sell to open)."""
        self._order_seq += 1
        self._orders.append(
            Order(
                order_id=f"o_{self._order_seq}",
                symbol=symbol,
                direction="short",
                offset="open",
                price=price,
                volume=volume,
            )
        )

    def cover(self, price: float, volume: float, symbol: str = "") -> None:
        """Close short (buy to close)."""
        self._order_seq += 1
        self._orders.append(
            Order(
                order_id=f"o_{self._order_seq}",
                symbol=symbol,
                direction="long",
                offset="close",
                price=price,
                volume=volume,
            )
        )

    def collect_orders(self) -> list:
        """Collect and clear the current strategy order queue."""
        orders = self._orders[:]
        self._orders.clear()
        return orders

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
