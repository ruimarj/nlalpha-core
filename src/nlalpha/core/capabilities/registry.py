"""Capability registry: unified entry for capability declarations and provider discovery."""

from dataclasses import dataclass, field
import logging
from copy import deepcopy
from importlib.metadata import entry_points
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from nlalpha.core.capabilities.plugin.protocol import CapabilityPlugin
from nlalpha.core.errors import InvalidRequestError, NlAlphaError

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
    def register_family(cls, family: str, helpers: list[CapabilityEntry]) -> FamilyCapabilitySet:
        """Publish and return a family's helper declaration."""
        capability_set = FamilyCapabilitySet(family=family, helpers=list(helpers))
        cls._FAMILY_HELPERS[family] = capability_set
        return capability_set

    @classmethod
    def unregister_family(cls, family: str, expected: FamilyCapabilitySet) -> None:
        """Remove a family declaration only while its publisher still owns it."""
        if cls._FAMILY_HELPERS.get(family) is expected:
            del cls._FAMILY_HELPERS[family]

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
        """Filter the discovered global helper catalog by its helper domain."""
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


@dataclass
class CapabilityDiscoveryRecord:
    """Installed entry-point identity and its resolved capability state."""

    entry_point: str
    target: str
    package: str | None = None
    version: str | None = None
    plugin: Any = None
    manifest: dict | None = None
    provider: Any = None
    helpers: tuple[CapabilityEntry, ...] = ()
    guidance: str | None = None
    status: Literal["available", "unavailable", "load_failed"] = "load_failed"
    reason: str = ""

    def describe(self) -> dict[str, Any]:
        """Return serializable discovery metadata and provider declarations."""
        return {
            "entry_point": self.entry_point, "target": self.target,
            "package": self.package, "version": self.version,
            "status": self.status, "reason": self.reason,
            "manifest": deepcopy(self.manifest), "helper_count": len(self.helpers),
        }


class CapabilityPluginRegistry:
    """Discover installed capability plugins into one cached record set."""

    _records: list[CapabilityDiscoveryRecord] | None = None
    _lock = Lock()

    @classmethod
    def reset(cls) -> None:
        """Clear discovery state for an explicit rediscovery."""
        with cls._lock:
            cls._records = None

    @classmethod
    def _discover(cls) -> list[CapabilityDiscoveryRecord]:
        snapshot = cls._records
        if snapshot is not None:
            return snapshot
        with cls._lock:
            snapshot = cls._records
            if snapshot is not None:
                return snapshot
            points = entry_points().select(group="nlalpha.capabilities")
            records = []
            for point in points:
                record = CapabilityDiscoveryRecord(point.name, point.value)
                if point.dist is not None:
                    record.package = point.dist.metadata["Name"]
                    record.version = point.dist.version
                    if (not isinstance(record.package, str) or not record.package
                            or record.package != record.package.strip()):
                        raise ValueError("distribution Name must be a nonempty trimmed string")
                    if (not isinstance(record.version, str) or not record.version
                            or record.version != record.version.strip()):
                        raise ValueError("distribution version must be a nonempty trimmed string")
                stage = "load"
                try:
                    record.plugin = point.load()()
                    if not isinstance(record.plugin, CapabilityPlugin):
                        raise TypeError("plugin does not implement CapabilityPlugin")
                    stage = "is_available"
                    available = record.plugin.is_available()
                    if type(available) is not bool:
                        raise TypeError("is_available must return bool")
                    stage = "get_manifest"
                    manifest = record.plugin.get_manifest()
                    if not isinstance(manifest, dict):
                        raise TypeError("get_manifest must return dict")
                    for name in ("provider_id", "provider_name"):
                        value = manifest.get(name)
                        if not isinstance(value, str) or not value or value != value.strip():
                            raise ValueError(f"manifest {name} must be a nonempty trimmed string")
                    if type(manifest.get("available")) is not bool:
                        raise TypeError("manifest available must be bool")
                    domains = manifest.get("domains", [])
                    if not isinstance(domains, list) or any(
                        not isinstance(domain, str) or not domain or domain != domain.strip()
                        for domain in domains
                    ):
                        raise TypeError("manifest domains must be a list of nonempty trimmed strings")
                    record.manifest = deepcopy(manifest)
                    if not available or manifest.get("available") is False:
                        record.status = "unavailable"
                        record.reason = str(manifest.get("unavailable_reason") or "plugin reports unavailable")
                    else:
                        stage = "get_provider"
                        provider = record.plugin.get_provider()
                        if provider is None:
                            raise TypeError("available plugin returned no provider")
                        stage = "get_helpers"
                        helpers = record.plugin.get_helpers()
                        if not isinstance(helpers, list) or any(not isinstance(h, CapabilityEntry) for h in helpers):
                            raise TypeError("get_helpers must return a list of CapabilityEntry")
                        record.provider = provider
                        record.helpers = tuple(helpers)
                        stage = "get_prompt_path"
                        prompt_path = record.plugin.get_prompt_path()
                        if prompt_path is not None:
                            if not isinstance(prompt_path, str) or not prompt_path.strip():
                                raise TypeError("get_prompt_path must return a nonempty path or None")
                            record.guidance = Path(prompt_path).read_text(encoding="utf-8")
                        record.status = "available"
                except Exception as exc:
                    record.status = "load_failed"
                    record.reason = f"{stage}: {type(exc).__name__}: {exc}"
                    record.provider = None
                    record.helpers = ()
                records.append(record)
            identities: dict[str, list[CapabilityDiscoveryRecord]] = {}
            for record in records:
                if record.manifest is not None:
                    identities.setdefault(record.manifest["provider_id"], []).append(record)
            for identity, matches in identities.items():
                if len(matches) > 1:
                    for record in matches:
                        record.status = "load_failed"
                        record.reason = f"duplicate provider_id: {identity}"
                        record.provider = None
                        record.helpers = ()
            for record in records:
                if record.status != "available":
                    logger.warning(
                        "Installed capability plugin unavailable | entry_point=%s status=%s reason=%s",
                        record.entry_point, record.status, record.reason,
                    )
            cls._records = records
            return records

    @classmethod
    def get_discovered_helpers(cls) -> list[CapabilityEntry]:
        """Return helpers from fully available discovery records."""
        records = cls._discover()
        return [helper for record in records if record.status == "available" for helper in record.helpers]

    @classmethod
    def get_helpers_by_domain(cls, domain: str) -> list[CapabilityEntry]:
        """Match helper domains independently of provider manifest classifications."""
        return [helper for helper in cls.get_discovered_helpers() if helper.domain == domain.strip()]

    @classmethod
    def list_domains(cls) -> list[str]:
        """Return the sorted set of available helper domains."""
        return sorted({helper.domain for helper in cls.get_discovered_helpers() if helper.domain})

    @classmethod
    def get_providers(cls) -> list[Any]:
        """Return the cached provider instances of fully available plugins."""
        records = cls._discover()
        return [record.provider for record in records if record.status == "available"]

    @classmethod
    def find_provider(cls, predicate) -> Any | None:
        """Find the first cached provider satisfying the caller's predicate."""
        return next((provider for provider in cls.get_providers() if predicate(provider)), None)

    @classmethod
    def list_manifests(cls) -> list[dict]:
        """Return copied manifests of fully available providers."""
        records = cls._discover()
        return [deepcopy(record.manifest) for record in records if record.status == "available"]

    @classmethod
    def list_provider_records(cls) -> list[dict[str, Any]]:
        """Describe every installed provider, including providers without helpers."""
        records = cls._discover()
        return [record.describe() for record in records]

    @classmethod
    def diagnostics(cls) -> list[dict[str, Any]]:
        """Describe installed plugins that are unavailable or failed to load."""
        return [record for record in cls.list_provider_records() if record["status"] != "available"]

    @classmethod
    def get_record(cls, provider_id: str) -> CapabilityDiscoveryRecord:
        """Resolve a selectable provider or distinguish absent and failed installations."""
        if not isinstance(provider_id, str) or not provider_id or provider_id != provider_id.strip():
            raise InvalidRequestError("provider_id must be a nonempty trimmed string", stage="request")
        records = cls._discover()
        matches = [record for record in records
                   if record.manifest is not None and record.manifest.get("provider_id") == provider_id]
        available = next((record for record in matches if record.status == "available"), None)
        if available is not None:
            return available
        faults = matches or [record for record in records
                             if record.entry_point == provider_id and record.status != "available"]
        if faults:
            raise NlAlphaError(
                f"Installed capability provider is unavailable: {provider_id}",
                details={"diagnostics": [record.describe() for record in faults]}, stage="load",
            )
        raise InvalidRequestError(
            f"Unknown capability provider: {provider_id}",
            details={"available_providers": [record.manifest["provider_id"] for record in records
                                             if record.status == "available"]}, stage="request",
        )
