# OpenTelemetry

Observability is optional and fail-open. The CLI, API, and worker composition
roots all use the same environment-based factory. With telemetry disabled or
with incomplete/invalid exporter configuration, the runtime uses a no-op
adapter and document execution continues.

## Configuration

```text
DOCS_OTEL_ENABLED=true
DOCS_OTEL_SERVICE_NAME=docs-api
DOCS_OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example.test:4317
DOCS_OTEL_EXPORTER_OTLP_PROTOCOL=grpc
DOCS_OTEL_EXPORTER_OTLP_HEADERS=api-key=redacted%2Dvalue
```

The protocol is `grpc` or `http/protobuf`. If an endpoint is set without a
protocol, gRPC is selected. Header keys and values are URL-decoded, malformed
entries are ignored, and configuration representations redact endpoint and
header contents.

Install the optional dependencies only in deployments that export signals:

```bash
uv sync --extra observability
```

## Signals and data policy

The adapter emits low-cardinality request/pipeline spans, counters, duration
observations, structured logs, and passport metrics. Signal names and free-form
text are normalized and bounded. Passport entries are redacted before metrics
are recorded; authorization, tokens, credentials, secrets, cookies, private
keys, and sensitive paths must never become telemetry attributes.

Exporter setup errors return the no-op adapter. Monitor exporter health
separately from document correctness: telemetry failure must not turn a valid
document build into a data-loss or publication bypass path.
