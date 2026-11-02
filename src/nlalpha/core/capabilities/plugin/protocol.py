"""Plugin base protocol.

Top-level interface definitions for all nlalpha plugins.
"""

from abc import ABC, abstractmethod
from typing import Protocol, Any, runtime_checkable


@runtime_checkable
class CapabilityPlugin(Protocol):
    """Capability provider plugin interface.

    Defines the contract for plugins in the indicator, statistics, performance,
    portfolio, and report capability domains.

    Third-party plugins may implement this Protocol directly without inheriting BaseCapabilityPlugin.
    """

    plugin_name: str  # Required
    plugin_version: str

    def is_available(self) -> bool:
        """Check whether the plugin is available."""
        ...

    def get_provider(self) -> Any:
        """Return the capability provider instance."""
        ...

    def get_manifest(self) -> dict:
        """Return the provider runtime manifest."""
        ...

    def get_helpers(self) -> list[Any]:
        """Return the list of capability declarations exposed to strategy code."""
        ...

    def get_prompt_path(self) -> str | None:
        """Return the path of required provider-authored guidance when declared."""
        ...


class BaseCapabilityPlugin(ABC, CapabilityPlugin):
    """Base capability plugin ABC.

    Internal plugins inherit explicitly for strong enforcement at
    class-definition and instantiation time.
    """

    __protocol_version__: str = "1.0.0"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        name = getattr(cls, "plugin_name", None)
        if not isinstance(name, str) or not name.strip():
            raise TypeError(f"{cls.__name__} must define a class attribute 'plugin_name'")

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def get_provider(self) -> Any: ...

    @abstractmethod
    def get_manifest(self) -> dict: ...

    @abstractmethod
    def get_helpers(self) -> list[Any]: ...

    @abstractmethod
    def get_prompt_path(self) -> str | None: ...
