# tests/integration/test_collection_service.py
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from docs.application.collection import CollectionService
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def service() -> CollectionService:
    return CollectionService(FilesystemSourceRepository(), JsonEvidenceRepository())


def _config(tmp_path: Path, **overrides) -> dict[str, Any]:
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    config: dict[str, Any] = {
        "paths": {
            "context_dir": str(context_dir),
            "source_manifest": str(tmp_path / "source-manifest.json"),
            "issues_manifest": str(tmp_path / "issues-manifest.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence-manifest.json"),
        },
        "evidence_sources": {},
        "privacy": {},
        "project": {},
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


# --- collect_sources ---

def test_collect_sources_includes_approved_context_md_files(tmp_path: Path, service):
    config = _config(tmp_path)
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "scope.md").write_text("Alcance del proyecto.")
    (context_dir / "_draft.md").write_text("borrador")
    (context_dir / "index.md").write_text("indice")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_count"] == 1
    assert manifest["sources"][0]["type"] == "approved_context"
    assert manifest["sources"][0]["classification"] == "confirmado"


def test_collect_sources_includes_manual_dir_when_present(tmp_path: Path, service):
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    (manual_dir / "norma.md").write_text("Norma institucional.")
    config = _config(tmp_path, paths={"manual_dir": str(manual_dir)})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    types = [s["type"] for s in manifest["sources"]]
    assert "institutional_manual" in types


def test_collect_sources_skips_missing_manual_dir(tmp_path: Path, service):
    config = _config(tmp_path, paths={"manual_dir": str(tmp_path / "missing")})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["sources"] == []


def test_collect_sources_includes_evidence_files_with_use_and_type(tmp_path: Path, service):
    evidence_root = tmp_path / "evidence_root"
    evidence_root.mkdir()
    (evidence_root / "data.json").write_text("{}")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "files": [{"path": "data.json", "type": "tech_doc", "use": "evidencia secundaria"}],
        },
    )
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["type"] == "tech_doc")
    assert entry["use"] == "evidencia secundaria"


def test_collect_sources_includes_cover_template_and_example_pdf(tmp_path: Path, service):
    template = tmp_path / "template.docx"
    template.write_bytes(b"PK\x03\x04fake")
    example = tmp_path / "example.pdf"
    example.write_bytes(b"%PDF-1.4 fake")
    config = _config(tmp_path, paths={"template_docx": str(template), "example_pdf": str(example)})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    types = {s["type"] for s in manifest["sources"]}
    assert types == {"cover_template", "example_reference"}
    classifications = {s["type"]: s["classification"] for s in manifest["sources"]}
    assert classifications["cover_template"] == "confirmado"
    assert classifications["example_reference"] == "fuera_de_alcance"


def test_collect_sources_injects_contradiction_fact_when_term_found(tmp_path: Path, service):
    config = _config(
        tmp_path,
        evidence_sources={"scope_contradiction_terms": ["fuera de alcance original"]},
    )
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "scope.md").write_text("Esto está Fuera De Alcance Original, ojo.")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any(f["classification"] == "contradiccion" for f in manifest["facts"])


def test_collect_sources_injects_sensitive_field_fact_when_table_row_present(tmp_path: Path, service):
    config = _config(tmp_path, privacy={"sensitive_context_fields": ["DNI"]})
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "datos.md").write_text("| Campo | Valor |\n| **DNI** | 12345678 |\n")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any(f["classification"] == "dato_sensible" and "DNI" in f["claim"] for f in manifest["facts"])


def test_collect_sources_excludes_curated_index_from_sources_and_facts(tmp_path: Path, service):
    # Regression (fresh-context review CRITICAL, PR8 remediation): PR8's
    # `stage_build_context_index` writes `context/curated-index.md`, but the
    # reader side (this method) only skipped `_`-prefixed files and the
    # literal `index.md` -- so the new curated index leaked in as a
    # "confirmado" approved-context source, AND its body text was scanned
    # for contradiction/sensitive-field facts, producing false positives.
    # Real CollectionService + FilesystemSourceRepository, no mocks.
    config = _config(
        tmp_path,
        evidence_sources={"scope_contradiction_terms": ["fuera de alcance original"]},
    )
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "scope.md").write_text("Alcance del proyecto.")
    (context_dir / "curated-index.md").write_text(
        "# Context Index\n\nBoilerplate mentioning Fuera De Alcance Original.\n"
    )
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    source_names = [Path(s["path"]).name for s in manifest["sources"]]
    assert "curated-index.md" not in source_names
    assert manifest["source_count"] == 1  # only scope.md
    assert manifest["facts"] == []  # curated-index.md boilerplate must not surface a false-positive fact


def test_collect_sources_still_includes_curated_concern_files_as_approved_context(tmp_path: Path, service):
    # Contract lock (not RED-first, existing/unchanged behavior): design.md's
    # Context Layout places keywords.md/tone.md/structure.md/writing-style.md/
    # formatting-rules.md in the same `context/` directory as approved
    # context, and its Data Flow routes them through the same [agent fills
    # slots] step before rendering -- they ARE meant to be collected as
    # "approved_context" sources, unlike the purely-generated index files.
    config = _config(tmp_path)
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "keywords.md").write_text("# Keywords\n\n- alcance\n")
    (context_dir / "curated-index.md").write_text("# Context Index\n\n- [Keywords](keywords.md)\n")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    by_name = {Path(s["path"]).name: s["type"] for s in manifest["sources"]}
    assert by_name.get("keywords.md") == "approved_context"
    assert "curated-index.md" not in by_name


def test_collect_sources_carries_scope_policy(tmp_path: Path, service):
    config = _config(tmp_path, project={"scope_policy": "alcance institucional"})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["policy"] == "alcance institucional"


# --- collect_issues ---

def test_collect_issues_raises_when_gh_not_available(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = _config(tmp_path)
    with pytest.raises(RuntimeError, match="GitHub CLI `gh` no está disponible"):
        service.collect_issues(config, repo_root=tmp_path)


def test_collect_issues_raises_when_repo_not_detected(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            raise OSError("no remote")
        raise AssertionError("should not call gh before repo is detected")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    with pytest.raises(RuntimeError, match="No se pudo detectar el repositorio GitHub"):
        service.collect_issues(config, repo_root=tmp_path)


def test_collect_issues_writes_manifest_with_parsed_issues(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")
        return subprocess.CompletedProcess(
            args, 0, stdout='[{"number": 1, "title": "Bug", "state": "OPEN", "url": "u", "labels": []}]', stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    path = service.collect_issues(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["repo"] == "org/repo"
    assert manifest["issue_count"] == 1
    assert manifest["issues"][0]["classification"] == "confirmado"


def test_collect_issues_propagates_called_process_error_from_gh(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        service.collect_issues(config, repo_root=tmp_path)


# --- collect_code_evidence ---

def test_collect_code_evidence_empty_when_no_evidence_sources(tmp_path: Path, service):
    config = _config(tmp_path)
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["files"] == []
    assert manifest["facts"] == []
    assert manifest["root"] == ""


def test_collect_code_evidence_detects_dependency_token(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "pyproject.toml").write_text('dependencies = ["fastapi"]')
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "files": [{"path": "pyproject.toml", "type": "python_dependency_manifest"}],
            "dependency_tokens": ["fastapi"],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any("fastapi" in f["claim"] for f in manifest["facts"])


def test_collect_code_evidence_globs_code_files_and_detects_source_token(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "code_globs": [{"glob": "*.py", "type": "source", "limit": 10}],
            "source_tokens": [{"token": "fastapi", "label": "FastAPI"}],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 1
    assert any("FastAPI" in f["claim"] for f in manifest["facts"])


def test_collect_code_evidence_respects_glob_limit(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    for i in range(5):
        (evidence_root / f"f{i}.py").write_text("x = 1")
    config = _config(
        tmp_path,
        evidence_sources={"root": str(evidence_root), "code_globs": [{"glob": "*.py", "limit": 2}]},
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2


def test_collect_code_evidence_skips_git_log_when_flag_false(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fail_run(*args, **kwargs):
        raise AssertionError("git should not be called when git_log is False")

    monkeypatch.setattr("subprocess.run", fail_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": False})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["facts"] == []


def test_collect_code_evidence_adds_git_log_facts_when_enabled(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc123 fix bug\ndef456 add feature\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": True})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["facts"]) == 2
    assert all(f["source"] == "git log" for f in manifest["facts"])


def test_collect_code_evidence_falls_back_to_pendiente_fact_on_git_failure(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fake_run(args, **kwargs):
        raise OSError("git not available")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": True})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["facts"] == [
        {
            "classification": "pendiente",
            "claim": "No se pudo obtener git log para la app móvil.",
            "source": "git",
        }
    ]


def test_collect_code_evidence_dedupes_facts(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "a.py").write_text("import fastapi")
    (evidence_root / "b.py").write_text("import fastapi")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "code_globs": [{"glob": "*.py", "limit": 10}],
            "source_tokens": [{"token": "fastapi", "label": "FastAPI"}],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claims = [f["claim"] for f in manifest["facts"] if "FastAPI" in f["claim"]]
    # two files both trigger the same token -> distinct sources, NOT deduped to one
    assert len(claims) == 2
