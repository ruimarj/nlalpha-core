"""OpenTelemetry observability utilities — unified entrypoint for tracing, metrics, and logs.

Zero-intrusion: gracefully degrades to NoOp when opentelemetry is absent.
"""

from __future__ import annotations

import functools
import logging
import os
from contextlib import contextmanager
from typing import Any, Callable, Generator, TypeVar
import inspect

logger = logging.getLogger("nlalpha.telemetry")

# Graceful import fallback

try:
    from opentelemetry import trace as _trace
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    import sys
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor as _BatchSpanProcessor,
        ConsoleSpanExporter as _ConsoleSpanExporter,
    )
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

    _OTEL_TRACE_AVAILABLE = True
except ImportError:
    _OTEL_TRACE_AVAILABLE = False
    logger.debug("opentelemetry trace SDK not installed; tracing disabled")

try:
    from opentelemetry.sdk.metrics import MeterProvider as _MeterProvider
    import sys
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter as _ConsoleMetricExporter,
        PeriodicExportingMetricReader as _PeriodicExportingMetricReader,
    )

    _OTEL_METRICS_AVAILABLE = True
except ImportError:
    _OTEL_METRICS_AVAILABLE = False
    logger.debug("opentelemetry metrics SDK not installed; metrics disabled")

try:
    from opentelemetry.sdk._logs import LoggerProvider as _LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor as _BatchLogRecordProcessor
    from opentelemetry.sdk._logs.export import ConsoleLogRecordExporter as _ConsoleLogExporter

    _OTEL_LOGS_AVAILABLE = True
except ImportError:
    _OTEL_LOGS_AVAILABLE = False
    logger.debug("opentelemetry logs SDK not installed; log correlation disabled")

try:
    from opentelemetry.sdk.resources import Resource as _Resource

    _OTEL_RESOURCE_AVAILABLE = True
except ImportError:
    _OTEL_RESOURCE_AVAILABLE = False


import asyncio


# Resource initialization

_RESOURCE: Any = None


def _get_resource() -> Any:
    """Get or create the shared Resource."""
    global _RESOURCE
    if _RESOURCE is not None:
        return _RESOURCE

    if not _OTEL_RESOURCE_AVAILABLE:
        return None

    version = "0.0.0"
    try:
        version = __import__("nlalpha").__version__
    except Exception:
        pass

    _RESOURCE = _Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "nlalpha"),
            "service.version": version,
            "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENV", "development"),
        }
    )
    return _RESOURCE


# OTLP exporter factory

def _create_otlp_span_exporter() -> Any:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    return OTLPSpanExporter(endpoint=endpoint) if endpoint else None


def _create_otlp_metric_exporter() -> Any:
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    return OTLPMetricExporter(endpoint=endpoint) if endpoint else None


def _create_otlp_log_exporter() -> Any:
    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    return OTLPLogExporter(endpoint=endpoint) if endpoint else None


# Tracer initialization

def _init_tracer() -> Any:
    if not _OTEL_TRACE_AVAILABLE:
        return _NoOpTracer()

    resource = _get_resource()
    provider = _TracerProvider(resource=resource) if resource else _TracerProvider()

    # Exporter selection: OTLP > Console
    otlp_exporter = _create_otlp_span_exporter()
    if otlp_exporter is not None:
        provider.add_span_processor(_BatchSpanProcessor(otlp_exporter))
        logger.info("OTLP trace exporter enabled | endpoint=%s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    else:
        provider.add_span_processor(_BatchSpanProcessor(_ConsoleSpanExporter(out=sys.stderr)))

    _trace.set_tracer_provider(provider)

    version = "0.0.0"
    try:
        version = __import__("nlalpha").__version__
    except Exception:
        pass
    return _trace.get_tracer("nlalpha", version)


# Meter initialization

def _init_meter() -> Any:
    if not _OTEL_METRICS_AVAILABLE:
        return _NoOpMeter()

    resource = _get_resource()
    readers = []

    otlp_exporter = _create_otlp_metric_exporter()
    if otlp_exporter is not None:
        readers.append(_PeriodicExportingMetricReader(otlp_exporter))
        logger.info("OTLP metric exporter enabled | endpoint=%s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    else:
        readers.append(_PeriodicExportingMetricReader(_ConsoleMetricExporter(out=sys.stderr)))

    provider = _MeterProvider(resource=resource, metric_readers=readers) if resource else _MeterProvider(metric_readers=readers)
    from opentelemetry.metrics import set_meter_provider
    set_meter_provider(provider)

    version = "0.0.0"
    try:
        version = __import__("nlalpha").__version__
    except Exception:
        pass
    return provider.get_meter("nlalpha", version)


# Logger initialization (OTel LoggingHandler for trace-log correlation)

def _init_otel_log_handler() -> Any:
    """Initialize OpenTelemetry LoggingHandler for trace-log correlation.

    Returns a LoggingHandler that injects trace_id/span_id into log records,
    or None if OTel logs SDK is unavailable.
    """
    if not _OTEL_LOGS_AVAILABLE:
        return None

    resource = _get_resource()
    provider = _LoggerProvider(resource=resource) if resource else _LoggerProvider()

    otlp_exporter = _create_otlp_log_exporter()
    if otlp_exporter is not None:
        provider.add_log_record_processor(_BatchLogRecordProcessor(otlp_exporter))
        logger.info("OTLP log exporter enabled | endpoint=%s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    else:
        provider.add_log_record_processor(_BatchLogRecordProcessor(_ConsoleLogExporter(out=sys.stderr)))

    return LoggingHandler(logger_provider=provider)


# No-op implementations

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


# Global instances (lazy init on first access)

_tracer = _init_tracer()
_meter = _init_meter()
_otel_log_handler = _init_otel_log_handler()


# Public API

F = TypeVar("F", bound=Callable[..., Any])


def get_tracer() -> Any:
    """Return the global tracer instance."""
    return _tracer


def get_meter() -> Any:
    """Return the global meter instance."""
    return _meter


def get_otel_log_handler() -> Any:
    """Return the OpenTelemetry LoggingHandler for trace-log correlation.

    Attach this handler to any logger to automatically inject trace_id/span_id.
    """
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

    with _tracer.start_as_current_span(name, **kwargs) as span:
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


# Traceparent propagation helpers

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
    """Return True if OpenTelemetry tracing is active."""
    return _OTEL_TRACE_AVAILABLE


def is_metrics_enabled() -> bool:
    """Return True if OpenTelemetry metrics is active."""
    return _OTEL_METRICS_AVAILABLE


def is_logs_enabled() -> bool:
    """Return True if OpenTelemetry logs is active."""
    return _OTEL_LOGS_AVAILABLE


# 统一日志入口：将 OTel LoggingHandler 挂载到根 logger

def setup_logging(level: str = "INFO") -> None:
    """Configure Python stdlib logging and attach OTel LoggingHandler."""
    _ensure_root_logging_configured(level)
    _attach_otel_log_handler()


_SILENCE_LOGGERS = (
    "httpx", "httpcore", "openai", "urllib3",
    "asyncio", "boto3", "botocore",
)


def _ensure_root_logging_configured(level: str) -> None:
    """Ensure root logger has at least one StreamHandler to avoid "No handler" warnings."""
    root = logging.getLogger()
    if root.handlers:
        return

    lvl = _resolve_log_level(level)
    root.setLevel(lvl)

    import sys as _sys
    handler = logging.StreamHandler(_sys.stderr)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root.addHandler(handler)

    for noisy in _SILENCE_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _attach_otel_log_handler() -> None:
    """Attach OTel LoggingHandler to root logger if OTel is available."""
    if _otel_log_handler is None:
        return

    root = logging.getLogger()
    if any(isinstance(h, LoggingHandler) for h in root.handlers):
        return

    otel_handler = _otel_log_handler
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
