"""Verify isolated process telemetry ownership, lazy access, and pytest teardown."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


class TelemetryLifecycleTests(unittest.TestCase):
    def test_instrumentation_requires_installed_distribution_metadata(self):
        self.run_process('''
            from importlib.metadata import PackageNotFoundError, version
            from unittest.mock import patch
            from nlalpha.core import telemetry
            assert telemetry._instrumentation_version() == version("nlalpha-core")
            with patch.object(telemetry, "version", side_effect=PackageNotFoundError("nlalpha-core")):
                try:
                    telemetry._instrumentation_version()
                except PackageNotFoundError:
                    pass
                else:
                    raise AssertionError("Missing installed metadata was hidden")
        ''')

    def run_process(self, source: str) -> subprocess.CompletedProcess[str]:
        """Execute lifecycle assertions in an independent Python interpreter."""
        environment = os.environ.copy()
        for name in (
            "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            "OTEL_PYTHON_TRACER_PROVIDER", "OTEL_PYTHON_METER_PROVIDER", "OTEL_PYTHON_LOGGER_PROVIDER",
        ):
            environment.pop(name, None)
        result = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(source)], env=environment,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_import_and_default_getters_create_no_exporters_or_worker_threads(self):
        self.run_process("""
            import threading
            from unittest.mock import patch
            from opentelemetry.sdk import trace, metrics, _logs
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
            from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter

            before = {thread.ident for thread in threading.enumerate()}
            with patch.object(trace.TracerProvider, '__init__', side_effect=AssertionError('trace provider created')), \\
                 patch.object(metrics.MeterProvider, '__init__', side_effect=AssertionError('meter provider created')), \\
                 patch.object(_logs.LoggerProvider, '__init__', side_effect=AssertionError('log provider created')), \\
                 patch.object(ConsoleSpanExporter, '__init__', side_effect=AssertionError('span exporter created')), \\
                 patch.object(ConsoleMetricExporter, '__init__', side_effect=AssertionError('metric exporter created')), \\
                 patch.object(ConsoleLogRecordExporter, '__init__', side_effect=AssertionError('log exporter created')):
                from nlalpha.core import telemetry
                assert before == {thread.ident for thread in threading.enumerate()}
                telemetry.get_tracer()
                telemetry.get_meter()
                telemetry.get_otel_log_handler()
                with telemetry.start_span('unconfigured'):
                    pass
                assert before == {thread.ident for thread in threading.enumerate()}
                telemetry.shutdown()
        """)

    def test_concurrent_getters_and_configuration_initialize_each_resource_once(self):
        self.run_process("""
            from concurrent.futures import ThreadPoolExecutor
            from unittest.mock import Mock, patch
            from nlalpha.core import telemetry

            tracer, meter, handler = object(), object(), Mock()
            with patch.object(telemetry._trace, 'get_tracer', return_value=tracer) as trace_get, \\
                 patch.object(telemetry._metrics, 'get_meter', return_value=meter) as meter_get, \\
                 patch.object(telemetry, '_TelemetryLoggingHandler', return_value=handler) as handler_get:
                def read(_):
                    return telemetry.get_tracer(), telemetry.get_meter(), telemetry.get_otel_log_handler()
                with ThreadPoolExecutor(max_workers=16) as pool:
                    values = list(pool.map(read, range(64)))
                assert all(value == (tracer, meter, handler) for value in values)
                trace_get.assert_called_once()
                meter_get.assert_called_once()
                handler_get.assert_called_once()
            with patch.object(telemetry, '_build_provider', wraps=telemetry._build_provider) as build:
                with ThreadPoolExecutor(max_workers=16) as pool:
                    list(pool.map(lambda _: telemetry.configure_telemetry(), range(64)))
                assert [call.args[0] for call in build.call_args_list] == ['trace', 'metrics', 'logs']
            telemetry.shutdown()
            handler.close.assert_called_once()
        """)

    def test_external_providers_are_reused_and_never_flushed_or_closed(self):
        self.run_process("""
            import logging
            from contextlib import ExitStack
            from unittest.mock import patch
            from opentelemetry import trace, metrics, _logs
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk._logs import LoggerProvider

            providers = [TracerProvider(shutdown_on_exit=False), MeterProvider(shutdown_on_exit=False),
                         LoggerProvider(shutdown_on_exit=False)]
            trace.set_tracer_provider(providers[0])
            metrics.set_meter_provider(providers[1])
            _logs.set_logger_provider(providers[2])
            from nlalpha.core import telemetry
            with ExitStack() as stack:
                flushes = [stack.enter_context(patch.object(provider, 'force_flush', return_value=True))
                           for provider in providers]
                closes = [stack.enter_context(patch.object(provider, 'shutdown')) for provider in providers]
                with patch.object(providers[0], 'get_tracer', wraps=providers[0].get_tracer) as traced, \\
                     patch.object(providers[1], 'get_meter', wraps=providers[1].get_meter) as metered:
                    telemetry.get_tracer()
                    telemetry.get_meter()
                    traced.assert_called_once()
                    metered.assert_called_once()
                handler = telemetry.get_otel_log_handler()
                logging.getLogger().addHandler(handler)
                telemetry.force_flush()
                telemetry.shutdown()
                handler.flush()
                assert handler not in logging.getLogger().handlers
                assert all(not method.called for method in flushes + closes)
            for provider in providers:
                provider.shutdown()
        """)

    def test_handler_keeps_sdk_flush_semantics_until_it_is_closed(self):
        self.run_process("""
            import threading
            from unittest.mock import patch
            from opentelemetry import _logs
            from opentelemetry.sdk._logs import LoggerProvider
            external = LoggerProvider(shutdown_on_exit=False)
            _logs.set_logger_provider(external)
            from nlalpha.core import telemetry
            event = threading.Event()
            with patch.object(external, 'force_flush', side_effect=event.set) as flush:
                handler = telemetry.get_otel_log_handler()
                handler.flush()
                assert event.wait(2), 'live handler did not flush its provider'
                assert flush.call_count == 1
                handler.close()
                handler.close()
                event.clear()
                handler.flush()
                assert not event.is_set()
                assert flush.call_count == 1
                telemetry.shutdown()
                assert flush.call_count == 1
            external.shutdown()
        """)

    def test_owned_signals_flush_close_and_detach_exactly_once(self):
        self.run_process("""
            import logging
            from contextlib import ExitStack
            from unittest.mock import patch
            from nlalpha.core import telemetry

            telemetry.configure_telemetry()
            providers = [telemetry._trace.get_tracer_provider(), telemetry._metrics.get_meter_provider(),
                         telemetry._logs.get_logger_provider()]
            handler = telemetry.get_otel_log_handler()
            named = logging.getLogger('lifecycle.named')
            logging.getLogger().addHandler(handler)
            named.addHandler(handler)
            with ExitStack() as stack:
                flushes = [stack.enter_context(patch.object(provider, 'force_flush', return_value=True))
                           for provider in providers]
                closes = [stack.enter_context(patch.object(provider, 'shutdown', wraps=provider.shutdown))
                          for provider in providers]
                close_handler = stack.enter_context(patch.object(handler, 'close', wraps=handler.close))
                assert telemetry.force_flush(timeout_millis=17)
                assert all(method.call_args.kwargs == {'timeout_millis': 17} for method in flushes)
                telemetry.shutdown(timeout_millis=19)
                assert all(method.call_count == 2 for method in flushes)
                assert all(method.call_args.kwargs == {'timeout_millis': 19} for method in flushes)
                closes[0].assert_called_once_with()
                closes[1].assert_called_once_with(timeout_millis=19)
                closes[2].assert_called_once_with()
                close_handler.assert_called_once()
                assert handler not in named.handlers and handler not in logging.getLogger().handlers
                telemetry.shutdown()
                assert telemetry.force_flush()
                assert all(method.call_count == 1 for method in closes)
                assert all(method.call_count == 2 for method in flushes)
                close_handler.assert_called_once()
            for access in (telemetry.get_tracer, telemetry.get_meter, telemetry.get_otel_log_handler,
                           telemetry.configure_telemetry):
                try:
                    access()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('closed process accepted instrumentation')
        """)

    def test_flush_errors_preserve_all_signal_cleanup_and_repeat_shutdown_is_safe(self):
        self.run_process("""
            from types import SimpleNamespace
            from unittest.mock import Mock, patch
            from nlalpha.core import telemetry

            providers = [SimpleNamespace(force_flush=Mock(return_value=True), shutdown=Mock()) for _ in range(3)]
            providers[0].force_flush.side_effect = ValueError('trace flush failed')
            providers[1].force_flush.return_value = False
            providers[0].shutdown.side_effect = OSError('trace close failed')
            with patch.object(telemetry, '_build_provider', side_effect=providers):
                telemetry.configure_telemetry()
            try:
                telemetry.force_flush()
            except ExceptionGroup as error:
                assert len(error.exceptions) == 2
                assert {type(exc) for exc in error.exceptions} == {ValueError, TimeoutError}
            else:
                raise AssertionError('flush failures were hidden')
            assert all(provider.force_flush.call_count == 1 for provider in providers)
            try:
                telemetry.shutdown()
            except ExceptionGroup as error:
                assert len(error.exceptions) == 3
                assert {type(exc) for exc in error.exceptions} == {ValueError, TimeoutError, OSError}
            else:
                raise AssertionError('shutdown failures were hidden')
            assert all(provider.shutdown.call_count == 1 for provider in providers)
            telemetry.shutdown()
            assert all(provider.shutdown.call_count == 1 for provider in providers)
        """)

    def test_configuration_conflict_closes_candidates_and_preserves_external_provider(self):
        self.run_process("""
            from types import SimpleNamespace
            from unittest.mock import Mock, patch
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider

            external = TracerProvider(shutdown_on_exit=False)
            trace.set_tracer_provider(external)
            from nlalpha.core import telemetry
            providers = [SimpleNamespace(force_flush=Mock(), shutdown=Mock()) for _ in range(3)]
            handler = telemetry.get_otel_log_handler()
            with patch.object(external, 'shutdown') as external_close, \\
                 patch.object(external, 'force_flush') as external_flush, \\
                 patch.object(telemetry, '_build_provider', side_effect=providers), \\
                 patch.object(handler, 'close', wraps=handler.close) as handler_close:
                try:
                    telemetry.configure_telemetry()
                except RuntimeError as error:
                    assert 'external trace provider' in str(error)
                else:
                    raise AssertionError('external provider was overwritten')
                assert trace.get_tracer_provider() is external
                assert all(provider.shutdown.call_count == 1 for provider in providers)
                assert all(not provider.force_flush.called for provider in providers)
                handler_close.assert_called_once()
                telemetry.shutdown()
                external_close.assert_not_called()
                external_flush.assert_not_called()
            external.shutdown()
        """)

    def test_configured_otlp_error_propagates_without_console_fallback(self):
        self.run_process("""
            import os
            from unittest.mock import patch
            from opentelemetry.exporter.otlp.proto.grpc import trace_exporter
            from nlalpha.core import telemetry

            os.environ['OTEL_EXPORTER_OTLP_ENDPOINT'] = 'http://configured-collector:4317'
            with patch.object(trace_exporter, 'OTLPSpanExporter', side_effect=RuntimeError('invalid OTLP config')) as otlp, \\
                 patch.object(telemetry, '_ConsoleSpanExporter') as console:
                try:
                    telemetry.configure_telemetry()
                except RuntimeError as error:
                    assert str(error) == 'invalid OTLP config'
                else:
                    raise AssertionError('OTLP configuration error was hidden')
                otlp.assert_called_once_with(endpoint='http://configured-collector:4317')
                console.assert_not_called()
            try:
                telemetry.configure_telemetry()
            except RuntimeError:
                pass
            else:
                raise AssertionError('failed process configuration was retried')
        """)

    def test_only_complete_sdk_absence_permits_noop(self):
        self.run_process("""
            import importlib.util
            from unittest.mock import patch
            original = importlib.util.find_spec
            with patch.object(importlib.util, 'find_spec', side_effect=lambda name, *args, **kwargs:
                              None if name == 'opentelemetry.sdk' else original(name, *args, **kwargs)):
                from nlalpha.core import telemetry
            assert not telemetry.is_enabled()
            telemetry.configure_telemetry()
            with telemetry.start_span('optional-sdk-absent'):
                telemetry.get_meter().create_counter('optional-sdk-absent').add(1)
            assert telemetry.get_otel_log_handler() is None
            telemetry.shutdown()
        """)
        self.run_process("""
            import builtins
            from unittest.mock import patch
            original = builtins.__import__
            def load(name, *args, **kwargs):
                if name == 'opentelemetry.sdk.metrics':
                    raise ImportError('broken SDK internal dependency')
                return original(name, *args, **kwargs)
            with patch.object(builtins, '__import__', side_effect=load):
                try:
                    from nlalpha.core import telemetry
                except ImportError as error:
                    assert str(error) == 'broken SDK internal dependency'
                else:
                    raise AssertionError('broken installed SDK was treated as absent')
        """)

    def test_explicit_otlp_configuration_requires_the_optional_sdk(self):
        for endpoint in (
            "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        ):
            with self.subTest(endpoint=endpoint):
                self.run_process(f"""
                    import importlib.util
                    import os
                    from unittest.mock import patch
                    original = importlib.util.find_spec
                    with patch.object(importlib.util, 'find_spec', side_effect=lambda name, *args, **kwargs:
                                      None if name == 'opentelemetry.sdk' else original(name, *args, **kwargs)):
                        from nlalpha.core import telemetry
                    os.environ[{endpoint!r}] = 'http://configured-collector:4317'
                    try:
                        telemetry.configure_telemetry()
                    except RuntimeError as error:
                        assert 'OpenTelemetry SDK' in str(error)
                        assert 'nlalpha-core[telemetry]' in str(error)
                    else:
                        raise AssertionError('explicit OTLP configuration was discarded')
                """)

    def test_pytest_closes_owned_signals_before_capture_and_reports_cleanup_failure(self):
        lifecycle_hook = (Path(__file__).resolve().parents[2] / "conftest.py").read_text()
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory(prefix="nlalpha-telemetry-pytest-") as temporary:
                directory = Path(temporary)
                marker = directory / "closed.txt"
                startup = f'''
def pytest_sessionstart(session):
    from pathlib import Path
    from nlalpha.core import telemetry
    telemetry.configure_telemetry()
    providers = [telemetry._trace.get_tracer_provider(), telemetry._metrics.get_meter_provider(),
                 telemetry._logs.get_logger_provider()]
    for index, provider in enumerate(providers):
        original_close = provider.shutdown
        def close(*args, _index=index, _original=original_close, **kwargs):
            assert not sys.stderr.closed
            with Path({str(marker)!r}).open('a') as output:
                output.write(str(_index))
            return _original(*args, **kwargs)
        provider.shutdown = close
    if {failure!r}:
        def fail_flush(**kwargs):
            raise RuntimeError('session telemetry flush failed')
        providers[0].force_flush = fail_flush
'''
                scripts = directory / "scripts"
                scripts.mkdir()
                gate = Path(__file__).resolve().parents[2] / "scripts/nlalpha_pytest_gate.py"
                (scripts / "nlalpha_pytest_gate.py").write_text(gate.read_text())
                (directory / "conftest.py").write_text(lifecycle_hook + startup)
                (directory / "test_probe.py").write_text(textwrap.dedent('''
                    def test_probe():
                        from nlalpha.core import telemetry
                        with telemetry.start_span('pytest-process-probe'):
                            telemetry.get_meter().create_counter('pytest_process_probe').add(1)
                '''))
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", str(directory)], cwd=directory,
                    capture_output=True, text=True, timeout=30,
                )
                output = result.stdout + result.stderr
                self.assertEqual(marker.read_text(), "012", output)
                self.assertNotIn("I/O operation on closed file", output)
                if failure:
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn("session telemetry flush failed", output)
                else:
                    self.assertEqual(result.returncode, 0, output)
