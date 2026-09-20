from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from docs.application.source_pipeline import SourcePipeline


class _Ingest:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def ingest_inbox(self, inbox: Path, sections: Path, *, assets_dir: Path) -> dict[str, Any]:
        return dict(self.result)


class _Writer:
    @contextmanager
    def scratch_dir(self, parent: Path):
        parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=parent) as scratch:
            yield Path(scratch)

    def atomic_finalize(self, candidate: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(candidate.read_bytes())


class _Projection:
    def __init__(self, warnings: tuple[str, ...] = (), unavailable: bool = False) -> None:
        self.warnings = warnings
        self.graph_unavailable = unavailable


class _Projector:
    def __init__(self, projection: _Projection | None = None, error: Exception | None = None) -> None:
        self.records: list[Any] | None = None
        self.projection = projection or _Projection()
        self.error = error

    def project(self, records):
        self.records = list(records)
        if self.error:
            raise self.error
        return self.projection


def _pipeline(tmp_path: Path, result: dict[str, Any], projector: Any, **kwargs: Any) -> SourcePipeline:
    return SourcePipeline(_Ingest(result), object(), _Writer(), projector, **kwargs)


def _ingest(tmp_path: Path, pipeline: SourcePipeline) -> dict[str, Any]:
    return pipeline.ingest("doc", tmp_path, {})


def test_projects_successful_explicit_normalized_records(tmp_path: Path) -> None:
    records = [{"source_id": "src-1", "source_type": "markdown", "content": "body"}]
    projector = _Projector()

    report = _ingest(tmp_path, _pipeline(tmp_path, {"status": "ok", "normalized_records": records}, projector))

    assert report["succeeded"] is True
    assert projector.records == records


def test_factory_precedes_mapper_when_both_are_configured(tmp_path: Path) -> None:
    factory_records = [{"source_id": "factory", "source_type": "source"}]
    mapper_records = [{"source_id": "mapper", "source_type": "source"}]
    projector = _Projector()
    factory_calls: list[dict[str, Any]] = []
    mapper_calls: list[dict[str, Any]] = []

    report = _ingest(
        tmp_path,
        _pipeline(
            tmp_path,
            {"status": "ok"},
            projector,
            record_factory=lambda result: (factory_calls.append(result) or factory_records),
            record_mapper=lambda result: (mapper_calls.append(result) or mapper_records),
        ),
    )

    assert report["succeeded"] is True
    assert projector.records == factory_records
    assert len(factory_calls) == 1
    assert mapper_calls == []


def test_projector_persistence_warning_preserves_ingest_success(tmp_path: Path) -> None:
    projector = _Projector(_Projection(("graph persistence unavailable: store down",), True))

    report = _ingest(
        tmp_path,
        _pipeline(tmp_path, {"status": "ok", "warnings": ["source warning"]}, projector,
                  record_mapper=lambda result: [{"source_id": "src", "source_type": "source"}]),
    )

    result = report["stages"][0]["result"]
    assert report["succeeded"] is True
    assert result["warnings"] == ["source warning", "graph persistence unavailable: store down"]


def test_projector_exception_becomes_warning_and_ingest_still_succeeds(tmp_path: Path) -> None:
    projector = _Projector(error=RuntimeError("project failed"))

    report = _ingest(tmp_path, _pipeline(
        tmp_path, {"status": "ok", "normalized_records": [{"source_id": "src", "source_type": "source"}]}, projector
    ))

    result = report["stages"][0]["result"]
    assert report["succeeded"] is True
    assert result["warnings"] == ["graph unavailable: project failed"]


def test_absent_records_are_a_no_op_for_compatibility(tmp_path: Path) -> None:
    projector = _Projector()

    report = _ingest(tmp_path, _pipeline(tmp_path, {"status": "ok"}, projector))

    assert report["succeeded"] is True
    assert projector.records is None
    assert "warnings" not in report["stages"][0]["result"]
