"""Shared result format for backtest engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BACKTEST_SUCCEEDED = "succeeded"
BACKTEST_FAILED = "failed"
BacktestResultStatus = Literal["succeeded", "failed"]


@dataclass(frozen=True)
class BacktestResult:
    """Engine-independent backtest output."""

    job_id: str
    status: BacktestResultStatus
    metrics: dict
    equity_curve: list[tuple] | None = None
    trade_details: list[dict] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    benchmark: dict | None = None
    reproducibility: dict = field(default_factory=dict)
    execution_quality: dict | None = None
    cost_breakdown: dict | None = None
    reports: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in (BACKTEST_SUCCEEDED, BACKTEST_FAILED):
            raise ValueError(
                "status must be 'succeeded' or 'failed', "
                f"got {self.status!r}"
            )
        if not isinstance(self.reports, dict):
            raise TypeError("reports must be a dictionary")

    @property
    def is_successful(self) -> bool:
        """Return whether this result is a clean successful backtest."""
        return self.status == BACKTEST_SUCCEEDED and not self.errors
