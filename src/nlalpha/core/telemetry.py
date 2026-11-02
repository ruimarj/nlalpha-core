"""Provide lazy instrumentation and explicitly owned process telemetry resources."""

from __future__ import annotations

import atexit
import functools
import importlib.util
import inspect
import logging
import os
import sys
import threading
from contextlib import contextmanager
from importlib.metadata import version
from typing import Any, Callable, Generator, TypeVar

logger = logging.getLogger("nlalpha.telemetry")


def _sdk_installed() -> bool:
    """Detect whether the optional SDK distribution is present."""
    try:
        return importlib.util.find_spec("opentelemetry.sdk") is not None
    except ModuleNotFoundError as exc:
        if exc.name != "opentelemetry":
            raise
        return False


_OTEL_TRACE_AVAILABLE = _sdk_installed()
_OTEL_METRICS_AVAILABLE = _OTEL_TRACE_AVAILABLE
_OTEL_LOGS_AVAILABLE = _OTEL_TRACE_AVAILABLE

if _OTEL_TRACE_AVAILABLE:
    from opentelemetry import metrics as _metrics
    from opentelemetry import _logs
    from opentelemetry import trace as _trace
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
        ConsoleSpanExporter as _ConsoleSpanExporter,
    )
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

    from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter as _ConsoleMetricExporter,
        PeriodicExportingMetricReader as _PeriodicExportingMetricReader,
    )

    from opentelemetry.sdk._logs import LoggerProvider as _LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor as _BatchLogRecordProcessor
    from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter as _ConsoleLogExporter

    from opentelemetry.sdk.resources import Resource as _Resource


_UNSET = object()
_lock = threading.RLock()
_resource: Any = None
_tracer: Any = _UNSET
_meter: Any = _UNSET
_otel_log_handler: Any = _UNSET
_owned_providers: dict[str, Any] = {}
_configured = False
_closed = False
_atexit_registered = False


def _instrumentation_version() -> str:
    """Read the installed core distribution's instrumentation version."""
    return version("nlalpha-core")


def _get_resource() -> Any:
    """Create the resource shared by explicitly configured SDK providers."""
    global _resource
    if _resource is None:
        _resource = _Resource.create({
            "service.name": os.getenv("OTEL_SERVICE_NAME", "nlalpha"),
            "service.version": _instrumentation_version(),
            "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENV", "development"),
        })
    return _resource


def _create_otlp_span_exporter() -> Any:
    """Create the trace exporter selected by its configured OTLP endpoint."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    return OTLPSpanExporter(endpoint=endpoint)


def _create_otlp_metric_exporter() -> Any:
    """Create the metric exporter selected by its configured OTLP endpoint."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    return OTLPMetricExporter(endpoint=endpoint)


def _create_otlp_log_exporter() -> Any:
    """Create the log exporter selected by its configured OTLP endpoint."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
    return OTLPLogExporter(endpoint=endpoint)


def _build_provider(signal: str) -> Any:
    """Construct one SDK provider and transfer exporter ownership into it."""
    resource = _get_resource()
    if signal == "metrics":
        exporter = _create_otlp_metric_exporter()
        if exporter is None:
            exporter = _ConsoleMetricExporter(out=sys.stderr)
        try:
            reader = _PeriodicExportingMetricReader(exporter)
        except BaseException:
            exporter.shutdown()
            raise
        try:
            return _MeterProvider(resource=resource, metric_readers=[reader], shutdown_on_exit=False)
        except BaseException:
            reader.shutdown()
            raise

    provider_type, exporter_factory, console_type, processor_type = {
        "trace": (_TracerProvider, _create_otlp_span_exporter, _ConsoleSpanExporter, _BatchSpanProcessor),
        "logs": (_LoggerProvider, _create_otlp_log_exporter, _ConsoleLogExporter, _BatchLogRecordProcessor),
    }[signal]
    provider = provider_type(resource=resource, shutdown_on_exit=False)
    try:
        exporter = exporter_factory()
        if exporter is None:
            exporter = console_type(out=sys.stderr)
        try:
            processor = processor_type(exporter)
        except BaseException:
            exporter.shutdown()
            raise
        try:
            if signal == "trace":
                provider.add_span_processor(processor)
            else:
                provider.add_log_record_processor(processor)
        except BaseException:
            processor.shutdown()
            raise
    except BaseException:
        provider.shutdown()
        raise
    return provider


def _require_open() -> None:
    """Reject instrumentation after the process telemetry lifecycle has ended."""
    if _closed:
        raise RuntimeError("process telemetry has been shut down")


def _timeout(timeout_millis: int) -> None:
    """Validate a positive integer export timeout."""
    if isinstance(timeout_millis, bool) or not isinstance(timeout_millis, int) or timeout_millis <= 0:
        raise ValueError("timeout_millis must be a positive integer")


def _close_provider(signal: str, provider: Any, timeout_millis: int) -> None:
    """Close a provider through its signal's SDK lifecycle interface."""
    if signal == "metrics":
        provider.shutdown(timeout_millis=timeout_millis)
    else:
        provider.shutdown()


def configure_telemetry() -> None:
    """Install SDK providers owned by this standalone process. Configuration failures are terminal."""
    global _configured, _closed, _atexit_registered, _tracer, _meter
    with _lock:
        _require_open()
        if _configured:
            return
        if not _OTEL_TRACE_AVAILABLE:
            if any(os.getenv(name) for name in (
                "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
            )):
                _closed = True
                raise RuntimeError("OTLP export requires the OpenTelemetry SDK; install nlalpha-core[telemetry]")
            return
        candidates: dict[str, Any] = {}
        try:
            for signal in ("trace", "metrics", "logs"):
                candidates[signal] = _build_provider(signal)
            interfaces = {
                "trace": (_trace.set_tracer_provider, _trace.get_tracer_provider),
                "metrics": (_metrics.set_meter_provider, _metrics.get_meter_provider),
                "logs": (_logs.set_logger_provider, _logs.get_logger_provider),
            }
            for signal, provider in candidates.items():
                setter, getter = interfaces[signal]
                setter(provider)
                if getter() is not provider:
                    raise RuntimeError(f"an external {signal} provider is already configured")
        except BaseException as exc:
            _closed = True
            errors = [exc, *_close_handler()]
            for signal, provider in candidates.items():
                try:
                    _close_provider(signal, provider, 30000)
                except BaseException as cleanup_error:
                    cleanup_error.add_note(f"closing telemetry candidate: {signal}")
                    errors.append(cleanup_error)
            if len(errors) > 1:
                raise BaseExceptionGroup("telemetry configuration and cleanup failed", errors)
            raise
        _owned_providers.update(candidates)
        _tracer = _meter = _UNSET
        _configured = True
        if not _atexit_registered:
            atexit.register(shutdown)
            _atexit_registered = True


def _flush_owned(timeout_millis: int) -> list[BaseException]:
    """Flush every owned signal while collecting independent failures."""
    errors = []
    for signal, provider in _owned_providers.items():
        try:
            if provider.force_flush(timeout_millis=timeout_millis) is False:
                raise TimeoutError(f"{signal} telemetry flush timed out")
        except BaseException as exc:
            exc.add_note(f"flushing telemetry signal: {signal}")
            errors.append(exc)
    return errors


def force_flush(timeout_millis: int = 30000) -> bool:
    """Flush all process-owned signals and report every export failure."""
    _timeout(timeout_millis)
    with _lock:
        errors = _flush_owned(timeout_millis)
        if errors:
            raise BaseExceptionGroup("telemetry flush failed", errors)
        return True


def _close_handler() -> list[BaseException]:
    """Detach and close the module's handler throughout the logging hierarchy."""
    errors = []
    if _otel_log_handler is _UNSET or _otel_log_handler is None:
        return errors
    targets = [logging.getLogger(), *logging.Logger.manager.loggerDict.copy().values()]
    for target in targets:
        if isinstance(target, logging.Logger):
            try:
                target.removeHandler(_otel_log_handler)
            except BaseException as exc:
                exc.add_note(f"detaching telemetry handler: {target.name}")
                errors.append(exc)
    try:
        _otel_log_handler.close()
    except BaseException as exc:
        errors.append(exc)
    return errors


def shutdown(timeout_millis: int = 30000) -> None:
    """Detach the module's handler and close every process-owned signal exactly once."""
    global _closed
    _timeout(timeout_millis)
    with _lock:
        if _closed:
            return
        _closed = True
        errors = _close_handler()
        errors.extend(_flush_owned(timeout_millis))
        for signal, provider in _owned_providers.items():
            try:
                _close_provider(signal, provider, timeout_millis)
            except BaseException as exc:
                exc.add_note(f"closing telemetry signal: {signal}")
                errors.append(exc)
        _owned_providers.clear()
        if errors:
            raise BaseExceptionGroup("telemetry shutdown failed", errors)


class _NoOpTracer:
    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any:
        from contextlib import nullcontext

        return nullcontext(_NoOpSpan())


class _NoOpSpan:
    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def record_exception(self, exception: BaseException, **kwargs: Any) -> None:
        pass

    def end(self) -> None:
        pass


class _NoOpMeter:
    def create_counter(self, name: str, **kwargs: Any) -> _NoOpCounter:
        return _NoOpCounter()

    def create_histogram(self, name: str, **kwargs: Any) -> _NoOpHistogram:
        return _NoOpHistogram()


class _NoOpCounter:
    def add(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        pass


class _NoOpHistogram:
    def record(self, amount: float, attributes: dict[str, Any] | None = None) -> None:
        pass


if _OTEL_LOGS_AVAILABLE:
    class _TelemetryLoggingHandler(LoggingHandler):
        """Retain SDK handler semantics throughout its explicit open and closed lifecycle."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._lifecycle_lock = threading.RLock()
            self._telemetry_closed = False
            super().__init__(*args, **kwargs)

        def flush(self) -> None:
            """Flush live handlers through the SDK's supported interface."""
            with self._lifecycle_lock:
                if not self._telemetry_closed:
                    super().flush()

        def close(self) -> None:
            """Mark the handler closed before releasing its logging resources."""
            with self._lifecycle_lock:
                if not self._telemetry_closed:
                    self._telemetry_closed = True
                    super().close()


F = TypeVar("F", bound=Callable[..., Any])


def get_tracer() -> Any:
    """Lazily obtain instrumentation from the host's current global tracer provider."""
    global _tracer
    with _lock:
        _require_open()
        if _tracer is _UNSET:
            _tracer = _trace.get_tracer("nlalpha", _instrumentation_version()) if _OTEL_TRACE_AVAILABLE else _NoOpTracer()
        return _tracer


def get_meter() -> Any:
    """Lazily obtain instrumentation from the host's current global meter provider."""
    global _meter
    with _lock:
        _require_open()
        if _meter is _UNSET:
            _meter = _metrics.get_meter("nlalpha", _instrumentation_version()) if _OTEL_METRICS_AVAILABLE else _NoOpMeter()
        return _meter


def get_otel_log_handler() -> Any:
    """Lazily create a handler bound to the host's current global log provider."""
    global _otel_log_handler
    with _lock:
        _require_open()
        if _otel_log_handler is _UNSET:
            _otel_log_handler = _TelemetryLoggingHandler(logger_provider=_logs.get_logger_provider()) if _OTEL_LOGS_AVAILABLE else None
        return _otel_log_handler


@contextmanager
def start_span(
    name: str,
    kind: Any = None,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Start a span as a context manager."""
    kwargs: dict[str, Any] = {}
    if kind is not None:
        kwargs["kind"] = kind
    if attributes:
        kwargs["attributes"] = attributes

    with get_tracer().start_as_current_span(name, **kwargs) as span:
        yield span


def span(name: str | None = None) -> Callable[[F], F]:
    """Decorator to wrap a function with a span."""

    def decorator(func: F) -> F:
        span_name = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with start_span(span_name) as s:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if _OTEL_TRACE_AVAILABLE:
                        s.record_exception(exc)
                    raise

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with start_span(span_name) as s:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if _OTEL_TRACE_AVAILABLE:
                        s.record_exception(exc)
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return wrapper  # type: ignore[return-value]

    return decorator


# 分布式追踪上下文传播

def inject_traceparent() -> str | None:
    """Extract the current traceparent string for propagation."""
    if not _OTEL_TRACE_AVAILABLE:
        return None
    current_span = _trace.get_current_span()
    if not current_span or not current_span.get_span_context().is_valid:
        return None
    ctx = current_span.get_span_context()
    trace_id = format(ctx.trace_id, "032x")
    span_id = format(ctx.span_id, "016x")
    flags = "01" if ctx.trace_flags & TraceFlags.SAMPLED else "00"
    return f"00-{trace_id}-{span_id}-{flags}"


def extract_traceparent(traceparent: str | None) -> Any:
    """Build a Context from a traceparent string."""
    if not _OTEL_TRACE_AVAILABLE or not traceparent:
        return None

    parts = traceparent.split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None

    try:
        trace_id = int(parts[1], 16)
        span_id = int(parts[2], 16)
        flags = int(parts[3], 16)
    except ValueError:
        return None

    span_ctx = SpanContext(
        trace_id=trace_id,
        span_id=span_id,
        is_remote=True,
        trace_flags=TraceFlags(flags),
    )
    return set_span_in_context(NonRecordingSpan(span_ctx))


def is_enabled() -> bool:
    """Report whether the optional tracing SDK is installed."""
    return _OTEL_TRACE_AVAILABLE


def is_metrics_enabled() -> bool:
    """Report whether the optional metrics SDK is installed."""
    return _OTEL_METRICS_AVAILABLE


def is_logs_enabled() -> bool:
    """Report whether the optional logging SDK is installed."""
    return _OTEL_LOGS_AVAILABLE


# 统一日志入口：将 OTel LoggingHandler 挂载到根 logger

def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    """Configure root logger with formatter and attach OTel handler."""
    with _lock:
        _require_open()
        _ensure_root_logging_configured(level, json_format)
        _attach_otel_log_handler()


_SILENCE_LOGGERS = (
    "httpx", "httpcore", "openai", "urllib3",
    "asyncio", "boto3", "botocore",
)


def _create_formatter(json_format: bool = False) -> logging.Formatter:
    """Create text or JSON formatter. Falls back to text if python-json-logger missing."""
    if json_format:
        try:
            from pythonjsonlogger.json import JsonFormatter
            return JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(otelTraceID)s %(otelSpanID)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        except ImportError:
            logger.warning("python-json-logger not installed, falling back to text format")
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _ensure_root_logging_configured(level: str, json_format: bool = False) -> None:
    """Ensure root logger has handler and correct formatter."""
    root = logging.getLogger()
    lvl = _resolve_log_level(level)
    root.setLevel(lvl)

    formatter = _create_formatter(json_format)

    import sys as _sys
    if not root.handlers:
        handler = logging.StreamHandler(_sys.stderr)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setFormatter(formatter)  # 替换已有 handler 的 formatter

    for noisy in _SILENCE_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _attach_otel_log_handler() -> None:
    """Attach OTel LoggingHandler to root logger if OTel is available."""
    with _lock:
        otel_handler = get_otel_log_handler()
        if otel_handler is None:
            return
        root = logging.getLogger()
        if any(isinstance(handler, LoggingHandler) for handler in root.handlers):
            return
        otel_handler.setLevel(logging.NOTSET)
        root.addHandler(otel_handler)
        logger.info("OTel LoggingHandler attached | trace-log correlation enabled")


def _resolve_log_level(raw: str) -> int:
    raw_upper = raw.upper()
    numeric = getattr(logging, raw_upper, None)
    if isinstance(numeric, int):
        return numeric
    try:
        return int(raw_upper)
    except ValueError:
        return logging.INFO
