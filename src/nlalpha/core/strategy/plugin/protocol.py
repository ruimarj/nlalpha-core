"""Strategy family protocol and base class.

Pure contracts with abstract base class — no external dependencies.
Plugins retain only two responsibilities: provide capability contract,
provide family confession.
"""

from abc import ABC, abstractmethod
from typing import Protocol, Any, runtime_checkable


@runtime_checkable
class StrategyFamilyPlugin(Protocol):
    """Strategy family plugin interface.

    A plugin represents a strategy world, e.g. CTA, stock selection, arbitrage, or options.
    The backbone interacts with plugins only through this interface,
    without understanding internal strategy semantics.

    Third-party plugins may implement this Protocol directly without inheriting BaseStrategyFamilyPlugin.
    """

    family: str  # Required
    plugin_name: str  # Required
    plugin_version: str = "0.1.0"

    def family_contract(self) -> Any: ...
    def confess(self) -> str: ...


class BaseStrategyFamilyPlugin(ABC, StrategyFamilyPlugin):
    """Abstract base class for strategy family plugins.

    Internal plugins should inherit from this class to get instantiation-time enforcement.
    """

    __protocol_version__: str = "0.1.0"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        family_val = getattr(cls, "family", None)
        if family_val is None:
            raise TypeError(f"{cls.__name__} must define a class attribute 'family'")
        if not isinstance(family_val, str):
            raise TypeError(f"{cls.__name__}.family must be a string, got {type(family_val).__name__}")
        if not family_val.strip():
            raise TypeError(f"{cls.__name__}.family cannot be empty or whitespace")
        name = getattr(cls, "plugin_name", None)
        if not isinstance(name, str) or not name.strip():
            raise TypeError(f"{cls.__name__} must define a class attribute 'plugin_name'")

    @abstractmethod
    def family_contract(self) -> Any: ...

    @abstractmethod
    def confess(self) -> str:
        """Strategy family confession: return supplementary notes in Markdown.

        Must be implemented. Return empty string if no special notes.
        May include: conventions, caveats, best practices.
        """
        ...
