from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from docs.cli.commands.v2_app import (
    _batch_journal_path,
    _package_files,
    _promote_release_candidate,
    _recover_batch_transaction,
    _verify_html_artifact,
    _verify_pdf_reproducibility,
    _write_batch_journal,
    _write_package_archive,
)
from docs.cli.main import app
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest
from docs.domain.review import Issue, ReviewDimension, ReviewResult


def _minimal_pdf() -> bytes:
    objects = (
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n",
    )
    body = b"%PDF-1.4\n"
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body += obj
    xref_offset = len(body)
    xref = b"xref\n0 4\n0000000000 65535 f \n" + b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return body + xref + f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()


def test_html_verification_reopens_and_rejects_empty_visual_content(tmp_path: Path):
    artifact = tmp_path / "empty.html"
    artifact.write_text("<html><body></body></html>", encoding="utf-8")
    passed, detail = _verify_html_artifact(artifact)
    assert passed is False
    assert "renderable" in detail


def test_pdf_reproducibility_accepts_different_bytes_with_same_page_geometry(tmp_path: Path):
    original = tmp_path / "original.pdf"
    rebuilt = tmp_path / "rebuilt.pdf"
    original.write_bytes(_minimal_pdf())
    rebuilt.write_bytes(_minimal_pdf() + b"% renderer metadata differs\n")

    passed, detail = _verify_pdf_reproducibility(original, rebuilt)

    assert passed is True
    assert "semantically" in detail


class _Renderer:
    def __init__(
        self,
        output_format: str = "docx",
        *,
        required_capabilities: tuple[str, ...] = (),
        version: str = "test-renderer-1",
    ) -> None:
        self.output_format = output_format
        self.required_capabilities = required_capabilities
        self.version = version
        self.calls: list[Path] = []
        self.payload: bytes | None = None

    def build(self, doc_id: str, config: dict[str, object], output: Path | None = None) -> Path:
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        payloads = {
            "docx": f"DOCX:{doc_id}".encode(),
            "html": f"<!doctype html><html><head><title>{doc_id}</title></head><body><p>{doc_id}</p></body></html>".encode(),
            "pdf": _minimal_pdf(),
        }
        output.write_bytes(self.payload if self.payload is not None else payloads[self.output_format])
        self.calls.append(output)
        return output


class _FormatAudit:
    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.result = ReviewResult()

    def audit_format(self, path: Path, config: dict[str, object], strict: bool = False) -> ReviewResult:
        self.calls.append(path)
        return self.result


class _Qa:
    def __init__(self) -> None:
        self.calls: list[Path] = []
        self.strict_calls: list[bool] = []

    def qa_docx(self, config: dict[str, object], path: Path, strict: bool = False) -> Path:
        self.calls.append(path)
        self.strict_calls.append(strict)
        qa_dir = Path(config["paths"]["output_qa_dir"])
        qa_dir.mkdir(parents=True, exist_ok=True)
        (qa_dir / "qa-report.md").write_text("verified", encoding="utf-8")
        return qa_dir


class _Review:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool]] = []

    def review_document(self, doc_id, template, *, strict, manifest_exists, manifest_size, normative):
        self.calls.append((doc_id, strict))
        return ReviewResult()


def _deps(tmp_path: Path):
    doc_root = tmp_path / "documents" / "active"
    renderers = {fmt: _Renderer(fmt) for fmt in ("docx", "html", "pdf")}
    renderer = renderers["docx"]
    audit = _FormatAudit()
    qa = _Qa()
    review = _Review()
    context = SimpleNamespace(
        doc_id="active",
        config={
            "output": {"format": "docx"},
            "paths": {
                "output_qa_dir": str(doc_root / "output" / "qa"),
                "output_draft_dir": str(doc_root / "output" / "draft"),
            },
        },
        template=SimpleNamespace(type="test-template"),
    )
    fixture = SimpleNamespace(
        workspace=SimpleNamespace(
            documents_dir=tmp_path / "documents",
            doc_root=lambda doc_id: tmp_path / "documents" / doc_id,
        ),
        resolve_context=lambda doc="": context,
        resolve_renderer=lambda config: renderers.get(config.get("output", {}).get("format", "docx"), renderer),
        format_audit=audit,
        qa=qa,
        renderer=renderer,
        audit=audit,
        qa_adapter=qa,
        review=review,
        renderers=renderers,
        pipeline=SimpleNamespace(
            ingest_sources=lambda: (True, "ingest-sources"),
            normalize_sources=lambda: (True, "normalize-sources"),
            compile_structure=lambda: (True, "compile-structure"),
            evidence_review=lambda: (True, "evidence-review"),
            consistency_review=lambda: (True, "consistency-review"),
            accessibility_review=lambda: (True, "accessibility-review"),
            visual_review=lambda: (True, "visual-review"),
            reproducibility_check=lambda: (True, "reproducibility-check"),
            rules_manifest_state=lambda config: (True, 1),
        ),
    )
    fixture.v2_compatibility = fixture.pipeline
    return fixture


def test_v2_build_resolves_renders_audits_qa_and_publishes_verified_docx(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "build"
    assert payload["integration"] == "workspace"
    assert payload["report"]["succeeded"] is True
    published = tmp_path / "documents" / "active" / "output" / "v2" / "active.docx"
    assert published.read_bytes() == b"DOCX:active"
    manifest = json.loads(published.with_suffix(".docx.manifest.json").read_text(encoding="utf-8"))
    assert all(len(manifest[name]) == 64 for name in ("source_hash", "template_hash", "config_hash", "context_hash"))
    assert manifest["renderer_versions"]
    assert manifest["verification"]["passed"] is True
    assert manifest["provenance_run"]
    assert deps.renderer.calls
    assert deps.audit.calls
    assert deps.qa_adapter.calls


def test_v2_build_records_rendered_artifact_as_output_before_attestation(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    observed: dict[str, object] = {}
    original = __import__("docs.application.provenance_v2", fromlist=["ProvenanceLedgerV2"]).ProvenanceLedgerV2.record_attestation

    def record_attestation(self, run_id, manifest):
        observed["run"] = self.load_run(run_id)
        return original(self, run_id, manifest)

    monkeypatch.setattr("docs.application.provenance_v2.ProvenanceLedgerV2.record_attestation", record_attestation)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--json"])

    assert result.exit_code == 0, result.stdout
    record = observed["run"]
    outputs = record["outputs"]
    assert len(outputs) == 1
    rendered_path, rendered_hash = next(iter(outputs.items()))
    ledger_dir = tmp_path / "documents" / "active" / "runs"
    assert (ledger_dir / rendered_path).is_file()
    assert rendered_path.startswith("v2-artifacts/")
    assert rendered_path.endswith(".active.docx")
    assert not list(ledger_dir.glob(".v2-render-*"))
    assert rendered_hash == hashlib.sha256(b"DOCX:active").hexdigest()


def test_v2_publication_spec_includes_manifest_sidecar(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    from docs.cli.commands.v2_app import create_v2_service

    service = create_v2_service(deps)

    assert service._publication.expected_outputs == (
        "primary.docx",
        "primary.docx.manifest.json",
        "active.zip",
    )
    assert service._publication.destinations[-1].name == "active.zip"


def test_v2_manifest_renderer_identity_changes_with_declared_version(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.renderer.version = "renderer-one"
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    first = CliRunner().invoke(app, ["v2", "build", "--json"])
    first_manifest = json.loads(
        (tmp_path / "documents" / "active" / "output" / "v2" / "active.docx.manifest.json").read_text(
            encoding="utf-8"
        )
    )

    deps.renderer.version = "renderer-two"
    second = CliRunner().invoke(app, ["v2", "build", "--json"])
    second_manifest = json.loads(
        (tmp_path / "documents" / "active" / "output" / "v2" / "active.docx.manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    assert first_manifest["renderer_versions"] != second_manifest["renderer_versions"]

def test_v2_verify_runs_workspace_stages_without_publishing(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["command"] == "verify"
    assert payload["integration"] == "workspace"
    assert payload["report"]["succeeded"] is True
    assert not (tmp_path / "documents" / "active" / "output" / "v2").exists()
    assert deps.renderer.calls
    assert deps.audit.calls
    assert deps.qa_adapter.calls


def test_v2_native_stage_adapters_replace_visual_cover_and_structure_gaps(monkeypatch, tmp_path):
    deps = _deps(tmp_path)

    class _Ingest:
        def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
            del inbox_dir, sections_dir, assets_dir
            return {"processed": 0, "files": []}

    deps.ingest = _Ingest()
    deps.pipeline.compile_structure = None
    deps.pipeline.generate_visuals = None
    deps.pipeline.compose_cover = None
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    stages = {item["stage"]: item for item in payload["report"]["execution"]["results"]}
    assert stages["compile-structure"]["outcome"] == "succeeded"
    assert stages["generate-visuals"]["outcome"] == "skipped"
    assert stages["compose-cover"]["outcome"] == "skipped"


def test_v2_build_runs_native_review_and_package_handlers_when_legacy_hooks_are_absent(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.pipeline.evidence_review = None
    deps.pipeline.consistency_review = None
    deps.pipeline.visual_review = None
    attestation_checks: list[str] = []
    original_verify_attestation = __import__(
        "docs.application.provenance_v2", fromlist=["ProvenanceLedgerV2"]
    ).ProvenanceLedgerV2.verify_attestation

    def verify_attestation(self, run_id, manifest):
        attestation_checks.append(run_id)
        return original_verify_attestation(self, run_id, manifest)

    monkeypatch.setattr(
        "docs.application.provenance_v2.ProvenanceLedgerV2.verify_attestation",
        verify_attestation,
    )
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    results = payload["report"]["execution"]["results"]
    assert all(
        next(item for item in results if item["stage"] == stage)["outcome"] == "succeeded"
        for stage in ("evidence-review", "consistency-review", "visual-review", "package-release")
    )
    assert deps.review.calls
    assert attestation_checks == ["cli-build-docx"]
    release = tmp_path / "documents" / "active" / "output" / "release" / "active.zip"
    assert release.is_file()
    import zipfile

    with zipfile.ZipFile(release) as archive:
        assert "active.docx" in archive.namelist()
        assert "active.docx.manifest.json" in archive.namelist()


def test_v2_native_package_release_writes_the_release_archive_via_existing_writer(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    archive_writes: list[tuple[Path, Path]] = []
    original_writer = _write_package_archive

    def record_archive_write(output: Path, source_dir: Path, **kwargs: object) -> None:
        archive_writes.append((output, source_dir))
        original_writer(output, source_dir, **kwargs)

    monkeypatch.setattr("docs.cli.commands.v2_app._write_package_archive", record_archive_write)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--json"])

    assert result.exit_code == 0, result.stdout
    root = tmp_path / "documents" / "active"
    assert len(archive_writes) == 1
    candidate, staging = archive_writes[0]
    assert candidate == root / "output" / "release" / ".active.zip.candidate"
    assert staging.parent == root / "output"
    assert staging.name.startswith(".v2-package-")
    with zipfile.ZipFile(root / "output" / "release" / "active.zip") as archive:
        assert archive.namelist() == ["active.docx", "active.docx.manifest.json"]


def test_v2_build_only_executes_the_requested_renderer_and_cleans_renderer_scratch(
    monkeypatch, tmp_path
):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--format", "docx", "--json"])

    assert result.exit_code == 0, result.stdout
    assert deps.renderers["docx"].calls
    assert deps.renderers["html"].calls == []
    assert deps.renderers["pdf"].calls == []
    assert not list((tmp_path / "documents" / "active").glob(".v2-*") )
    assert not list((tmp_path / "documents" / "active").glob(".v2-render-*") )


def test_v2_render_rejects_replaced_retained_artifact_directory(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    original_guard = __import__("docs.cli.commands.v2_app", fromlist=["directory_handle_guard"]).directory_handle_guard
    replaced = False

    def replace_retained_directory(path):
        nonlocal replaced
        if not replaced and path.name == "v2-artifacts":
            moved = path.with_name("v2-artifacts-original")
            path.rename(moved)
            path.mkdir()
            replaced = True
        return original_guard(path)

    monkeypatch.setattr("docs.cli.commands.v2_app.directory_handle_guard", replace_retained_directory)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--json"])

    assert result.exit_code == 1
    assert "changed" in result.stdout.lower() or "boundary" in result.stdout.lower()


def test_v2_release_candidate_promotion_requires_package_lock(monkeypatch, tmp_path):
    root = tmp_path / "documents" / "active"
    release = root / "output" / "release"
    release.mkdir(parents=True)
    candidate = release / ".active.zip.candidate"
    candidate.write_bytes(b"verified-package")
    entered = False

    from contextlib import contextmanager

    @contextmanager
    def package_lock(path):
        nonlocal entered
        entered = True
        yield

    monkeypatch.setattr("docs.cli.commands.v2_app._package_lock", package_lock)

    _promote_release_candidate(root, "active")

    assert entered is True


def test_v2_release_candidate_replacement_after_verification_cannot_publish(monkeypatch, tmp_path):
    root = tmp_path / "documents" / "active"
    release = root / "output" / "release"
    release.mkdir(parents=True)
    candidate = release / ".active.zip.candidate"
    candidate.write_bytes(b"verified-package")
    original = __import__("docs.cli.commands.v2_app", fromlist=["_assert_directory_identity"])._assert_directory_identity
    calls = 0

    def replace_candidate_after_check(path, expected, *, operation):
        nonlocal calls
        calls += 1
        result = original(path, expected, operation=operation)
        if calls == 1:
            candidate.write_bytes(b"tampered-package")
        return result

    monkeypatch.setattr(
        "docs.cli.commands.v2_app._assert_directory_identity",
        replace_candidate_after_check,
    )

    with pytest.raises(Exception, match=r"candidate|package|identity|hash"):
        _promote_release_candidate(root, "active")
    assert not (release / "active.zip").exists()


def test_v2_batch_recovery_restores_outputs_from_durable_journal(tmp_path: Path):
    root = tmp_path / "document"
    output = root / "output" / "v2"
    output.mkdir(parents=True)
    (output / "report.docx").write_text("partial", encoding="utf-8")
    backup = root / ".v2-batch-crash"
    (backup / "output" / "v2").mkdir(parents=True)
    (backup / "output" / "v2" / "report.docx").write_text("previous", encoding="utf-8")
    journal = _batch_journal_path(root)
    _write_batch_journal(journal, root, backup, (Path("output") / "v2", Path("output") / "release"))

    _recover_batch_transaction(journal)

    assert (output / "report.docx").read_text(encoding="utf-8") == "previous"
    assert not journal.exists()


def test_v2_verify_uses_distinct_run_id_and_preserves_build_attestation(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    runner = CliRunner()
    assert runner.invoke(app, ["v2", "build", "--json"]).exit_code == 0
    ledger_path = tmp_path / "documents" / "active" / "runs" / "v2-provenance.json"
    before = json.loads(ledger_path.read_text(encoding="utf-8"))["attestations"]
    assert runner.invoke(app, ["v2", "verify", "--json"]).exit_code == 0
    after = json.loads(ledger_path.read_text(encoding="utf-8"))["attestations"]
    assert after == before


def test_v2_strict_verify_passes_strict_policy_into_qa(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    result = CliRunner().invoke(app, ["v2", "verify", "--policy", "strict", "--json"])
    assert result.exit_code == 0, result.stdout
    assert deps.qa.strict_calls == [True]


def test_v2_verify_can_filter_execution_results_by_dimension(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--dimension", "visual", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["report"]["dimensions"] == ["visual"]
    assert {
        item["stage"] for item in payload["report"]["execution"]["results"]
    } == {"visual-review"}


def test_v2_native_accessibility_review_degrades_findings_in_draft(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.pipeline.accessibility_review = None
    deps.format_audit.result = ReviewResult(
        [Issue("warning", "image is missing a caption", code="a11y.caption", dimension=ReviewDimension.ACCESSIBILITY)]
    )
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--policy", "draft", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    accessibility = next(
        item for item in payload["report"]["execution"]["results"] if item["stage"] == "accessibility-review"
    )
    assert accessibility["ok"] is True
    assert accessibility["warnings"] == ["image is missing a caption"]


def test_v2_native_accessibility_review_blocks_strict_findings(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.pipeline.accessibility_review = None
    deps.format_audit.result = ReviewResult(
        [Issue("warning", "image is missing a caption", code="a11y.caption", dimension=ReviewDimension.ACCESSIBILITY)]
    )
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--policy", "strict", "--json"])

    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    accessibility = next(
        item for item in payload["report"]["execution"]["results"] if item["stage"] == "accessibility-review"
    )
    assert accessibility["ok"] is False
    assert accessibility["errors"] == ["image is missing a caption"]


def test_v2_native_reproducibility_check_degrades_divergence_in_draft(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.pipeline.reproducibility_check = None

    class _DivergingRenderer(_Renderer):
        def __init__(self) -> None:
            super().__init__("docx")
            self.build_count = 0

        def build(self, doc_id: str, config: dict[str, object], output: Path | None = None) -> Path:
            self.build_count += 1
            assert output is not None
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"DOCX:{doc_id}:{self.build_count}".encode())
            self.calls.append(output)
            return output

    renderer = _DivergingRenderer()
    deps.renderer = renderer
    deps.renderers["docx"] = renderer
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--policy", "draft", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    reproducibility = next(
        item for item in payload["report"]["execution"]["results"] if item["stage"] == "reproducibility-check"
    )
    assert reproducibility["ok"] is True
    assert reproducibility["warnings"] == ["reproducibility divergence detected"]


def test_v2_native_reproducibility_check_blocks_release_divergence(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.pipeline.reproducibility_check = None

    class _DivergingRenderer(_Renderer):
        def __init__(self) -> None:
            super().__init__("docx")
            self.build_count = 0

        def build(self, doc_id: str, config: dict[str, object], output: Path | None = None) -> Path:
            self.build_count += 1
            assert output is not None
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"DOCX:{doc_id}:{self.build_count}".encode())
            self.calls.append(output)
            return output

    renderer = _DivergingRenderer()
    deps.renderer = renderer
    deps.renderers["docx"] = renderer
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--policy", "release", "--json"])

    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    reproducibility = next(
        item for item in payload["report"]["execution"]["results"] if item["stage"] == "reproducibility-check"
    )
    assert reproducibility["ok"] is False
    assert reproducibility["errors"] == ["reproducibility divergence detected"]


def test_v2_build_draft_policy_never_publishes(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--policy", "draft", "--json"])

    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["report"]["succeeded"] is False
    assert any(
        item["stage"] == "publish-draft" and item["ok"] is False
        for item in payload["report"]["execution"]["results"]
    )
    assert not (tmp_path / "documents" / "active" / "output" / "v2" / "active.docx").exists()


@pytest.mark.parametrize("mode", ("strict", "release"))
def test_v2_failed_optional_package_gate_never_publishes(monkeypatch, tmp_path, mode):
    deps = _deps(tmp_path)
    deps.pipeline.package_release = lambda: (False, "package unavailable")
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--policy", mode, "--json"])

    assert result.exit_code == 1, result.stdout
    assert not (tmp_path / "documents" / "active" / "output" / "draft").exists()
    payload = json.loads(result.stdout)
    stages = {item["stage"]: item for item in payload["report"]["execution"]["results"]}
    assert stages["package-release"]["ok"] is False
    assert stages["publish-draft"]["ok"] is False


@pytest.mark.parametrize("mode", ("strict", "release"))
def test_v2_archive_writer_failure_blocks_publish_draft(monkeypatch, tmp_path, mode):
    deps = _deps(tmp_path)
    writer_attempts: list[Path] = []

    def fail_archive_write(output: Path, source_dir: Path, **kwargs: object) -> None:
        del source_dir, kwargs
        writer_attempts.append(output)
        raise OSError("archive writer unavailable")

    monkeypatch.setattr("docs.cli.commands.v2_app._write_package_archive", fail_archive_write)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--policy", mode, "--json"])

    assert result.exit_code == 1, result.stdout
    root = tmp_path / "documents" / "active"
    assert writer_attempts == [root / "output" / "release" / ".active.zip.candidate"]
    payload = json.loads(result.stdout)
    stages = {item["stage"]: item for item in payload["report"]["execution"]["results"]}
    assert stages["package-release"]["ok"] is False
    assert "archive writer unavailable" in stages["package-release"]["errors"][0]
    assert stages["publish-draft"]["ok"] is False
    assert not (root / "output" / "v2" / "active.docx").exists()
    assert not (root / "output" / "release" / "active.zip").exists()


def test_v2_public_verify_boundary_reuses_the_published_artifact(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    runner = CliRunner()

    built = runner.invoke(app, ["v2", "build", "--json"])
    assert built.exit_code == 0, built.stdout
    verified = runner.invoke(app, ["v2", "verify", "--pipeline", "document-verify", "--json"])

    assert verified.exit_code == 0, verified.stdout
    stages = [item["stage"] for item in json.loads(verified.stdout)["report"]["execution"]["results"]]
    assert stages == [
        "structural-audit", "editorial-review", "evidence-review", "consistency-review",
        "accessibility-review", "visual-review", "reproducibility-check",
    ]


def test_v2_verify_uses_document_selected_on_cli_context(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    active = deps.resolve_context()
    selected_root = tmp_path / "documents" / "selected"
    selected_config = dict(active.config)
    selected_config["paths"] = {
        **active.config["paths"],
        "output_qa_dir": str(selected_root / "output" / "qa"),
        "output_draft_dir": str(selected_root / "output" / "draft"),
    }
    selected = SimpleNamespace(
        doc_id="selected",
        config=selected_config,
        template=active.template,
    )
    deps.resolve_context = lambda doc="": selected if doc == "selected" else active
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["--doc", "selected", "v2", "verify", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["report"]["succeeded"] is True
    assert deps.renderers["docx"].calls
    assert all("selected" in str(path) for path in deps.renderers["docx"].calls)


def test_v2_build_accepts_repeatable_formats_and_publishes_each_artifact(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "C:/tools/" + name)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--format", "docx", "--format", "html", "--format", "pdf", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert [item["format"] for item in payload] == ["docx", "html", "pdf"]
    for fmt in ("docx", "html", "pdf"):
        assert (tmp_path / "documents" / "active" / "output" / "v2" / f"active.{fmt}").exists()
        manifest = tmp_path / "documents" / "active" / "output" / "v2" / f"active.{fmt}.manifest.json"
        assert json.loads(manifest.read_text(encoding="utf-8"))["schema"] == "docs.build/v2"

    package = tmp_path / "documents" / "active" / "output" / "release" / "active.zip"
    with zipfile.ZipFile(package) as archive:
        assert archive.namelist() == [
            "active.docx",
            "active.docx.manifest.json",
            "active.html",
            "active.html.manifest.json",
            "active.pdf",
            "active.pdf.manifest.json",
        ]


def test_v2_multi_format_build_restores_all_outputs_when_later_format_fails(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    root = tmp_path / "documents" / "active"
    v2 = root / "output" / "v2"
    release = root / "output" / "release"
    v2.mkdir(parents=True)
    release.mkdir(parents=True)
    (v2 / "sentinel.docx").write_bytes(b"old-docx")
    (release / "active.zip").write_bytes(b"old-release")

    def fail_pdf(*args, **kwargs):
        raise RuntimeError("pdf renderer failed")

    deps.renderers["pdf"].build = fail_pdf
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(
        app,
        ["v2", "build", "--format", "docx", "--format", "pdf", "--json"],
    )

    assert result.exit_code == 1
    assert (v2 / "sentinel.docx").read_bytes() == b"old-docx"
    assert not (v2 / "active.docx").exists()
    assert (release / "active.zip").read_bytes() == b"old-release"


def test_v2_package_post_publication_failure_restores_previous_archive(monkeypatch, tmp_path):
    source = tmp_path / "output" / "v2"
    source.mkdir(parents=True)
    artifact = source / "active.docx"
    artifact.write_bytes(b"artifact")
    manifest = BuildManifest(
        document_id="active",
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        artifacts=(ArtifactRef(str(artifact), hashlib.sha256(b"artifact").hexdigest(), ArtifactState.READY),),
        verification={"passed": True},
        renderer_versions={"docx": "test"},
        provenance_run="run-1",
    )
    (source / "active.docx.manifest.json").write_text(manifest.to_json() + "\n", encoding="utf-8")
    output = tmp_path / "output" / "release.zip"
    output.write_bytes(b"previous")
    original = __import__("docs.cli.commands.v2_app", fromlist=["_assert_directory_identity"])._assert_directory_identity
    calls = 0

    def fail_after_replace(path, expected, *, operation):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("post-publication check")
        return original(path, expected, operation=operation)

    monkeypatch.setattr("docs.cli.commands.v2_app._assert_directory_identity", fail_after_replace)
    with pytest.raises(RuntimeError, match="post-publication check"):
        _write_package_archive(output, source, _verify_attestation=False)
    assert output.read_bytes() == b"previous"


def test_v2_package_rejects_mixed_source_generations(tmp_path):
    source = tmp_path / "output" / "v2"
    source.mkdir(parents=True)
    for fmt, source_hash in (("docx", "a" * 64), ("html", "b" * 64)):
        artifact = source / f"active.{fmt}"
        payload = fmt.encode()
        artifact.write_bytes(payload)
        manifest = BuildManifest(
            document_id="active",
            source_hash=source_hash,
            template_hash="b" * 64,
            config_hash="c" * 64,
            context_hash="d" * 64,
            artifacts=(ArtifactRef(str(artifact), hashlib.sha256(payload).hexdigest(), ArtifactState.READY),),
            verification={"passed": True},
            renderer_versions={fmt: "test"},
            provenance_run=f"run-{fmt}",
        )
        (source / f"active.{fmt}.manifest.json").write_text(manifest.to_json() + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="source generation"):
        _package_files(source, _verify_attestation=False)


def test_v2_pdf_draft_reports_missing_soffice_without_blocking_render(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--format", "pdf", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["report"]["capabilities"] == {
        "pillow": {"available": True, "path": "python:PIL"},
        "pypdfium2": {"available": True, "path": "python:pypdfium2"},
        "soffice": {"available": False, "path": None},
    }
    assert deps.renderers["pdf"].calls


@pytest.mark.parametrize("mode", ("strict", "release"))
def test_v2_pdf_strict_and_release_fail_before_render_when_soffice_is_missing(monkeypatch, tmp_path, mode):
    deps = _deps(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--format", "pdf", "--policy", mode, "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["report"]["capabilities"] == {
        "pillow": {"available": True, "path": "python:PIL"},
        "pypdfium2": {"available": True, "path": "python:pypdfium2"},
        "soffice": {"available": False, "path": None},
    }
    assert payload["report"]["execution"]["results"][0]["errors"] == ["required capability unavailable: soffice"]
    assert deps.renderers["pdf"].calls == []


def test_v2_html_uses_renderer_declared_required_capabilities(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.renderers["html"].required_capabilities = ("pandoc",)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--format", "html", "--policy", "strict", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["report"]["capabilities"] == {
        "pandoc": {"available": False, "path": None},
        "pillow": {"available": True, "path": "python:PIL"},
        "pypdfium2": {"available": True, "path": "python:pypdfium2"},
    }
    assert deps.renderers["html"].calls == []


def test_v2_visual_specs_report_optional_mermaid_capabilities(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    sections = tmp_path / "documents" / "active" / "sections"
    sections.mkdir(parents=True)
    (sections / "visual-specs.json").write_text(
        json.dumps([{"label": "architecture", "type": "mermaid", "source": "graph TD; A-->B;"}]),
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "verify", "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["report"]["capabilities"] == {
        "mmdc": {"available": False, "path": None},
        "pillow": {"available": True, "path": "python:PIL"},
        "pypdfium2": {"available": True, "path": "python:pypdfium2"},
        "resvg": {"available": False, "path": None},
    }


@pytest.mark.parametrize(
    ("output_format", "payload", "expected_detail"),
    [
        ("html", b"not an HTML document", "HTML artifact is missing an html root element"),
        ("pdf", b"not a PDF document", "PDF artifact is missing the %PDF header"),
        ("pdf", b"%PDF-1.4\n%%EOF\n", "PDF artifact is unreadable"),
    ],
)
def test_v2_build_rejects_malformed_non_docx_artifacts_before_publication(
    monkeypatch, tmp_path, output_format, payload, expected_detail
):
    deps = _deps(tmp_path)
    deps.renderers[output_format].payload = payload
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["v2", "build", "--format", output_format, "--json"])

    assert result.exit_code == 1
    assert expected_detail in result.stdout
    assert not (tmp_path / "documents" / "active" / "output" / "v2" / f"active.{output_format}").exists()


def test_v2_document_create_delegates_to_existing_document_services(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    calls: list[tuple[str, str, str]] = []
    deps.document_repository = SimpleNamespace(list_templates=lambda: ["test-template"])
    deps.documents = SimpleNamespace(create=lambda doc_id, template, title="": calls.append((doc_id, template, title)))
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "create", "proposal", "--title", "Proposal", "--json"])

    assert result.exit_code == 0, result.stdout
    assert calls == [("proposal", "test-template", "Proposal")]
    assert json.loads(result.stdout) == {
        "document_id": "proposal",
        "path": str((tmp_path / "documents" / "proposal" / "document.json").resolve()),
        "template": "test-template",
        "title": "Proposal",
    }


def test_v2_document_status_serializes_domain_status_with_v2_provenance(monkeypatch, tmp_path):
    deps = _deps(tmp_path)
    deps.renderers["docx"].required_capabilities = ("pandoc",)
    payload = {
        "doc_id": "active",
        "sections": {"authored": 0},
        "v2": {
            "execution": {"schema": "docs.build/v2", "verification": {"passed": True}},
            "provenance": {"run_id": "cli-build-docx"},
        },
    }
    calls: list[tuple[str, object, dict[str, object], object]] = []

    class _Status:
        def status_summary(self, doc_id, template, config, *, normative):
            calls.append((doc_id, template, config, normative))
            return SimpleNamespace(to_dict=lambda: payload)

    deps.status = _Status()
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)

    result = CliRunner().invoke(app, ["document", "status", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {
        **payload,
        "v2": {
            **payload["v2"],
                "capabilities": {
                    "pandoc": {"available": False, "path": None},
                    "pillow": {"available": True, "path": "python:PIL"},
                    "pypdfium2": {"available": True, "path": "python:pypdfium2"},
                },
            "unsupported_stages": [],
            "publication_blockers": [],
        },
    }
    assert calls and calls[0][0] == "active"


def test_document_baseline_updates_only_when_explicit(tmp_path: Path):
    source = tmp_path / "previews"
    source.mkdir()
    from PIL import Image
    Image.new("RGB", (10, 10), "white").save(source / "page-01.png")
    destination = tmp_path / "baseline"

    result = CliRunner().invoke(
        app, ["document", "baseline", str(source), "--destination", str(destination), "--json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] is False
    assert (destination / "page-01.png").is_file()
