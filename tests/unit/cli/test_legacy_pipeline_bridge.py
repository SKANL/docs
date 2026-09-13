"""Unit tests for the CLI legacy pipeline compatibility bridge."""
from __future__ import annotations

import pytest

import docs.cli.legacy_pipeline_bridge as bridge_module
from docs.cli.legacy_pipeline_bridge import LegacyPipelineBridge


def test_constructor_forwards_arguments_to_pipeline_service(monkeypatch):
    captured: dict[str, object] = {}
    service = object()

    def fake_pipeline_service(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return service

    monkeypatch.setattr(bridge_module, "PipelineService", fake_pipeline_service)

    bridge = LegacyPipelineBridge("workspace", strict=True)

    assert bridge._service is service
    assert captured == {"args": ("workspace",), "kwargs": {"strict": True}}


def test_getattr_delegates_public_methods_to_pipeline_service(monkeypatch):
    class FakePipelineService:
        def run_pipeline(self, document_id: str) -> str:
            return f"ran {document_id}"

    monkeypatch.setattr(bridge_module, "PipelineService", FakePipelineService)
    bridge = LegacyPipelineBridge()

    assert bridge.run_pipeline("report") == "ran report"


def test_private_and_missing_attributes_follow_normal_attribute_lookup(monkeypatch):
    service = object()
    monkeypatch.setattr(bridge_module, "PipelineService", lambda: service)
    bridge = LegacyPipelineBridge()
    private_missing = "_missing"
    public_missing = "missing"

    assert bridge._service is service
    with pytest.raises(AttributeError):
        getattr(bridge, private_missing)
    with pytest.raises(AttributeError):
        getattr(bridge, public_missing)
