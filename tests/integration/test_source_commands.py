from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from docs.application.source_pipeline import SourcePipeline
from docs.cli.main import app
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter


class _Ingest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del assets_dir
        target = Path(sections_dir) / "ingested" / "brief-md-deadbeef.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("---\n{\"z\": 1, \"a\": 2}\n---\nBody\n", encoding="utf-8")
        return {"processed": 1, "files": [{"status": "converted", "path": str(target)}]}


class _FailedIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del inbox_dir, sections_dir, assets_dir
        return {"status": "degraded", "processed": 0, "files": [], "errors": ["pandoc unavailable"]}


class _ExplodingIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del inbox_dir, sections_dir, assets_dir
        raise RuntimeError("source adapter crashed")


class _ExplodingFileWriter(AtomicFileAdapter):
    def atomic_finalize(self, source: Path, destination: Path) -> None:
        if destination.name == "v2-structure.json":
            del source, destination
            raise RuntimeError("structure persistence crashed")
        super().atomic_finalize(source, destination)


class _ReportPersistenceFailingWriter(AtomicFileAdapter):
    def atomic_finalize(self, source: Path, destination: Path) -> None:
        if destination.name == "v2-ingest.json":
            del source, destination
            raise RuntimeError("report persistence crashed")
        super().atomic_finalize(source, destination)


class _StrictIngest:
    def __init__(self) -> None:
        self.strict_calls: list[bool] = []

    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False):
        del inbox_dir, sections_dir, assets_dir
        self.strict_calls.append(strict)
        return {
            "processed": 0,
            "files": [],
            "strict_policy": {"requested": True, "applied": True, "mode": "enforced"},
        }


class _IgnoringStrictIngest:
    def __init__(self) -> None:
        self.strict_calls: list[bool] = []

    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False):
        del inbox_dir, sections_dir, assets_dir
        self.strict_calls.append(strict)
        return {"processed": 0, "files": []}


class _ContradictoryStrictPolicyIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False):
        del inbox_dir, sections_dir, assets_dir, strict
        return {
            "processed": 0,
            "files": [],
            "strict_policy": {"requested": True, "applied": True, "mode": "advisory"},
        }


class _PositionalOnlyStrictIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False, /):
        del inbox_dir, sections_dir, assets_dir, strict
        return {"processed": 0, "files": []}


def _deps(tmp_path: Path):
    root = tmp_path / "documents" / "brief"
    context = SimpleNamespace(
        doc_id="brief",
        config={
            "paths": {
                "inbox_dir": str(root / "inbox"),
                "sections_dir": str(root / "sections"),
                "assets_dir": str(root / "assets"),
                "runs_dir": str(root / "runs"),
            },
            "structure": [{"type": "sections"}],
        },
    )
    return SimpleNamespace(
        ingest=_Ingest(),
        markdown_normalizer=MdNormalizeAdapter(),
        atomic_file_writer=AtomicFileAdapter(),
        resolve_context=lambda doc="": context,
        workspace=SimpleNamespace(doc_root=lambda doc_id: root),
    )


def test_source_prepare_normalizes_and_compiles_atomic_outputs(tmp_path: Path) -> None:
    root = tmp_path / "document"
    config = {"structure": [{"type": "sections"}]}
    service = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter())

    report = service.prepare("brief", root, config)

    assert report["succeeded"] is True
    normalized = next((root / "sections" / "ingested").glob("*.md"))
    assert normalized.read_text(encoding="utf-8") == (
        '---\n{\n  "a": 2,\n  "z": 1\n}\n---\nBody\n'
    )
    structure = json.loads((root / "sections" / "v2-structure.json").read_text(encoding="utf-8"))
    assert structure["parts"] == [{"type": "sections"}]
    assert (root / "runs" / "v2-prepare.json").is_file()


def test_source_prepare_persists_reports_in_configured_runs_dir(tmp_path: Path) -> None:
    root = tmp_path / "document"
    runs = tmp_path / "custom-runs"
    config = {"paths": {"runs_dir": str(runs)}, "structure": [{"type": "sections"}]}

    report = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter()).prepare(
        "brief", root, config
    )

    assert report["succeeded"] is True
    assert (runs / "v2-prepare.json").is_file()
    assert not (root / "runs" / "v2-prepare.json").exists()


def test_source_ingest_fails_closed_when_required_report_persistence_fails(tmp_path: Path) -> None:
    report = SourcePipeline(
        _Ingest(), MdNormalizeAdapter(), _ReportPersistenceFailingWriter()
    ).ingest("brief", tmp_path / "document", {})

    assert report["document_id"] == "brief"
    assert report["succeeded"] is False
    assert report["stages"][0]["succeeded"] is False
    assert report["errors"] == [{
        "code": "pipeline.v2_report_persistence_failed",
        "message": "The required v2 ingest report could not be persisted: report persistence crashed",
    }]


def test_source_prepare_resolves_relative_runs_dir_from_document_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "document"
    other_cwd = tmp_path / "unrelated-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    config = {"paths": {"runs_dir": "relative-runs"}, "structure": [{"type": "sections"}]}

    report = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter()).prepare(
        "brief", root, config
    )

    assert report["succeeded"] is True
    assert (root / "relative-runs" / "v2-prepare.json").is_file()
    assert not (other_cwd / "relative-runs" / "v2-prepare.json").exists()


def test_source_prepare_resolves_all_relative_paths_from_document_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "document"
    other_cwd = tmp_path / "unrelated-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    config = {
        "paths": {
            "inbox_dir": "relative-inbox",
            "sections_dir": "relative-sections",
            "assets_dir": "relative-assets",
            "runs_dir": "relative-runs",
        },
        "structure": [{"type": "sections"}],
    }

    report = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter()).prepare(
        "brief", root, config
    )

    assert report["succeeded"] is True
    assert (root / "relative-sections" / "v2-structure.json").is_file()
    assert (root / "relative-runs" / "v2-prepare.json").is_file()
    assert not (other_cwd / "relative-sections").exists()
    assert not (other_cwd / "relative-runs").exists()


def test_source_prepare_preserves_absolute_configured_paths(tmp_path: Path) -> None:
    root = tmp_path / "document"
    absolute_paths = {
        "inbox_dir": tmp_path / "absolute-inbox",
        "sections_dir": tmp_path / "absolute-sections",
        "assets_dir": tmp_path / "absolute-assets",
        "runs_dir": tmp_path / "absolute-runs",
    }
    config = {
        "paths": {name: str(path) for name, path in absolute_paths.items()},
        "structure": [{"type": "sections"}],
    }

    report = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter()).prepare(
        "brief", root, config
    )

    assert report["succeeded"] is True
    assert (absolute_paths["sections_dir"] / "v2-structure.json").is_file()
    assert (absolute_paths["runs_dir"] / "v2-prepare.json").is_file()
    assert not (root / "sections").exists()
    assert not (root / "runs").exists()


@pytest.mark.parametrize("invalid_result", [None, [], "invalid"])
def test_source_ingest_rejects_non_mapping_adapter_results(tmp_path: Path, invalid_result) -> None:
    class _InvalidIngest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return invalid_result

    report = SourcePipeline(_InvalidIngest(), MdNormalizeAdapter(), AtomicFileAdapter()).ingest(
        "brief", tmp_path / "document", {}
    )

    assert report["succeeded"] is False
    assert report["stages"][0]["result"]["status"] == "failed"
    assert report["stages"][0]["result"]["errors"] == ["v2 ingest result must be a mapping"]


def test_source_ingest_rejects_non_boolean_explicit_success_result(tmp_path: Path) -> None:
    class _IngestWithMalformedSuccess:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"succeeded": "yes", "processed": 0, "files": []}

    report = SourcePipeline(
        _IngestWithMalformedSuccess(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"] == [{
        "name": "ingest-sources",
        "succeeded": False,
        "result": {"succeeded": "yes", "processed": 0, "files": []},
    }]


def test_source_ingest_contains_validated_adapter_output_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "document"

    class _IngestWithOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, assets_dir
            output = Path(sections_dir) / "ingested" / "brief-md-deadbeef.md"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("body\n", encoding="utf-8")
            return {
                "processed": 1,
                "files": [{"status": "converted", "path": str(output)}],
            }

    report = SourcePipeline(
        _IngestWithOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {})

    assert report["artifacts"] == ["sections/ingested/brief-md-deadbeef.md"]
    assert report["stages"][0]["result"]["files"][0]["path"]


@pytest.mark.parametrize("raw_path", ["../outside.md"])
def test_source_ingest_ignores_artifacts_outside_document_root(tmp_path: Path, raw_path: str) -> None:
    root = tmp_path / "document"
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")

    class _IngestWithOutsideOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"files": [{"status": "converted", "path": raw_path}]}

    report = SourcePipeline(
        _IngestWithOutsideOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {})

    assert report["artifacts"] == []


def test_source_ingest_ignores_absolute_artifacts_outside_configured_roots(tmp_path: Path) -> None:
    root = tmp_path / "document"
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")

    class _IngestWithOutsideOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"files": [{"status": "converted", "path": str(outside)}]}

    report = SourcePipeline(
        _IngestWithOutsideOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {})

    assert report["artifacts"] == []


@pytest.mark.parametrize("root_name", ["sections_dir", "assets_dir", "runs_dir"])
def test_source_ingest_ignores_artifacts_in_configured_roots_outside_document_root(
    tmp_path: Path, root_name: str
) -> None:
    root = tmp_path / "document"
    configured_root = tmp_path / f"external-{root_name}"
    output = configured_root / "artifact.md"

    class _IngestWithConfiguredOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("outside\n", encoding="utf-8")
            return {"files": [{"status": "converted", "path": str(output)}]}

    report = SourcePipeline(
        _IngestWithConfiguredOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {"paths": {root_name: str(configured_root)}})

    assert report["artifacts"] == []


def test_source_ingest_does_not_accept_inbox_as_output_evidence(tmp_path: Path) -> None:
    root = tmp_path / "document"
    inbox_output = root / "inbox" / "claimed.md"
    inbox_output.parent.mkdir(parents=True)
    inbox_output.write_text("input\n", encoding="utf-8")

    class _IngestWithInboxOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"files": [{"status": "converted", "path": str(inbox_output)}]}

    report = SourcePipeline(
        _IngestWithInboxOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {})

    assert report["artifacts"] == []


def test_source_ingest_ignores_symlink_artifact_escaping_configured_root(tmp_path: Path) -> None:
    root = tmp_path / "document"
    sections = root / "sections"
    sections.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    escaped = sections / "escaped.md"
    try:
        escaped.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    class _IngestWithEscapingOutput:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"files": [{"status": "converted", "path": str(escaped)}]}

    report = SourcePipeline(
        _IngestWithEscapingOutput(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", root, {})

    assert report["artifacts"] == []


@pytest.mark.parametrize("operation_name", ["ingest", "normalize", "compile_structure", "prepare"])
def test_source_operations_turn_invalid_paths_config_into_failed_v2_reports(
    tmp_path: Path, operation_name: str
) -> None:
    service = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter())

    report = getattr(service, operation_name)("brief", tmp_path / "document", {"paths": None})

    assert report["schema"] == "docs.sources/v2"
    assert report["document_id"] == "brief"
    assert report["succeeded"] is False
    assert report["stages"][0]["succeeded"] is False


def test_document_ingest_is_public_and_returns_structured_report(monkeypatch, tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "ingest", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema"] == "docs.sources/v2"
    assert payload["stages"][0]["name"] == "ingest-sources"


def test_document_prepare_wires_all_source_handlers(monkeypatch, tmp_path: Path) -> None:
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "prepare", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [stage["name"] for stage in payload["stages"]] == [
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
    ]




def test_source_prepare_propagates_degraded_ingest_without_claiming_success(tmp_path: Path) -> None:
    report = SourcePipeline(_FailedIngest(), MdNormalizeAdapter(), AtomicFileAdapter()).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"][0]["succeeded"] is False
    assert report["stages"][0]["result"]["status"] == "degraded"


def test_source_prepare_skips_dependent_stages_after_ingest_failure(tmp_path: Path) -> None:
    class _UnexpectedNormalizer:
        def normalize(self, original: str) -> str:
            raise AssertionError(f"normalization must not run: {original}")

    report = SourcePipeline(
        _FailedIngest(), _UnexpectedNormalizer(), AtomicFileAdapter()
    ).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert [stage["name"] for stage in report["stages"]] == [
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
    ]
    assert report["stages"][1]["skipped"] is True
    assert report["stages"][1]["result"] == {
        "status": "skipped",
        "reason": "dependency_failed",
        "depends_on": "ingest-sources",
    }
    assert report["stages"][2]["skipped"] is True
    assert report["stages"][2]["result"] == {
        "status": "skipped",
        "reason": "dependency_failed",
        "depends_on": "normalize-sources",
    }


def test_source_ingest_converts_adapter_exception_to_failed_stage_report(tmp_path: Path) -> None:
    report = SourcePipeline(_ExplodingIngest(), MdNormalizeAdapter(), AtomicFileAdapter()).ingest("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["document_id"] == "brief"
    assert report["stages"][0]["result"]["status"] == "failed"
    assert report["stages"][0]["result"]["errors"] == ["source adapter crashed"]


def test_source_ingest_reports_missing_adapter_operation_with_document_id(tmp_path: Path) -> None:
    report = SourcePipeline(object(), MdNormalizeAdapter(), AtomicFileAdapter()).ingest(
        "brief", tmp_path / "document", {}
    )

    assert report["succeeded"] is False
    assert report["document_id"] == "brief"
    assert report["stages"][0]["result"]["status"] == "failed"


def test_source_ingest_forwards_strict_when_adapter_supports_it(tmp_path: Path) -> None:
    adapter = _StrictIngest()

    report = SourcePipeline(adapter, MdNormalizeAdapter(), AtomicFileAdapter()).ingest(
        "brief", tmp_path / "document", {}, strict=True
    )

    assert report["succeeded"] is True
    assert adapter.strict_calls == [True]
    assert report["strict_policy"] == {"requested": True, "applied": True, "mode": "enforced"}


def test_source_ingest_does_not_infer_strict_enforcement_from_parameter_acceptance(
    tmp_path: Path,
) -> None:
    adapter = _IgnoringStrictIngest()

    report = SourcePipeline(adapter, MdNormalizeAdapter(), AtomicFileAdapter()).ingest(
        "brief", tmp_path / "document", {}, strict=True
    )

    assert adapter.strict_calls == [True]
    assert report["strict_policy"] == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
        "warning": "v2 ingest does not expose strict enforcement",
    }


def test_source_ingest_rejects_contradictory_adapter_strict_policy(tmp_path: Path) -> None:
    report = SourcePipeline(
        _ContradictoryStrictPolicyIngest(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", tmp_path / "document", {}, strict=True)

    assert report["document_id"] == "brief"
    assert report["succeeded"] is False
    assert report["stages"][0]["succeeded"] is False
    assert report["errors"] == [{
        "code": "pipeline.malformed_strict_policy",
        "message": "The v2 ingest strict_policy is contradictory: applied true requires requested true and mode enforced.",
    }]


def test_source_ingest_rejects_adapter_requested_strict_mismatch_without_masking_evidence(
    tmp_path: Path,
) -> None:
    class _MismatchedStrictPolicyIngest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False):
            del inbox_dir, sections_dir, assets_dir, strict
            return {
                "processed": 0,
                "files": [],
                "strict_policy": {"requested": True, "applied": False, "mode": "advisory"},
            }

    report = SourcePipeline(
        _MismatchedStrictPolicyIngest(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", tmp_path / "document", {}, strict=False)

    assert report["succeeded"] is False
    assert report["strict_policy"] == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
    }
    assert report["errors"][0]["code"] == "pipeline.malformed_strict_policy"


@pytest.mark.parametrize(
    "strict_policy",
    [
        ["not", "a", "mapping"],
        {"requested": "true", "applied": False, "mode": "advisory"},
        {"requested": False, "applied": 1, "mode": "advisory"},
        {"requested": False, "applied": False, "mode": "not-requested"},
        {"requested": True, "applied": False, "mode": "enforced"},
    ],
)
def test_source_ingest_rejects_malformed_adapter_strict_policy(
    tmp_path: Path, strict_policy: object
) -> None:
    class _MalformedPolicyIngest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None, strict=False):
            del inbox_dir, sections_dir, assets_dir, strict
            return {"processed": 0, "files": [], "strict_policy": strict_policy}

    report = SourcePipeline(
        _MalformedPolicyIngest(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", tmp_path / "document", {}, strict=True)

    assert report["succeeded"] is False
    assert report["errors"][0]["code"] == "pipeline.malformed_strict_policy"


def test_source_ingest_marks_strict_advisory_when_adapter_lacks_it(tmp_path: Path) -> None:
    report = SourcePipeline(_Ingest(), MdNormalizeAdapter(), AtomicFileAdapter()).ingest(
        "brief", tmp_path / "document", {}, strict=True
    )

    assert report["strict_policy"] == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
        "warning": "v2 ingest does not expose strict enforcement",
    }


def test_source_ingest_treats_positional_only_strict_as_unsupported(tmp_path: Path) -> None:
    report = SourcePipeline(
        _PositionalOnlyStrictIngest(), MdNormalizeAdapter(), AtomicFileAdapter()
    ).ingest("brief", tmp_path / "document", {}, strict=True)

    assert report["succeeded"] is True
    assert report["strict_policy"] == {
        "requested": True,
        "applied": False,
        "mode": "advisory",
        "warning": "v2 ingest does not expose strict enforcement",
    }


def test_source_prepare_propagates_normalization_failure(tmp_path: Path) -> None:
    class _BrokenNormalizer:
        def normalize(self, original: str) -> str:
            del original
            raise RuntimeError("normalizer crashed")

    report = SourcePipeline(_Ingest(), _BrokenNormalizer(), AtomicFileAdapter()).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    assert report["stages"][1]["succeeded"] is False
    assert report["stages"][1]["result"]["errors"] == ["normalizer crashed"]
    assert report["stages"][2] == {
        "name": "compile-structure",
        "succeeded": False,
        "skipped": True,
        "result": {
            "status": "skipped",
            "reason": "dependency_failed",
            "depends_on": "normalize-sources",
        },
    }


def test_source_prepare_converts_compile_structure_exception_to_failed_stage_report(
    tmp_path: Path,
) -> None:
    report = SourcePipeline(
        _Ingest(), MdNormalizeAdapter(), _ExplodingFileWriter()
    ).prepare("brief", tmp_path / "document", {})

    assert report["succeeded"] is False
    compile_stage = report["stages"][2]
    assert compile_stage["name"] == "compile-structure"
    assert compile_stage["succeeded"] is False
    assert compile_stage["result"] == {
        "status": "failed",
        "errors": ["structure persistence crashed"],
    }


def test_source_ingest_alias_uses_the_same_native_stage(tmp_path, monkeypatch):
    # The source namespace is a public spelling of the v2 ingest boundary.
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    result = CliRunner().invoke(app, ["source", "ingest", "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["succeeded"] is True
