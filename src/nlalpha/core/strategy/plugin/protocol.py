"""Typed contracts and the required strategy-family plugin base class."""

from abc import ABC, abstractmethod
from typing import Protocol, Any, runtime_checkable

from nlalpha.core.capabilities.contract import FamilyContract


@runtime_checkable
class StrategyFamilyPlugin(Protocol):
    """Typed strategy-family interface enforced through BaseStrategyFamilyPlugin."""

    family: str  # Required
    plugin_name: str  # Required
    plugin_version: str

    def family_contract(self) -> FamilyContract: ...
    def confess(self) -> str: ...


class BaseStrategyFamilyPlugin(ABC, StrategyFamilyPlugin):
    """Required base class for installed strategy-family plugins."""

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
    def family_contract(self) -> FamilyContract: ...

    @abstractmethod
    def confess(self) -> str:
        """Return supplementary family conventions as Markdown."""
        ...
