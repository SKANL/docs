from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from docs.application.documents import DocumentService
from docs.application.pipeline_service_v2 import FULL_STAGE_IDS
from docs.cli.main import app
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository


class _JourneyIngest:
    def ingest_inbox(self, inbox_dir, sections_dir, assets_dir=None):
        del assets_dir
        source = next(Path(inbox_dir).glob("*.md"))
        output = Path(sections_dir) / "ingested" / "brief-md-journey.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "---\n{\"source\": \"journey\"}\n---\n" + source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return {"processed": 1, "files": [{"status": "converted", "path": str(output)}]}


class _JourneyRenderer:
    output_format = "docx"
    required_capabilities: tuple[str, ...] = ()
    version = "journey-renderer-1"

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def build(self, doc_id: str, config: dict[str, object], output: Path | None = None) -> Path:
        del config
        assert output is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"DOCX:{doc_id}:journey".encode())
        self.calls.append(output)
        return output


class _JourneyAudit:
    def audit_format(self, path: Path, config: dict[str, object], strict: bool = False):
        del path, config, strict
        from docs.domain.review import ReviewResult

        return ReviewResult()


class _JourneyQa:
    def qa_docx(self, config: dict[str, object], path: Path, strict: bool = False) -> Path:
        del path, strict
        target = Path(config["paths"]["output_qa_dir"])
        target.mkdir(parents=True, exist_ok=True)
        (target / "qa-report.md").write_text("verified", encoding="utf-8")
        return target


class _JourneyReview:
    def review_document(self, *args, **kwargs):
        from docs.domain.review import ReviewResult

        return ReviewResult()


def _journey_deps(tmp_path: Path):
    documents_dir = tmp_path / "documents"
    templates_dir = tmp_path / "templates"
    workspace = Workspace(documents_dir, templates_dir)
    repository = JsonDocumentRepository(workspace)
    documents = DocumentService(repository, workspace, clock=lambda: "2026-01-01T00:00:00")
    template = Template(type="journey", title="Journey", structure=[{"type": "sections"}])
    templates_dir.mkdir(parents=True)
    (templates_dir / "journey.json").write_text(template.model_dump_json(), encoding="utf-8")
    renderer = _JourneyRenderer()
    audit = _JourneyAudit()
    qa = _JourneyQa()
    review = _JourneyReview()

    def resolve_context(doc_id: str = ""):
        selected = doc_id or repository.active_id()
        root = workspace.doc_root(selected)
        config = {
            "output": {"format": "docx"},
            "structure": [{"type": "sections"}],
            "paths": {
                "inbox_dir": str(root / "inbox"),
                "sections_dir": str(root / "sections"),
                "assets_dir": str(root / "assets"),
                "runs_dir": str(root / "runs"),
                "output_qa_dir": str(root / "output" / "qa"),
                "output_draft_dir": str(root / "output" / "draft"),
            },
        }
        return SimpleNamespace(
            doc_id=selected,
            config=config,
            template=repository.load_template("journey"),
        )

    def stage() -> tuple[bool, str]:
        return True, "journey"
    pipeline = SimpleNamespace(
        generate_visuals=stage,
        compose_cover=stage,
        build_html=stage,
        build_pdf=stage,
        structural_audit=stage,
        accessibility_review=stage,
        visual_review=stage,
        reproducibility_check=stage,
        evidence_review=stage,
        consistency_review=stage,
        rules_manifest_state=lambda config: (True, 1),
    )
    return SimpleNamespace(
        workspace=workspace,
        document_repository=repository,
        documents=documents,
        ingest=_JourneyIngest(),
        markdown_normalizer=MdNormalizeAdapter(),
        atomic_file_writer=AtomicFileAdapter(),
        resolve_context=resolve_context,
        resolve_renderer=lambda config: renderer,
        renderers={"docx": renderer},
        renderer=renderer,
        format_audit=audit,
        qa=qa,
        review=review,
        pipeline=pipeline,
        v2_compatibility=pipeline,
    )


def invoke(runner: CliRunner, *args: str):
    result = runner.invoke(app, ["document", *args, "--json"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_v2_public_journey_creates_prepares_builds_verifies_packages_and_publishes(
    monkeypatch, tmp_path: Path
) -> None:
    deps = _journey_deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    runner = CliRunner()

    created = invoke(runner, "create", "journey", "--template", "journey", "--title", "Journey")
    root = deps.workspace.doc_root("journey")
    (root / "inbox" / "source.md").write_text("A source claim.\n", encoding="utf-8")
    assert created["document_id"] == "journey"
    assert (root / "document.json").is_file()

    ingested = invoke(runner, "ingest")
    prepared = invoke(runner, "prepare")
    built = invoke(runner, "build")
    verified = invoke(runner, "verify")

    assert ingested["stages"][0]["name"] == "ingest-sources"
    assert [stage["name"] for stage in prepared["stages"]] == [
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
    ]
    assert built["report"]["succeeded"] is True
    assert verified["report"]["succeeded"] is True

    artifact = root / "output" / "v2" / "journey.docx"
    package = root / "output" / "release" / "journey-external.zip"
    packaged = invoke(runner, "package", str(artifact.parent), str(package))
    published = invoke(
        runner,
        "publish",
        str(artifact),
        str(root / "published" / "journey.docx"),
    )

    assert packaged["path"] == str(package.resolve())
    assert published["published"] is True
    assert (root / "published" / "journey.docx").read_bytes() == artifact.read_bytes()
    assert all(deps.renderer.calls)
    assert (root / "runs" / "v2-prepare.json").is_file()
    assert set(FULL_STAGE_IDS) >= {
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
        "build-docx",
        "editorial-review",
        "package-release",
        "publish-draft",
    }


def test_v2_release_command_composes_creation_and_verified_build(monkeypatch, tmp_path: Path) -> None:
    deps = _journey_deps(tmp_path)
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["document", "create", "one-shot", "--template", "journey", "--title", "One-shot", "--json"],
    )
    assert created.exit_code == 0, created.stdout
    (deps.workspace.doc_root("one-shot") / "inbox" / "source.md").write_text(
        "A source claim.\n", encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "document",
            "release",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["report"]["succeeded"] is True
    root = deps.workspace.doc_root("one-shot")
    assert (root / "document.json").is_file()
    assert (root / "output" / "v2" / "one-shot.docx").is_file()
    assert (root / "output" / "release" / "one-shot.zip").is_file()


def test_v2_builtin_template_journey_produces_artifacts_and_provenance(
    monkeypatch, tmp_path: Path
) -> None:
    """The public journey must work in an isolated workspace with a shipped template."""
    deps = _journey_deps(tmp_path)
    fixture = Path(__file__).parents[1] / "fixtures" / "templates" / "documento-generico.json"
    (deps.workspace.templates_dir / "documento-generico.json").write_bytes(fixture.read_bytes())
    monkeypatch.setattr("docs.cli.main.Deps", lambda: deps)
    runner = CliRunner()

    created = invoke(
        runner,
        "create",
        "canonical",
        "--template",
        "documento-generico",
        "--title",
        "Canonical journey",
    )
    root = deps.workspace.doc_root("canonical")
    (root / "inbox" / "source.md").write_text("A source claim.\n", encoding="utf-8")

    ingested = invoke(runner, "ingest")
    prepared = invoke(runner, "prepare")
    built = invoke(runner, "build")
    verified = invoke(runner, "verify")

    artifact = root / "output" / "v2" / "canonical.docx"
    inspected = invoke(runner, "inspect", str(artifact))
    package = root / "output" / "release" / "canonical.zip"
    packaged = invoke(runner, "package", str(artifact.parent), str(package))
    destination = root / "published" / "canonical.docx"
    published = invoke(runner, "publish", str(artifact), str(destination))

    assert created["document_id"] == "canonical"
    assert ingested["stages"][0]["name"] == "ingest-sources"
    assert [stage["name"] for stage in prepared["stages"]] == [
        "ingest-sources",
        "normalize-sources",
        "compile-structure",
    ]
    assert built["report"]["succeeded"] is True
    assert verified["report"]["succeeded"] is True
    assert artifact.read_bytes() == b"DOCX:canonical:journey"
    assert inspected["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert packaged["path"] == str(package.resolve())
    with zipfile.ZipFile(package) as archive:
        assert "canonical.docx" in archive.namelist()

    manifest_path = artifact.with_suffix(".docx.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["document_id"] == "canonical"
    assert manifest["verification"]["passed"] is True
    assert manifest["artifacts"][0]["sha256"] == inspected["sha256"]
    assert manifest["provenance_run"] == "cli-build-docx"
    assert "cli-build-docx" in (root / "runs" / "v2-provenance.json").read_text(encoding="utf-8")
    assert published["published"] is True
    assert destination.read_bytes() == artifact.read_bytes()
    assert destination.with_suffix(".docx.manifest.json").read_bytes() == manifest_path.read_bytes()


def test_v2_stage_traceability_declares_every_runtime_stage() -> None:
    path = Path(__file__).parents[2] / "docs" / "migration-v2-traceability.json"
    traceability = json.loads(path.read_text(encoding="utf-8"))
    declared = {entry["stage"] for entry in traceability["pipeline_stages"]}
    assert declared == set(FULL_STAGE_IDS)
    assert traceability["journey"]["status"] in {"covered", "closest-real-journey"}
