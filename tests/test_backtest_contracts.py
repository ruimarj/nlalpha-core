"""Tests for engine contracts and run-local data isolation."""

from importlib.metadata import distribution
from dataclasses import fields
import pickle
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nlalpha.core.backtest import (
    BACKTEST_FAILED,
    BACKTEST_SUCCEEDED,
    BacktestContext,
    BacktestResult,
    BacktestResultStatus,
    EngineManifest,
)


class BacktestContractTests(unittest.TestCase):
    def test_import_without_site_packages_or_backtest_service(self):
        with tempfile.TemporaryDirectory(prefix="nlalpha-standalone-metadata-") as directory:
            metadata = Path(directory) / "nlalpha_core.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(distribution("nlalpha-core").read_text("METADATA"), encoding="utf-8")
            source = str(Path(__file__).resolve().parents[1] / "src")
            script = f"""
import sys
sys.path.insert(0, {source!r})
sys.path.insert(0, {directory!r})
from nlalpha.core.backtest import (
    BACKTEST_FAILED, BACKTEST_SUCCEEDED, BacktestContext,
    BacktestEngineProvider, BacktestResult, EngineManifest,
)
from nlalpha.core.strategy import VectorizedStrategy
from nlalpha.core.strategy.runtime import VectorizedStrategy as RuntimeStrategy
assert RuntimeStrategy is VectorizedStrategy
assert BacktestContext('job', None, []).job_id == 'job'
assert BacktestResult('job', BACKTEST_SUCCEEDED, {{}}).is_successful
assert not BacktestResult('job', BACKTEST_FAILED, {{}}).is_successful
assert EngineManifest('probe', 'Probe', True).available
for dependency in ('nlalpha_backtest', 'nautilus_trader', 'pandas', 'numpy', 'pyarrow'):
    assert dependency not in sys.modules, dependency
"""
            process = subprocess.run(
                [sys.executable, "-I", "-S", "-c", script],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_context_configuration_is_local_to_each_run(self):
        first = BacktestContext("first", None, [])
        second = BacktestContext("second", None, [])
        first.execution_config["commission"] = 0.001
        first.capital_config["initial"] = 1000
        first.contract_config["symbol"] = "TEST"
        self.assertEqual(second.execution_config, {})
        self.assertEqual(second.capital_config, {})
        self.assertEqual(second.contract_config, {})

    def test_result_records_and_metadata_are_local_to_each_run(self):
        first = BacktestResult("first", BACKTEST_SUCCEEDED, {})
        second = BacktestResult("second", BACKTEST_SUCCEEDED, {})
        first.trade_details.append({"trade_id": "fill-1"})
        first.assumptions["execution"] = "bar_close"
        first.diagnostics["bars"] = 10
        first.errors.append({"message": "sample"})
        first.reproducibility["seed"] = 1
        first.reports["summary"] = {"report_id": "report-1"}
        self.assertEqual(second.trade_details, [])
        self.assertEqual(second.assumptions, {})
        self.assertEqual(second.diagnostics, {})
        self.assertEqual(second.errors, [])
        self.assertEqual(second.reproducibility, {})
        self.assertEqual(second.reports, {})

    def test_result_fields_match_backtest_package_contract(self):
        self.assertEqual(
            [field.name for field in fields(BacktestResult)],
            [
                "job_id", "status", "metrics", "equity_curve", "trade_details",
                "assumptions", "diagnostics", "errors", "benchmark",
                "reproducibility", "execution_quality", "cost_breakdown", "reports",
            ],
        )

    def test_result_status_accepts_only_success_or_failure(self):
        succeeded = BacktestResult("succeeded", BACKTEST_SUCCEEDED, {})
        failed = BacktestResult("failed", BACKTEST_FAILED, {})
        self.assertEqual(succeeded.status, BACKTEST_SUCCEEDED)
        self.assertEqual(failed.status, BACKTEST_FAILED)
        self.assertIs(succeeded.is_successful, True)
        self.assertIs(failed.is_successful, False)
        self.assertEqual(BacktestResultStatus.__args__, ("succeeded", "failed"))

    def test_result_status_rejects_completed_alias_and_unknown_values(self):
        for status in ("completed", "unknown"):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, "status must be"):
                    BacktestResult("job", status, {})

    def test_succeeded_result_with_errors_is_not_successful(self):
        result = BacktestResult(
            "job", BACKTEST_SUCCEEDED, {}, errors=[{"message": "partial failure"}]
        )
        self.assertIs(result.is_successful, False)

    def test_result_round_trip_preserves_audit_fields(self):
        result = BacktestResult(
            "job-1",
            BACKTEST_SUCCEEDED,
            {"total_return": 0.1},
            equity_curve=[("2026-01-01", 1000.0)],
            trade_details=[{"trade_id": "fill-1", "volume": 1}],
            assumptions={"execution": "bar_close"},
            diagnostics={"bars": 1},
            benchmark={"symbol": "INDEX"},
            reproducibility={"engine_version": "test"},
            execution_quality={"fill_count": 1},
            cost_breakdown={"commission": 0.1},
        )
        self.assertEqual(pickle.loads(pickle.dumps(result)), result)


if __name__ == "__main__":
    unittest.main()
