"""Domain contracts and plugin framework for the quantitative strategy ecosystem.

Defines shared contracts between strategy family plugins, generation modules,
market data, capability registries, and security sandboxes.
"""

__version__ = "0.1.0"

from nlalpha.core.telemetry import get_tracer, start_span, span, is_enabled, setup_logging  # noqa: F401
from nlalpha.core.contracts.market import Bar, Order, Position, Trade  # noqa: F401
from nlalpha.core.strategy.runtime.base import BaseEventDrivenStrategy  # noqa: F401
from nlalpha.core.strategy.runtime.protocol import (
    EventDrivenStrategy,
    VectorizedStrategy,
)  # noqa: F401
from nlalpha.core.strategy.plugin.protocol import (
    StrategyFamilyPlugin,
    BaseStrategyFamilyPlugin,
)  # noqa: F401
