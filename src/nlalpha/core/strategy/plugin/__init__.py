"""Strategy-family contracts and the shared installed-family registry."""

from nlalpha.core.strategy.plugin.protocol import StrategyFamilyPlugin, BaseStrategyFamilyPlugin
from nlalpha.core.strategy.plugin.registry import StrategyFamilyRecord, StrategyFamilyRegistry

__all__ = [
    "StrategyFamilyPlugin",
    "BaseStrategyFamilyPlugin",
    "StrategyFamilyRecord",
    "StrategyFamilyRegistry",
]
