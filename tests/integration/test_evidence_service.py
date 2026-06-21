# tests/integration/test_evidence_service.py
import json
from pathlib import Path

import pytest

from docs.application.evidence import EvidenceService
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def service() -> EvidenceService:
    return EvidenceService(JsonEvidenceRepository())


def _config(tmp_path: Path, **overrides) -> dict:
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    extracted_dir = tmp_path / "extracted"
    config = {
        "paths": {
            "manual_dir": str(manual_dir),
            "extracted_dir": str(extracted_dir),
            "rules_manifest": str(tmp_path / "manual-rules.json"),
        },
        "section_contracts": {},
        "advisor_overrides": [],
        "strict_policy": {},
        "preliminaries": {},
        "format": {},
        "apa7": {},
        "privacy": {},
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


def test_build_rules_returns_manifest_path(tmp_path: Path, service):
    config = _config(tmp_path)
    result_path = service.build_rules(config)
    assert result_path == Path(config["paths"]["rules_manifest"])
    assert result_path.exists()


def test_build_rules_hashes_manual_markdown_files(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Introducción\n\nTexto inicial.")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1
    entry = manifest["manual_files"][0]
    assert entry["name"] == "00-intro.md"
    assert entry["headings"] == ["Introducción"]
    assert len(entry["sha256"]) == 64


def test_build_rules_manual_files_sorted_by_filename(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "01-b.md").write_text("# B")
    (manual_dir / "00-a.md").write_text("# A")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["manual_files"]] == ["00-a.md", "01-b.md"]


def test_build_rules_skips_missing_manual_pdf_and_example_pdf(tmp_path: Path, service):
    config = _config(tmp_path, paths={"manual_pdf": "", "example_pdf": str(tmp_path / "missing.pdf")})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_includes_existing_manual_pdf_as_traceability(tmp_path: Path, service):
    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    config = _config(tmp_path, paths={"manual_pdf": str(pdf_path)})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["traceability"]) == 1
    entry = manifest["traceability"][0]
    assert entry["type"] == "institutional_pdf"
    assert entry["size"] == pdf_path.stat().st_size


def test_build_rules_includes_extracted_dir_md_and_json_files(tmp_path: Path, service):
    config = _config(tmp_path)
    extracted_dir = Path(config["paths"]["extracted_dir"])
    extracted_dir.mkdir()
    (extracted_dir / "notes.md").write_text("notas")
    (extracted_dir / "data.json").write_text("{}")
    (extracted_dir / "image.png").write_text("x")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = {entry["path"].split("/")[-1] for entry in manifest["traceability"]}
    assert entries == {"notes.md", "data.json"}
    assert all(e["type"] == "extracted_traceability" for e in manifest["traceability"])


def test_build_rules_skips_extracted_dir_entirely_when_absent(tmp_path: Path, service):
    config = _config(tmp_path)  # extracted_dir not created
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_computes_contract_hashes(tmp_path: Path, service):
    contracts = {"intro": {"title": "Introducción", "required_content": ["objetivo"]}}
    config = _config(tmp_path, section_contracts=contracts)
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["section_contracts"] == contracts
    assert set(manifest["contract_hashes"]) == {"intro"}
    assert len(manifest["contract_hashes"]["intro"]) == 64


def test_build_rules_carries_policy_apa7_privacy_preliminaries_format(tmp_path: Path, service):
    config = _config(
        tmp_path,
        strict_policy={"draft": {"allow_pending": True}, "strict": {"allow_pending": False}},
        apa7={"enabled": True},
        privacy={"redact": True},
        preliminaries={"roman_pagination": {"enabled": True}},
        format={"page_margins_cm": {}},
        advisor_overrides=[{"id": "x", "status": "active"}],
    )
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["policy"]["draft_mode"] == {"allow_pending": True}
    assert manifest["policy"]["strict_mode"] == {"allow_pending": False}
    assert manifest["apa7"] == {"enabled": True}
    assert manifest["privacy"] == {"redact": True}
    assert manifest["preliminaries"] == {"roman_pagination": {"enabled": True}}
    assert manifest["format"] == {"page_margins_cm": {}}
    assert manifest["advisor_overrides"] == [{"id": "x", "status": "active"}]
    assert manifest["policy"]["advisor_overrides"] == [{"id": "x", "status": "active"}]


def test_build_rules_second_call_with_unchanged_inputs_does_not_rewrite_generated_at(tmp_path: Path, service):
    config = _config(tmp_path)
    path = service.build_rules(config)
    first = json.loads(path.read_text(encoding="utf-8"))
    path = service.build_rules(config)
    second = json.loads(path.read_text(encoding="utf-8"))
    assert first["generated_at"] == second["generated_at"]


def test_build_rules_second_call_with_new_manual_file_rewrites_manifest(tmp_path: Path, service):
    config = _config(tmp_path)
    service.build_rules(config)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-new.md").write_text("# Nuevo")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1
