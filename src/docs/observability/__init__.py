"""Optional, fail-open telemetry for document pipeline execution."""

from .core import (
    NoOpObservability,
    Observability,
    ObservabilityPort,
    TelemetryConfig,
    create_observability,
    create_observability_from_env,
)
from .passport import passport_metrics
from .redaction import redact_attributes

__all__ = [
    "NoOpObservability",
    "Observability",
    "ObservabilityPort",
    "TelemetryConfig",
    "create_observability",
    "create_observability_from_env",
    "passport_metrics",
    "redact_attributes",
]
