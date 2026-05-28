"""Capability registry: unified entry for capability declarations and provider discovery."""

from dataclasses import dataclass, field
import logging
import os
from typing import Any, Literal

from nlalpha.core.capabilities.plugin.protocol import CapabilityPlugin

logger = logging.getLogger("nlalpha.capabilities.registry")


@dataclass(frozen=True)
class CapabilityEntry:
    """Single capability declaration entry.

    category: runtime semantics — function (callable) or property (read-only attribute)
    domain: technical domain — trend/momentum/volatility/statistics/trade/account/lifecycle/ml/nlp/...
    """

    name: str
    category: Literal["function", "property"]
    signature: str
    description: str
    source_plugin: str  # helper 来源插件标识
    availability: str = ""  # 语义待重新定义
    read_only: bool = True  # True = 只读属性；False = 可调用函数或允许写入的属性
    domain: str = ""  # 技术领域标签，用于 prompt 分组展示
    version: str = ""  # API 版本
    deprecated: bool = False  # 是否废弃
    examples: list[str] = field(default_factory=list)  # 使用示例
    extra: dict[str, Any] = field(default_factory=dict)  # 开放扩展字段


@dataclass
class FamilyCapabilitySet:
    """Helper set exposed by a strategy family."""

    family: str
    helpers: list[CapabilityEntry] = field(default_factory=list)

    def names(self) -> set[str]:
        return {h.name for h in self.helpers}

    def readonly_props(self) -> set[str]:
        return {h.name for h in self.helpers if h.category == "property" and h.read_only}

    def functions(self) -> list[CapabilityEntry]:
        """Return all callable functions."""
        return [h for h in self.helpers if h.category == "function"]

    def properties(self) -> list[CapabilityEntry]:
        """Return all properties."""
        return [h for h in self.helpers if h.category == "property"]

    def helpers_by_domain(self, domain: str = "") -> list[CapabilityEntry]:
        """Filter helpers by domain. Returns all helpers if domain is empty."""
        if not domain:
            return self.helpers
        return [h for h in self.helpers if h.domain == domain]


class CapabilityRegistry:
    """Helper capability registry.

    Per-family registration; supports whitelist, prompt, and template generation.
    """

    _FAMILY_HELPERS: dict[str, FamilyCapabilitySet] = {}

    @classmethod
    def register_family(cls, family: str, helpers: list[CapabilityEntry]) -> None:
        """Register a family's helper list. Overwrites on repeat."""
        cls._FAMILY_HELPERS[family] = FamilyCapabilitySet(family=family, helpers=list(helpers))

    @classmethod
    def get_family(cls, family: str) -> FamilyCapabilitySet | None:
        return cls._FAMILY_HELPERS.get(family)

    @classmethod
    def family_names(cls, family: str) -> set[str]:
        """All helper names for a family (validator whitelist). Empty if not registered."""
        fcs = cls._FAMILY_HELPERS.get(family)
        return fcs.names() if fcs else set()

    @classmethod
    def family_readonly_props(cls, family: str) -> set[str]:
        """Read-only property names for a family (write-guard validation)."""
        fcs = cls._FAMILY_HELPERS.get(family)
        return fcs.readonly_props() if fcs else set()

    @classmethod
    def family_functions(cls, family: str) -> list[CapabilityEntry]:
        """All callable functions for a family."""
        fcs = cls._FAMILY_HELPERS.get(family)
        return fcs.functions() if fcs else []

    @classmethod
    def family_properties(cls, family: str) -> list[CapabilityEntry]:
        """All properties for a family."""
        fcs = cls._FAMILY_HELPERS.get(family)
        return fcs.properties() if fcs else []

    @classmethod
    def family_helpers_by_domain(cls, family: str, domain: str = "") -> list[CapabilityEntry]:
        """Filter a family's helpers by domain. Returns all helpers if domain is empty."""
        fcs = cls._FAMILY_HELPERS.get(family)
        return fcs.helpers_by_domain(domain) if fcs else []

    @classmethod
    def list_global_catalog(cls) -> list[CapabilityEntry]:
        """Return the global capability catalog (aggregated from Provider declarations)."""
        return CapabilityPluginRegistry.get_discovered_helpers()

    @classmethod
    def list_by_domain(cls, domain: str) -> list[CapabilityEntry]:
        """Filter global capability catalog by domain (on-demand; only loads matching plugins)."""
        return CapabilityPluginRegistry.get_helpers_by_domain(domain)

    @classmethod
    def list_all(cls) -> list[CapabilityEntry]:
        """Return global capability catalog (alias for list_global_catalog)."""
        return cls.list_global_catalog()

    @classmethod
    def names(cls) -> set[str]:
        return {e.name for e in cls.list_global_catalog()}

    @classmethod
    def get(cls, name: str) -> CapabilityEntry | None:
        for entry in cls.list_global_catalog():
            if entry.name == name:
                return entry
        return None


class CapabilityPluginRegistry:
    """Capability provider registry.

    Discovers plugins via entry_points; lazy-loads on first access.

    Responsibilities:
    - Scan nlalpha.capabilities entry_points to discover all available plugins.
    - Aggregate get_helpers() declarations from each plugin to build the global helper catalog.
    - Collect get_manifest() from each plugin for audit trails.
    """

    _PLUGINS: list[Any] = []
    _PLUGIN_DOMAINS: dict[str, list[Any]] = {}  # domain → plugins 反向索引
    _DISCOVERY_DONE: bool = False

    @classmethod
    def _discover(cls) -> None:
        if cls._DISCOVERY_DONE:
            return

        try:
            from importlib.metadata import entry_points
            try:
                eps = entry_points().select(group="nlalpha.capabilities")
            except AttributeError:
                all_eps = entry_points()
                if hasattr(all_eps, "get"):
                    eps = all_eps.get("nlalpha.capabilities", ())  # type: ignore[attr-defined]
                else:
                    eps = [ep for ep in all_eps if getattr(ep, "group", None) == "nlalpha.capabilities"]
        except Exception:
            eps = []

        for ep in eps:
            try:
                plugin_cls = ep.load()
                plugin = plugin_cls()
                if not isinstance(plugin, CapabilityPlugin):
                    missing = [
                        m for m in ("is_available", "get_provider", "get_manifest", "get_helpers")
                        if not callable(getattr(plugin, m, None))
                    ]
                    logger.warning(
                        "Capability plugin '%s' skipped: does not satisfy CapabilityPlugin. Missing: %s",
                        ep.name,
                        missing,
                    )
                    continue
                if not plugin.is_available():
                    continue
                cls._PLUGINS.append(plugin)

                # 读取 manifest 建立 domain 反向索引（插件自声明，core 不维护语义）
                try:
                    manifest = plugin.get_manifest()
                    if isinstance(manifest, dict):
                        domains = manifest.get("domains", [])
                    elif hasattr(manifest, "get"):
                        domains = manifest.get("domains", [])
                    else:
                        domains = []
                    for domain in domains:
                        if isinstance(domain, str) and domain.strip():
                            cls._PLUGIN_DOMAINS.setdefault(domain.strip(), []).append(plugin)
                except Exception:
                    pass
            except Exception:
                continue

        # 开发时请使用 pip install -e 安装 plugin
        cls._DISCOVERY_DONE = True

    @classmethod
    def get_discovered_helpers(cls) -> list[CapabilityEntry]:
        """Aggregate helper declarations from all discovered Providers (loaded on demand)."""
        cls._discover()
        helpers: list[CapabilityEntry] = []
        for plugin in cls._PLUGINS:
            try:
                plugin_helpers = plugin.get_helpers()
                if plugin_helpers:
                    helpers.extend(plugin_helpers)
            except Exception:
                continue
        return helpers

    @classmethod
    def get_helpers_by_domain(cls, domain: str) -> list[CapabilityEntry]:
        """Return helper declarations filtered by domain (on-demand; only loads matching plugins).

        Args:
            domain: technical domain tag, e.g. "statistics", "performance", "trade".
                    Tag values are self-declared by plugin manifest; core only does string matching.

        Returns:
            List of matching CapabilityEntry.
        """
        cls._discover()
        helpers: list[CapabilityEntry] = []
        for plugin in cls._PLUGIN_DOMAINS.get(domain.strip(), []):
            try:
                plugin_helpers = plugin.get_helpers()
                if plugin_helpers:
                    helpers.extend(plugin_helpers)
            except Exception:
                continue
        return helpers

    @classmethod
    def list_domains(cls) -> list[str]:
        """Return all discovered domain tags (deduplicated and sorted)."""
        cls._discover()
        return sorted(cls._PLUGIN_DOMAINS.keys())

    @classmethod
    def get_providers(cls) -> list[Any]:
        """Return provider instances from all discovered plugins."""
        cls._discover()
        providers = []
        for plugin in cls._PLUGINS:
            try:
                provider = plugin.get_provider()
                if provider is not None:
                    providers.append(provider)
            except Exception:
                continue
        return providers

    @classmethod
    def find_provider(cls, predicate) -> Any | None:
        """Find a provider instance matching the given predicate.

        Args:
            predicate: function receiving a provider instance, returning bool.

        Returns:
            First matching provider instance, or None if not found.
        """
        cls._discover()
        for plugin in cls._PLUGINS:
            try:
                provider = plugin.get_provider()
                if provider is not None and predicate(provider):
                    return provider
            except Exception:
                continue
        return None

    @classmethod
    def list_manifests(cls) -> list[dict]:
        """Return manifest dicts from all discovered plugins."""
        cls._discover()
        manifests = []
        for plugin in cls._PLUGINS:
            try:
                m = plugin.get_manifest()
                if isinstance(m, dict):
                    manifests.append(m)
                elif hasattr(m, "to_dict"):
                    manifests.append(m.to_dict())
            except Exception:
                continue
        return manifests
