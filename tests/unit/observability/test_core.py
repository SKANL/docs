from __future__ import annotations

from types import SimpleNamespace

from docs.domain.contracts import Passport
from docs.observability import (
    NoOpObservability,
    Observability,
    TelemetryConfig,
    create_observability_from_env,
    passport_metrics,
    redact_attributes,
)
from docs.observability.core import create_observability


def test_redaction_removes_sensitive_values_and_keeps_low_cardinality_attributes():
    result = redact_attributes({"stage": "build-docx", "status": "ok", "run_id": "secret"})

    assert result == {"stage": "build-docx", "status": "ok"}


def test_passport_metrics_are_derived_without_run_or_artifact_identity_labels():
    passport = Passport(
        "run-123",
        entries=(
            {"artifact": "a", "kind": "source", "status": "accepted"},
            {"artifact": "b", "kind": "source", "status": "accepted"},
            {"artifact": "c", "kind": "output", "status": "failed"},
        ),
    )

    assert passport_metrics(passport) == {
        "passport.entries": 3,
        "passport.entries.accepted": 2,
        "passport.entries.failed": 1,
        "passport.kinds": 2,
    }


def test_noop_observability_is_safe_without_optional_dependencies():
    observability = NoOpObservability()

    observability.increment("docs.runs", 1, {"status": "ok"})
    observability.observe("docs.duration", 12.5, {"stage": "build"})
    with observability.span("docs.run", {"status": "ok"}):
        observability.log("run completed", {"run_id": "secret"})
    observability.record_passport(Passport("run-1", entries=({"status": "accepted"},)))


def test_observability_can_use_injected_hooks_without_leaking_redacted_values():
    increments: list[tuple[str, float, dict[str, str]]] = []
    logs: list[tuple[str, dict[str, str]]] = []
    observability = Observability(
        increment_hook=lambda name, value, attributes: increments.append((name, value, attributes)),
        log_hook=lambda message, attributes: logs.append((message, attributes)),
    )

    observability.increment("docs.runs", 1, {"status": "ok", "token": "secret"})
    observability.log("done", {"run_id": "run-1", "status": "ok"})

    assert increments == [("docs.runs", 1, {"status": "ok"})]
    assert logs == [("done", {"status": "ok"})]


def test_observability_hook_failures_are_fail_open():
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("telemetry unavailable")

    observability = Observability(
        increment_hook=fail,
        observe_hook=fail,
        log_hook=fail,
        span_hook=fail,
    )

    observability.increment("docs.runs")
    observability.observe("docs.duration", 1)
    observability.log("done")
    with observability.span("docs.run"):
        pass


def test_observability_bounds_and_redacts_signal_names_and_log_messages():
    events = []
    observability = Observability(
        increment_hook=lambda name, _value, _attrs: events.append(name),
        log_hook=lambda message, _attrs: events.append(message),
    )

    observability.increment("docs.token=secret")
    observability.log("token=secret " * 1000)

    assert all("secret" not in event for event in events)
    assert len(events[1]) <= 256


def test_redaction_drops_unbounded_strings_and_numbers():
    assert redact_attributes(
        {
            "stage": "tenant-secret-stage",
            "status": "ok",
            "reason": "a" * 10_000,
            "count": 10_000_001,
        }
    ) == {"status": "ok"}


def test_fail_open_span_exits_when_enter_fails_after_underlying_context_entry():
    closed = []

    class BrokenContext:
        def __enter__(self):
            raise RuntimeError("set_attributes failed")

        def __exit__(self, exc_type, exc_value, traceback):
            closed.append((exc_type, exc_value, traceback))
            return False

    with Observability(span_hook=lambda _name, _attrs: BrokenContext()).span("docs.run"):
        pass

    assert len(closed) == 1


def test_otel_setup_is_fail_open_for_non_import_setup_failure(monkeypatch):
    class BrokenImport:
        def __getattr__(self, _name):
            raise RuntimeError("broken optional telemetry")

    monkeypatch.setitem(__import__("sys").modules, "opentelemetry", BrokenImport())
    assert create_observability() is not None


def test_otelt_instruments_are_created_only_on_cache_miss(monkeypatch):
    class Meter:
        def __init__(self):
            self.created = 0

        def create_counter(self, _name):
            self.created += 1
            return type("C", (), {"add": lambda *_: None})()

        def create_histogram(self, _name):
            self.created += 1
            return type("H", (), {"record": lambda *_: None})()

    meter = Meter()
    module = type(
        "OTel",
        (),
        {
            "metrics": type("M", (), {"get_meter": staticmethod(lambda _n: meter)}),
            "trace": type("T", (), {"get_tracer": staticmethod(lambda _n: object())}),
        },
    )()
    monkeypatch.setitem(__import__("sys").modules, "opentelemetry", module)
    observability = create_observability()
    observability.increment("docs.one")
    observability.increment("docs.one")
    assert meter.created == 1


def test_telemetry_config_parses_environment_without_exposing_header_values():
    config = TelemetryConfig.from_env(
        {
            "DOCS_OTEL_ENABLED": "yes",
            "DOCS_OTEL_SERVICE_NAME": "document-worker",
            "DOCS_OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example/v1",
            "DOCS_OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "DOCS_OTEL_EXPORTER_OTLP_HEADERS": (
                "authorization=Bearer%20top-secret,x-tenant=docs%2Cprod,broken,no-key%ZZ=value"
            ),
        }
    )

    assert config.enabled is True
    assert config.service_name == "document-worker"
    assert config.endpoint == "https://collector.example/v1"
    assert config.protocol == "http/protobuf"
    assert config.headers == (
        ("authorization", "Bearer top-secret"),
        ("x-tenant", "docs,prod"),
    )
    assert "top-secret" not in repr(config)
    assert "docs,prod" not in repr(config)


def test_telemetry_config_defaults_to_disabled_and_rejects_unsupported_values():
    config = TelemetryConfig.from_env(
        {
            "DOCS_OTEL_ENABLED": "sometimes",
            "DOCS_OTEL_EXPORTER_OTLP_PROTOCOL": "json",
            "DOCS_OTEL_EXPORTER_OTLP_HEADERS": "=secret,missing-value=",
        }
    )

    assert config == TelemetryConfig(
        enabled=False,
        service_name="docs",
        endpoint=None,
        protocol=None,
        headers=(),
    )


def test_telemetry_config_defaults_to_grpc_when_endpoint_is_configured():
    config = TelemetryConfig.from_env(
        {
            "DOCS_OTEL_ENABLED": "true",
            "DOCS_OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
        }
    )

    assert config.protocol == "grpc"


def test_environment_factory_does_not_load_modules_when_disabled():
    loaded: list[str] = []

    def load_module(name: str) -> None:
        loaded.append(name)

    result = create_observability_from_env(
        environ={"DOCS_OTEL_ENABLED": "false"},
        module_loader=load_module,
    )

    assert isinstance(result, NoOpObservability)
    assert loaded == []


def _fake_otel_modules(*, protocol: str) -> tuple[dict[str, object], dict[str, object]]:
    state: dict[str, object] = {"exporters": [], "providers": []}

    class Resource:
        @staticmethod
        def create(attributes):
            state["resource"] = attributes
            return attributes

    class Exporter:
        def __init__(self, **kwargs):
            state["exporters"].append(kwargs)  # type: ignore[union-attr]

    class Processor:
        def __init__(self, exporter):
            self.exporter = exporter

    class Reader(Processor):
        pass

    class Provider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.processors = []

        def add_span_processor(self, processor):
            self.processors.append(processor)

        def add_log_record_processor(self, processor):
            self.processors.append(processor)

    class Meter:
        def create_counter(self, _name):
            return SimpleNamespace(add=lambda *_args: None)

        def create_histogram(self, _name):
            return SimpleNamespace(record=lambda *_args: None)

    class SpanContext:
        def __enter__(self):
            return SimpleNamespace(set_attributes=lambda _attributes: None)

        def __exit__(self, *_args):
            return False

    metrics_api = SimpleNamespace(
        set_meter_provider=lambda provider: state["providers"].append(("metrics", provider)),  # type: ignore[union-attr]
        get_meter=lambda _name: Meter(),
    )
    trace_api = SimpleNamespace(
        set_tracer_provider=lambda provider: state["providers"].append(("trace", provider)),  # type: ignore[union-attr]
        get_tracer=lambda _name: SimpleNamespace(start_as_current_span=lambda _name: SpanContext()),
    )
    logs_api = SimpleNamespace(
        LogRecord=lambda **kwargs: kwargs,
        set_logger_provider=lambda provider: state["providers"].append(("logs", provider)),  # type: ignore[union-attr]
        get_logger_provider=object,
        get_logger=lambda _name: SimpleNamespace(emit=lambda _record: None),
    )
    prefix = f"opentelemetry.exporter.otlp.proto.{protocol}"
    modules = {
        "opentelemetry.metrics": metrics_api,
        "opentelemetry.trace": trace_api,
        "opentelemetry._logs": logs_api,
        "opentelemetry.sdk.resources": SimpleNamespace(Resource=Resource),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider=Provider),
        "opentelemetry.sdk.trace.export": SimpleNamespace(BatchSpanProcessor=Processor),
        "opentelemetry.sdk.metrics": SimpleNamespace(MeterProvider=Provider),
        "opentelemetry.sdk.metrics.export": SimpleNamespace(PeriodicExportingMetricReader=Reader),
        "opentelemetry.sdk._logs": SimpleNamespace(LoggerProvider=Provider),
        "opentelemetry.sdk._logs.export": SimpleNamespace(BatchLogRecordProcessor=Processor),
        f"{prefix}.trace_exporter": SimpleNamespace(OTLPSpanExporter=Exporter),
        f"{prefix}.metric_exporter": SimpleNamespace(OTLPMetricExporter=Exporter),
        f"{prefix}._log_exporter": SimpleNamespace(OTLPLogExporter=Exporter),
    }
    return modules, state


def test_environment_factory_configures_grpc_traces_metrics_and_logs():
    modules, state = _fake_otel_modules(protocol="grpc")

    result = create_observability_from_env(
        environ={
            "DOCS_OTEL_ENABLED": "true",
            "DOCS_OTEL_SERVICE_NAME": "docs-api",
            "DOCS_OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
            "DOCS_OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "DOCS_OTEL_EXPORTER_OTLP_HEADERS": "authorization=secret",
        },
        module_loader=modules.__getitem__,
    )

    assert isinstance(result, Observability)
    assert state["resource"] == {"service.name": "docs-api"}
    assert [name for name, _provider in state["providers"]] == ["trace", "metrics", "logs"]
    assert state["exporters"] == [
        {"endpoint": "http://collector:4317", "headers": {"authorization": "secret"}},
        {"endpoint": "http://collector:4317", "headers": {"authorization": "secret"}},
        {"endpoint": "http://collector:4317", "headers": {"authorization": "secret"}},
    ]


def test_environment_factory_keeps_traces_and_metrics_when_logs_are_unavailable():
    modules, state = _fake_otel_modules(protocol="http")
    del modules["opentelemetry.sdk._logs"]

    result = create_observability_from_env(
        environ={
            "DOCS_OTEL_ENABLED": "1",
            "DOCS_OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "DOCS_OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        },
        module_loader=modules.__getitem__,
    )

    assert isinstance(result, Observability)
    assert [name for name, _provider in state["providers"]] == ["trace", "metrics"]
    assert state["exporters"] == [
        {"endpoint": "http://collector:4318/v1/traces", "headers": {}},
        {"endpoint": "http://collector:4318/v1/metrics", "headers": {}},
    ]


def test_environment_factory_is_noop_when_packages_are_missing_or_setup_fails(capsys):
    environment = {
        "DOCS_OTEL_ENABLED": "true",
        "DOCS_OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317",
        "DOCS_OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
        "DOCS_OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer%20top-secret",
    }
    modules, _state = _fake_otel_modules(protocol="grpc")
    modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = SimpleNamespace(
        OTLPSpanExporter=lambda **kwargs: (_ for _ in ()).throw(RuntimeError(repr(kwargs)))
    )

    missing = create_observability_from_env(environ=environment, module_loader=lambda _name: None)
    broken = create_observability_from_env(environ=environment, module_loader=modules.__getitem__)

    assert isinstance(missing, NoOpObservability)
    assert isinstance(broken, NoOpObservability)
    captured = capsys.readouterr()
    assert "top-secret" not in captured.out
    assert "top-secret" not in captured.err
