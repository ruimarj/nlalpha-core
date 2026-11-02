"""Runtime manifest shared by all capability providers.

Used for result auditing: records the library, version, and available
capabilities used for a computation.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProviderManifest:
    """Runtime manifest for a capability provider."""

    provider_id: str
    provider_name: str
    provider_version: str | None = None

    available: bool = True
    unavailable_reason: str | None = None
    methods: list[str] = field(default_factory=list)
    conventions: dict = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)  # Provider 分类标签
    extra: dict[str, Any] = field(default_factory=dict)  # 开放扩展字段，用于未来权限控制、商业化 tier 等

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "methods": self.methods,
            "conventions": self.conventions,
            "domains": self.domains,
            "extra": self.extra,
        }
