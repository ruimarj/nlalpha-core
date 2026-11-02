"""Tests for runtime negotiation and opaque batch input contracts."""

from importlib.metadata import distribution
from dataclasses import FrozenInstanceError, fields
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from nlalpha.core.backtest import (
    BATCH_SIGNALS,
    EVENT_DRIVEN,
    BacktestContext,
    BatchBacktestContext,
    BatchBacktestInput,
    EngineManifest,
)


class UntouchablePayload:
    """A payload whose contents and truthiness must remain unread."""

    def __bool__(self):
        raise AssertionError("Payload truthiness was evaluated")

    def __len__(self):
        raise AssertionError("Payload length was read")

    def __iter__(self):
        raise AssertionError("Payload was iterated")


class BatchInputTests(unittest.TestCase):
    def test_preserves_payload_references_without_inspection(self):
        market_data = UntouchablePayload()
        signals = UntouchablePayload()
        inputs = BatchBacktestInput("example.signals.v1", market_data, signals)
        self.assertIs(inputs.market_data, market_data)
        self.assertIs(inputs.signals, signals)
        with self.assertRaises(FrozenInstanceError):
            inputs.schema_id = "other.v1"

    def test_rejects_invalid_schema_ids(self):
        for schema_id in ("", " ", "\t", " schema.v1", "schema.v1 ", "schema.v1\n"):
            with self.subTest(schema_id=schema_id), self.assertRaises(ValueError):
                BatchBacktestInput(schema_id, [], [])
        for schema_id in (None, 1, b"schema.v1"):
            with self.subTest(schema_id=schema_id), self.assertRaises(TypeError):
                BatchBacktestInput(schema_id, [], [])

    def test_rejects_missing_payloads_but_allows_empty_payloads(self):
        for market_data, signals in ((None, []), ([], None), (None, None)):
            with self.subTest(market_data=market_data, signals=signals):
                with self.assertRaises(ValueError):
                    BatchBacktestInput("schema.v1", market_data, signals)
        BatchBacktestInput("schema.v1", [], [])

    def test_envelope_does_not_freeze_payload_contents(self):
        signals = []
        inputs = BatchBacktestInput("schema.v1", [], signals)
        signals.append(1)
        self.assertEqual(inputs.signals, [1])


class RuntimeContextTests(unittest.TestCase):
    def test_event_context_keeps_original_constructor_fields(self):
        self.assertEqual(
            [field.name for field in fields(BacktestContext)],
            [
                "job_id", "strategy_instance", "data", "execution_config",
                "capital_config", "contract_config", "progress_callback",
            ],
        )
        context = BacktestContext("event-job", None, [])
        self.assertEqual(context.runtime_mode, EVENT_DRIVEN)
        self.assertIsNone(context.input_schema)
        with self.assertRaises(AttributeError):
            context.runtime_mode = BATCH_SIGNALS
        with self.assertRaises(AttributeError):
            context.input_schema = "schema.v1"

    def test_batch_context_declares_input_contract(self):
        inputs = BatchBacktestInput("schema.v1", [], [])
        progress = lambda value, message: None
        context = BatchBacktestContext("batch-job", inputs, progress_callback=progress)
        self.assertIs(context.inputs, inputs)
        self.assertIs(context.progress_callback, progress)
        self.assertEqual(context.runtime_mode, BATCH_SIGNALS)
        self.assertEqual(context.input_schema, "schema.v1")
        with self.assertRaises(AttributeError):
            context.runtime_mode = EVENT_DRIVEN
        with self.assertRaises(AttributeError):
            context.input_schema = "schema.v2"

    def test_batch_configuration_is_local_to_each_run(self):
        inputs = BatchBacktestInput("schema.v1", [], [])
        first = BatchBacktestContext("first", inputs)
        second = BatchBacktestContext("second", inputs)
        first.execution_config["fee"] = 0.01
        first.capital_config["cash"] = 1000
        first.contract_config["currency"] = "USD"
        self.assertEqual(second.execution_config, {})
        self.assertEqual(second.capital_config, {})
        self.assertEqual(second.contract_config, {})

    def test_batch_context_rejects_untyped_inputs(self):
        for inputs in (None, {}, [], "schema.v1"):
            with self.subTest(inputs=inputs), self.assertRaises(TypeError):
                BatchBacktestContext("job", inputs)


class EngineManifestTests(unittest.TestCase):
    def test_old_positional_constructor_defaults_to_event_only(self):
        manifest = EngineManifest("legacy", "Legacy", False, "Not installed")
        self.assertEqual(manifest.runtime_modes, (EVENT_DRIVEN,))
        self.assertEqual(manifest.input_schemas, ())
        self.assertTrue(manifest.supports(EVENT_DRIVEN))
        self.assertFalse(manifest.supports(EVENT_DRIVEN, "schema.v1"))
        self.assertFalse(manifest.supports(BATCH_SIGNALS))
        self.assertFalse(manifest.supports(BATCH_SIGNALS, "schema.v1"))
        self.assertFalse(manifest.available)
        self.assertEqual(manifest.unavailable_reason, "Not installed")

    def test_supports_requires_runtime_and_exact_schema(self):
        batch = EngineManifest(
            "batch", "Batch", True,
            runtime_modes=(BATCH_SIGNALS,), input_schemas=("schema.v1",),
        )
        self.assertTrue(batch.supports(BATCH_SIGNALS, "schema.v1"))
        for mode, schema in (
            (EVENT_DRIVEN, None), (EVENT_DRIVEN, "schema.v1"),
            (BATCH_SIGNALS, None), (BATCH_SIGNALS, "schema.v2"),
            (BATCH_SIGNALS, " schema.v1"), (BATCH_SIGNALS, ""),
            ("unknown", "schema.v1"),
        ):
            with self.subTest(mode=mode, schema=schema):
                self.assertFalse(batch.supports(mode, schema))
        both = EngineManifest(
            "both", "Both", True,
            runtime_modes=(EVENT_DRIVEN, BATCH_SIGNALS), input_schemas=("schema.v1",),
        )
        self.assertTrue(both.supports(EVENT_DRIVEN))
        self.assertFalse(both.supports(EVENT_DRIVEN, "schema.v1"))
        self.assertTrue(both.supports(BATCH_SIGNALS, "schema.v1"))

    def test_normalizes_collections_without_retaining_mutable_lists(self):
        modes = [EVENT_DRIVEN, BATCH_SIGNALS]
        schemas = ["schema.v1"]
        manifest = EngineManifest("both", "Both", True, runtime_modes=modes, input_schemas=schemas)
        modes.clear()
        schemas.clear()
        self.assertEqual(manifest.runtime_modes, (EVENT_DRIVEN, BATCH_SIGNALS))
        self.assertEqual(manifest.input_schemas, ("schema.v1",))

    def test_rejects_string_collections(self):
        for field, value in (
            ("runtime_modes", EVENT_DRIVEN), ("runtime_modes", b"event_driven"),
            ("input_schemas", "schema.v1"), ("input_schemas", b"schema.v1"),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(TypeError):
                EngineManifest("test", "Test", True, **{field: value})

    def test_rejects_missing_or_unknown_modes(self):
        for modes in ((), ("",), ("unknown",), (" event_driven",), (None,)):
            with self.subTest(modes=modes), self.assertRaises(ValueError):
                EngineManifest("test", "Test", True, runtime_modes=modes)
        with self.assertRaises(ValueError):
            EngineManifest("test", "Test", True, runtime_modes=(BATCH_SIGNALS,))

    def test_rejects_invalid_batch_schema_ids(self):
        for schema_id in ("", " ", " schema.v1", "schema.v1 "):
            with self.subTest(schema_id=schema_id), self.assertRaises(ValueError):
                EngineManifest(
                    "test", "Test", True,
                    runtime_modes=(BATCH_SIGNALS,), input_schemas=(schema_id,),
                )
        with self.assertRaises(TypeError):
            EngineManifest(
                "test", "Test", True,
                runtime_modes=(BATCH_SIGNALS,), input_schemas=(None,),
            )

    def test_to_dict_includes_all_fields_and_json_arrays(self):
        manifest = EngineManifest(
            "batch", "Batch", False, "Dependency missing",
            runtime_modes=(BATCH_SIGNALS,), input_schemas=("schema.v1",),
        )
        metadata = manifest.to_dict()
        self.assertEqual(set(metadata), {field.name for field in fields(manifest)})
        self.assertEqual(metadata["runtime_modes"], [BATCH_SIGNALS])
        self.assertEqual(metadata["input_schemas"], ["schema.v1"])
        self.assertEqual(json.loads(json.dumps(metadata)), metadata)
        metadata["runtime_modes"].clear()
        self.assertEqual(manifest.runtime_modes, (BATCH_SIGNALS,))


class StandaloneImportTests(unittest.TestCase):
    def test_batch_contracts_need_no_site_packages(self):
        with tempfile.TemporaryDirectory(prefix="nlalpha-standalone-metadata-") as directory:
            metadata = Path(directory) / "nlalpha_core.dist-info"
            metadata.mkdir()
            (metadata / "METADATA").write_text(distribution("nlalpha-core").read_text("METADATA"), encoding="utf-8")
            source = str(Path(__file__).resolve().parents[1] / "src")
            script = f"""
import sys
from typing import get_args
sys.path.insert(0, {source!r})
sys.path.insert(0, {directory!r})
from nlalpha.core.backtest import (
    BATCH_SIGNALS, EVENT_DRIVEN, BacktestContext, BacktestEngineProvider,
    BatchBacktestContext, BatchBacktestInput, EngineManifest, EngineRunContext,
)
inputs = BatchBacktestInput('schema.v1', [], [])
context = BatchBacktestContext('job', inputs)
manifest = EngineManifest('batch', 'Batch', True,
    runtime_modes=(BATCH_SIGNALS,), input_schemas=('schema.v1',))
assert manifest.supports(context.runtime_mode, context.input_schema)
assert set(get_args(EngineRunContext)) == {{BacktestContext, BatchBacktestContext}}
BacktestEngineProvider[BacktestContext]
BacktestEngineProvider[BatchBacktestContext]
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


if __name__ == "__main__":
    unittest.main()
