"""Discover strategy families and publish their validated capability contracts."""

from dataclasses import dataclass
from importlib.metadata import entry_points
import logging
from threading import Lock
from typing import Any, Literal

from nlalpha.core.capabilities.contract import FamilyContract
from nlalpha.core.capabilities.registry import CapabilityEntry, CapabilityRegistry, FamilyCapabilitySet
from nlalpha.core.errors import InvalidRequestError, NlAlphaError
from nlalpha.core.strategy.plugin.protocol import BaseStrategyFamilyPlugin

logger = logging.getLogger("nlalpha.strategy.plugin.registry")


@dataclass
class StrategyFamilyRecord:
    """One installed family identity with its cached contract and notes."""

    entry_point: str
    target: str
    package: str | None = None
    version: str | None = None
    family: str | None = None
    plugin: BaseStrategyFamilyPlugin | None = None
    contract: FamilyContract | None = None
    confession: str | None = None
    status: Literal["available", "load_failed"] = "load_failed"
    reason: str = ""

    def describe(self) -> dict[str, Any]:
        """Return serializable identity and discovery diagnostics."""
        return {
            "entry_point": self.entry_point, "target": self.target,
            "package": self.package, "version": self.version, "family": self.family,
            "status": self.status, "reason": self.reason,
            "helper_count": len(self.contract.helpers) if self.contract is not None and self.status == "available" else 0,
        }


class StrategyFamilyRegistry:
    """Cache installed family records and publish only validated unique families."""

    _records: list[StrategyFamilyRecord] | None = None
    _published: dict[str, FamilyCapabilitySet] = {}
    _lock = Lock()

    @classmethod
    def clear(cls) -> None:
        """Reset discovery and remove declarations owned by this registry."""
        with cls._lock:
            for family, capability_set in cls._published.items():
                CapabilityRegistry.unregister_family(family, capability_set)
            cls._published = {}
            cls._records = None

    @classmethod
    def _discover(cls) -> list[StrategyFamilyRecord]:
        snapshot = cls._records
        if snapshot is not None:
            return snapshot
        with cls._lock:
            snapshot = cls._records
            if snapshot is not None:
                return snapshot
            points = entry_points().select(group="nlalpha.strategies")
            records = []
            for point in points:
                record = StrategyFamilyRecord(point.name, point.value)
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
                    plugin_type = point.load()
                    if not isinstance(plugin_type, type) or not issubclass(plugin_type, BaseStrategyFamilyPlugin):
                        raise TypeError("strategy family plugin must inherit BaseStrategyFamilyPlugin")
                    record.family = plugin_type.family
                    record.plugin = plugin_type()
                    if record.plugin.family != record.family:
                        raise ValueError("plugin instance family must match its class declaration")
                    stage = "family_contract"
                    contract = record.plugin.family_contract()
                    if not isinstance(contract, FamilyContract):
                        raise TypeError("family_contract must return FamilyContract")
                    if (not isinstance(contract.family, str) or not contract.family
                            or contract.family != contract.family.strip() or contract.family != record.family):
                        raise ValueError("contract family must match the nonempty trimmed plugin family")
                    if (not isinstance(contract.helpers, list)
                            or any(not isinstance(helper, CapabilityEntry) for helper in contract.helpers)):
                        raise TypeError("contract helpers must be a list of CapabilityEntry")
                    names = [helper.name for helper in contract.helpers]
                    if len(names) != len(set(names)):
                        raise ValueError("contract helper names must be unique")
                    record.contract = contract
                    stage = "confess"
                    record.confession = record.plugin.confess()
                    if not isinstance(record.confession, str):
                        raise TypeError("confess must return str")
                    record.status = "available"
                except Exception as exc:
                    record.status = "load_failed"
                    record.reason = f"{stage}: {type(exc).__name__}: {exc}"
                records.append(record)
            identities: dict[str, list[StrategyFamilyRecord]] = {}
            for record in records:
                if record.family is not None:
                    identities.setdefault(record.family, []).append(record)
            for family, matches in identities.items():
                if len(matches) > 1:
                    for record in matches:
                        record.status = "load_failed"
                        record.reason = f"duplicate strategy family: {family}"
            for record in records:
                if record.status == "available" and CapabilityRegistry.get_family(record.family) is not None:
                    record.status = "load_failed"
                    record.reason = "publish: family declaration already belongs to another publisher"
            published = {}
            try:
                for record in records:
                    if record.status == "available":
                        published[record.family] = CapabilityRegistry.register_family(record.family, record.contract.helpers)
            except Exception:
                for family, capability_set in published.items():
                    CapabilityRegistry.unregister_family(family, capability_set)
                raise
            for record in records:
                if record.status != "available":
                    logger.warning(
                        "Installed strategy family failed | entry_point=%s reason=%s", record.entry_point, record.reason,
                    )
            cls._published = published
            cls._records = records
            return records

    @classmethod
    def get_record(cls, family: str) -> StrategyFamilyRecord:
        """Resolve an available family or distinguish absent and failed installations."""
        if not isinstance(family, str) or not family or family != family.strip():
            raise InvalidRequestError("family must be a nonempty trimmed string", stage="request")
        records = cls._discover()
        matches = [record for record in records if record.family == family]
        available = next((record for record in matches if record.status == "available"), None)
        if available is not None:
            return available
        faults = matches or [record for record in records
                             if record.entry_point == family and record.status != "available"]
        if faults:
            raise NlAlphaError(
                f"Installed strategy family is unavailable: {family}",
                details={"diagnostics": [record.describe() for record in faults]}, stage="load",
            )
        raise InvalidRequestError(
            f"Unknown strategy family: {family}",
            details={"available_families": sorted(record.family for record in records if record.status == "available")}, stage="request",
        )

    @classmethod
    def list_families(cls) -> list[str]:
        """List selectable family identities from cached available records."""
        records = cls._discover()
        return sorted(record.family for record in records if record.status == "available")

    @classmethod
    def list_records(cls) -> list[dict[str, Any]]:
        """Describe all installed families, including failed installations."""
        records = cls._discover()
        return [record.describe() for record in records]

    @classmethod
    def diagnostics(cls) -> list[dict[str, Any]]:
        """Describe installed strategy families that failed discovery."""
        return [record for record in cls.list_records() if record["status"] != "available"]
