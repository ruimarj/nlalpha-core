"""Backtest engine provider protocol and availability manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

from nlalpha.core.backtest.context import EngineRunContext
from nlalpha.core.backtest.input import BATCH_SIGNALS, EVENT_DRIVEN, _validate_schema_id
from nlalpha.core.backtest.result import BacktestResult


ContextT = TypeVar("ContextT", bound=EngineRunContext, contravariant=True)


@dataclass(frozen=True)
class EngineManifest:
    """Engine identity, availability, and accepted runtime/input contracts."""

    engine_id: str
    engine_name: str
    available: bool
    unavailable_reason: str | None = None
    runtime_modes: tuple[str, ...] = (EVENT_DRIVEN,)
    input_schemas: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("engine_id", "engine_name"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a nonempty trimmed string")
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")
        if self.unavailable_reason is not None and (
            not isinstance(self.unavailable_reason, str) or not self.unavailable_reason.strip()
        ):
            raise ValueError("unavailable_reason must be a nonempty string or null")
        if self.available and self.unavailable_reason is not None:
            raise ValueError("available engines cannot declare an unavailable_reason")
        for name in ("runtime_modes", "input_schemas"):
            values = getattr(self, name)
            if isinstance(values, (str, bytes)):
                raise TypeError(f"{name} must be an iterable of strings, not a string")
            try:
                normalized = tuple(values)
            except TypeError as exc:
                raise TypeError(f"{name} must be an iterable of strings") from exc
            object.__setattr__(self, name, normalized)
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{name} must contain unique values")

        if not self.runtime_modes:
            raise ValueError("runtime_modes must not be empty")
        for mode in self.runtime_modes:
            if not isinstance(mode, str) or mode not in (EVENT_DRIVEN, BATCH_SIGNALS):
                raise ValueError(f"Unknown runtime mode: {mode!r}")
        for schema_id in self.input_schemas:
            _validate_schema_id(schema_id)
        if BATCH_SIGNALS in self.runtime_modes and not self.input_schemas:
            raise ValueError("batch_signals requires at least one input schema")

    def supports(self, runtime_mode: str, input_schema: str | None = None) -> bool:
        """Match a runtime and its declared batch input schema."""
        if runtime_mode not in self.runtime_modes:
            return False
        if runtime_mode == EVENT_DRIVEN:
            return input_schema is None
        return input_schema is not None and input_schema in self.input_schemas

    def to_dict(self) -> dict:
        """Return JSON-friendly metadata for this engine."""
        return {
            "engine_id": self.engine_id,
            "engine_name": self.engine_name,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "runtime_modes": list(self.runtime_modes),
            "input_schemas": list(self.input_schemas),
        }


class BacktestEngineProvider(Protocol[ContextT]):
    """Contract implemented by backtest engine providers."""

    def manifest(self) -> EngineManifest:
        """Return the engine manifest."""
        ...

    def confess(self) -> str:
        """Describe capabilities, limitations, and usage guidance."""
        ...

    async def run(self, context: ContextT) -> BacktestResult:
        """Execute a backtest and return its standardized result."""
        ...
