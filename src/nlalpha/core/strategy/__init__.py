"""Strategy specification and runtime base classes.

Plugin discovery moved to nlalpha-strategy, managed by the strategy domain.
"""

from nlalpha.core.strategy.runtime import BaseEventDrivenStrategy, EventDrivenStrategy
from nlalpha.core.strategy.spec import StrategySpecEnvelope
from nlalpha.core.strategy.plugin import (
    StrategyFamilyPlugin,
    BaseStrategyFamilyPlugin,
)

__all__ = [
    "BaseEventDrivenStrategy",
    "EventDrivenStrategy",
    "StrategySpecEnvelope",
    "StrategyFamilyPlugin",
    "BaseStrategyFamilyPlugin",
]
