"""Telemetry adapters with an optional OpenTelemetry implementation."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext, suppress
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Literal, Protocol
from urllib.parse import unquote

from docs.domain.contracts import Passport

from .passport import passport_metrics
from .redaction import redact_attributes, redact_signal_name, redact_text

Attributes = Mapping[str, Any] | None
IncrementHook = Callable[[str, float, dict[str, Any]], None]
ObserveHook = Callable[[str, float, dict[str, Any]], None]
LogHook = Callable[[str, dict[str, Any]], None]
SpanHook = Callable[[str, dict[str, Any]], AbstractContextManager[Any] | None]
ModuleLoader = Callable[[str], Any]

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_PROTOCOLS = frozenset({"grpc", "http/protobuf"})
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


@dataclass(frozen=True, slots=True, repr=False)
class TelemetryConfig:
    """Immutable, secret-safe production telemetry configuration."""

    enabled: bool = False
    service_name: str = "docs"
    endpoint: str | None = None
    protocol: Literal["grpc", "http/protobuf"] | None = None
    headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> TelemetryConfig:
        """Parse supported DOCS_OTEL_* variables without raising."""
        source = os.environ if environ is None else environ
        service_name = source.get("DOCS_OTEL_SERVICE_NAME", "docs").strip() or "docs"
        endpoint = source.get("DOCS_OTEL_EXPORTER_OTLP_ENDPOINT", "").strip() or None
        raw_protocol = source.get("DOCS_OTEL_EXPORTER_OTLP_PROTOCOL", "").strip().lower()
        protocol: Literal["grpc", "http/protobuf"] | None = None
        if not raw_protocol and endpoint is not None:
            protocol = "grpc"
        elif raw_protocol in _PROTOCOLS:
            protocol = raw_protocol  # type: ignore[assignment]
        return cls(
            enabled=source.get("DOCS_OTEL_ENABLED", "").strip().lower() in _TRUTHY,
            service_name=service_name,
            endpoint=endpoint,
            protocol=protocol,
            headers=_parse_headers(source.get("DOCS_OTEL_EXPORTER_OTLP_HEADERS", "")),
        )

    def __repr__(self) -> str:
        endpoint = "<configured>" if self.endpoint is not None else "None"
        headers = f"<redacted:{len(self.headers)}>" if self.headers else "()"
        return (
            "TelemetryConfig("
            f"enabled={self.enabled!r}, service_name={self.service_name!r}, "
            f"endpoint={endpoint}, protocol={self.protocol!r}, headers={headers})"
        )


def _parse_headers(value: str) -> tuple[tuple[str, str], ...]:
    headers: dict[str, str] = {}
    for item in value.split(","):
        encoded_key, separator, encoded_value = item.partition("=")
        encoded_key = encoded_key.strip()
        encoded_value = encoded_value.strip()
        if not separator or not encoded_key or not encoded_value:
            continue
        if _INVALID_PERCENT_ESCAPE.search(encoded_key) or _INVALID_PERCENT_ESCAPE.search(encoded_value):
            continue
        try:
            key = unquote(encoded_key, errors="strict").strip()
            header_value = unquote(encoded_value, errors="strict").strip()
        except (UnicodeDecodeError, ValueError):
            continue
        if key and header_value:
            headers[key] = header_value
    return tuple(headers.items())


class ObservabilityPort(Protocol):
    def increment(self, name: str, value: float = 1, attributes: Attributes = None) -> None: ...
    def observe(self, name: str, value: float, attributes: Attributes = None) -> None: ...
    def span(self, name: str, attributes: Attributes = None) -> AbstractContextManager[Any]: ...
    def log(self, message: str, attributes: Attributes = None) -> None: ...
    def record_passport(self, passport: Passport) -> None: ...


class NoOpObservability:
    """Safe fallback used when telemetry is disabled or unavailable."""

    def increment(self, name: str, value: float = 1, attributes: Attributes = None) -> None:
        del name, value, attributes

    def observe(self, name: str, value: float, attributes: Attributes = None) -> None:
        del name, value, attributes

    def span(self, name: str, attributes: Attributes = None) -> AbstractContextManager[Any]:
        del name, attributes
        return nullcontext()

    def log(self, message: str, attributes: Attributes = None) -> None:
        del message, attributes

    def record_passport(self, passport: Passport) -> None:
        del passport


class Observability(NoOpObservability):
    """Small signal boundary; hooks make the unit testable and embeddable."""

    def __init__(
        self,
        *,
        increment_hook: IncrementHook | None = None,
        observe_hook: ObserveHook | None = None,
        span_hook: SpanHook | None = None,
        log_hook: LogHook | None = None,
    ) -> None:
        self._increment_hook = increment_hook
        self._observe_hook = observe_hook
        self._span_hook = span_hook
        self._log_hook = log_hook

    def increment(self, name: str, value: float = 1, attributes: Attributes = None) -> None:
        with suppress(Exception):
            if self._increment_hook is not None:
                self._increment_hook(redact_signal_name(name), value, redact_attributes(attributes))

    def observe(self, name: str, value: float, attributes: Attributes = None) -> None:
        with suppress(Exception):
            if self._observe_hook is not None:
                self._observe_hook(redact_signal_name(name), value, redact_attributes(attributes))

    def span(self, name: str, attributes: Attributes = None) -> AbstractContextManager[Any]:
        try:
            if self._span_hook is None:
                return nullcontext()
            context = self._span_hook(redact_signal_name(name), redact_attributes(attributes))
            return _FailOpenSpan(context) if context is not None else nullcontext()
        except Exception:
            return nullcontext()

    def log(self, message: str, attributes: Attributes = None) -> None:
        with suppress(Exception):
            if self._log_hook is not None:
                self._log_hook(redact_text(message), redact_attributes(attributes))

    def record_passport(self, passport: Passport) -> None:
        with suppress(Exception):
            for name, value in passport_metrics(passport).items():
                self.increment(f"docs.{name}", value)


def create_observability(*, enabled: bool = True, service_name: str = "docs") -> ObservabilityPort:
    """Create an OpenTelemetry-backed adapter, or a no-op when unavailable."""
    if not enabled:
        return NoOpObservability()
    try:
        from opentelemetry import metrics, trace  # type: ignore[import-not-found]
    except Exception:
        return NoOpObservability()

    try:
        meter = metrics.get_meter(service_name)
        tracer = trace.get_tracer(service_name)
    except Exception:
        return NoOpObservability()
    logs_api: Any | None
    try:
        from opentelemetry import _logs  # type: ignore[import-not-found]

        logs_api = _logs
    except Exception:
        logs_api = None
    return _create_observability_adapter(
        service_name=service_name,
        metrics_api=metrics,
        trace_api=trace,
        logs_api=logs_api,
        meter=meter,
        tracer=tracer,
    )


def create_observability_from_env(
    *,
    environ: Mapping[str, str] | None = None,
    module_loader: ModuleLoader | None = None,
) -> ObservabilityPort:
    """Configure explicitly enabled OTLP exporters, otherwise return a no-op."""
    config = TelemetryConfig.from_env(environ)
    if not config.enabled or config.endpoint is None or config.protocol is None:
        return NoOpObservability()

    load = import_module if module_loader is None else module_loader
    exporter_protocol = "http" if config.protocol == "http/protobuf" else "grpc"
    exporter_prefix = f"opentelemetry.exporter.otlp.proto.{exporter_protocol}"
    try:
        metrics_api = load("opentelemetry.metrics")
        trace_api = load("opentelemetry.trace")
        resources = load("opentelemetry.sdk.resources")
        trace_sdk = load("opentelemetry.sdk.trace")
        trace_export = load("opentelemetry.sdk.trace.export")
        metrics_sdk = load("opentelemetry.sdk.metrics")
        metrics_export = load("opentelemetry.sdk.metrics.export")
        span_exporter_module = load(f"{exporter_prefix}.trace_exporter")
        metric_exporter_module = load(f"{exporter_prefix}.metric_exporter")

        resource = resources.Resource.create({"service.name": config.service_name})
        span_exporter = span_exporter_module.OTLPSpanExporter(**_exporter_options(config, "traces"))
        metric_exporter = metric_exporter_module.OTLPMetricExporter(**_exporter_options(config, "metrics"))
        tracer_provider = trace_sdk.TracerProvider(resource=resource)
        tracer_provider.add_span_processor(trace_export.BatchSpanProcessor(span_exporter))
        metric_reader = metrics_export.PeriodicExportingMetricReader(metric_exporter)
        meter_provider = metrics_sdk.MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
        )
    except Exception:
        return NoOpObservability()

    logs_api, logger_provider = _build_logs_provider(
        load=load,
        exporter_prefix=exporter_prefix,
        resource=resource,
        exporter_options=_exporter_options(config, "logs"),
    )
    try:
        trace_api.set_tracer_provider(tracer_provider)
        metrics_api.set_meter_provider(meter_provider)
    except Exception:
        return NoOpObservability()
    if logs_api is not None and logger_provider is not None:
        try:
            logs_api.set_logger_provider(logger_provider)
        except Exception:
            logs_api = None

    try:
        meter = metrics_api.get_meter(config.service_name)
        tracer = trace_api.get_tracer(config.service_name)
    except Exception:
        return NoOpObservability()
    return _create_observability_adapter(
        service_name=config.service_name,
        metrics_api=metrics_api,
        trace_api=trace_api,
        logs_api=logs_api,
        meter=meter,
        tracer=tracer,
    )


def _exporter_options(config: TelemetryConfig, signal: str) -> dict[str, Any]:
    endpoint = config.endpoint
    if endpoint is None:
        raise ValueError("OTLP endpoint is required")
    if config.protocol == "http/protobuf":
        endpoint = f"{endpoint.rstrip('/')}/v1/{signal}"
    return {"endpoint": endpoint, "headers": dict(config.headers)}


def _build_logs_provider(
    *,
    load: ModuleLoader,
    exporter_prefix: str,
    resource: Any,
    exporter_options: dict[str, Any],
) -> tuple[Any | None, Any | None]:
    try:
        logs_api = load("opentelemetry._logs")
        logs_sdk = load("opentelemetry.sdk._logs")
        logs_export = load("opentelemetry.sdk._logs.export")
        log_exporter_module = load(f"{exporter_prefix}._log_exporter")
        log_exporter = log_exporter_module.OTLPLogExporter(**exporter_options)
        logger_provider = logs_sdk.LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(logs_export.BatchLogRecordProcessor(log_exporter))
        return logs_api, logger_provider
    except Exception:
        return None, None


def _create_observability_adapter(
    *,
    service_name: str,
    metrics_api: Any,
    trace_api: Any,
    logs_api: Any | None,
    meter: Any,
    tracer: Any,
) -> ObservabilityPort:
    del metrics_api, trace_api
    logger: Any | None = None
    log_record: Any | None = None
    try:
        if logs_api is not None and logs_api.get_logger_provider() is not None:
            logger = logs_api.get_logger(service_name)
            log_record = logs_api.LogRecord
    except Exception:
        logger = None
        log_record = None
    counters: dict[str, Any] = {}
    histograms: dict[str, Any] = {}

    def increment(name: str, value: float, attributes: dict[str, Any]) -> None:
        counter = counters.get(name)
        if counter is None:
            counter = meter.create_counter(name)
            counters[name] = counter
        counter.add(value, attributes)

    def observe(name: str, value: float, attributes: dict[str, Any]) -> None:
        histogram = histograms.get(name)
        if histogram is None:
            histogram = meter.create_histogram(name)
            histograms[name] = histogram
        histogram.record(value, attributes)

    def span(name: str, attributes: dict[str, Any]) -> AbstractContextManager[Any]:
        return _OpenTelemetrySpan(tracer.start_as_current_span(name), attributes)

    def log(message: str, attributes: dict[str, Any]) -> None:
        if logger is not None and log_record is not None:
            logger.emit(log_record(body=message, attributes=attributes))

    return Observability(
        increment_hook=increment,
        observe_hook=observe,
        span_hook=span,
        log_hook=log if logger is not None and log_record is not None else None,
    )


class _OpenTelemetrySpan:
    def __init__(self, context: AbstractContextManager[Any], attributes: dict[str, Any]) -> None:
        self._context = context
        self._attributes = attributes

    def __enter__(self) -> Any:
        span = self._context.__enter__()
        span.set_attributes(self._attributes)
        return span

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool | None:
        return self._context.__exit__(exc_type, exc_value, traceback)


class _FailOpenSpan:
    def __init__(self, context: AbstractContextManager[Any]) -> None:
        self._context = context
        self._enter_attempted = False

    def __enter__(self) -> Any:
        self._enter_attempted = True
        try:
            return self._context.__enter__()
        except Exception as exc:
            with suppress(Exception):
                self._context.__exit__(type(exc), exc, exc.__traceback__)
            self._enter_attempted = False
            return None

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> Literal[False]:
        if self._enter_attempted:
            with suppress(Exception):
                self._context.__exit__(exc_type, exc_value, traceback)
            self._enter_attempted = False
        return False
