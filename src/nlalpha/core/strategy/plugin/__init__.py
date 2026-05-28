"""Strategy plugin framework protocol definitions.

Plugin discovery moved to nlalpha-strategy, managed by the strategy domain.
"""

from nlalpha.core.strategy.plugin.protocol import StrategyFamilyPlugin, BaseStrategyFamilyPlugin

__all__ = [
    "StrategyFamilyPlugin",
    "BaseStrategyFamilyPlugin",
]
