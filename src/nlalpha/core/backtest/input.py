"""Runtime identifiers and opaque, versioned batch input payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EVENT_DRIVEN = "event_driven"
BATCH_SIGNALS = "batch_signals"


def _validate_schema_id(schema_id: str) -> None:
    """Validate a schema identifier shared by an input and provider manifest."""
    if not isinstance(schema_id, str):
        raise TypeError("schema_id must be a string")
    if not schema_id or schema_id != schema_id.strip():
        raise ValueError("schema_id must be nonempty without surrounding whitespace")


@dataclass(frozen=True)
class BatchBacktestInput:
    """Carry plugin-owned market data and signals under a schema identifier.

    Core validates the identifier and payload presence while preserving payload references.
    The consuming plugin validates the concrete payload schema.
    """

    schema_id: str
    market_data: Any
    signals: Any

    def __post_init__(self) -> None:
        _validate_schema_id(self.schema_id)
        if self.market_data is None:
            raise ValueError("market_data must not be None")
        if self.signals is None:
            raise ValueError("signals must not be None")
