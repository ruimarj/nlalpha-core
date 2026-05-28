"""Strategy runtime module. Exports base class and event-driven strategy protocol."""

from nlalpha.core.strategy.runtime.base import BaseEventDrivenStrategy
from nlalpha.core.strategy.runtime.protocol import EventDrivenStrategy

__all__ = ["BaseEventDrivenStrategy", "EventDrivenStrategy"]
