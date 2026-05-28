"""Generic envelope for strategy contracts.

The backbone only understands generic fields and does not parse family_spec internals.
This is the public protocol — new families should not modify this file.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategySpecEnvelope:
    """Generic strategy specification envelope."""

    id: str
    version: str = "0.1"
    family: str = ""
    universe: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    capital: dict[str, Any] = field(default_factory=dict)
    family_spec: dict[str, Any] = field(default_factory=dict)
    assumptions: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dict."""
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StrategySpecEnvelope":
        """Deserialize from dict."""
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}

        # 防御性处理：如果缺少 id 则自动生成
        if "id" not in filtered or not filtered["id"]:
            import uuid

            filtered["id"] = f"spec-{uuid.uuid4().hex[:12]}"

        return cls(**filtered)
