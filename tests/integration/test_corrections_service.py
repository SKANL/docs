# tests/integration/test_corrections_service.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application.corrections import CorrectionsService
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return CorrectionsService(JsonSectionRepository(workspace), JsonEvidenceRepository()), workspace


def _config(tmp_path, sections):
    return {
        "paths": {
            "corrections_inbox_dir": str(tmp_path / "inbox"),
            "corrections_applied": str(tmp_path / "state" / "applied.json"),
        },
        "sections": sections,
    }


def test_apply_corrections_returns_zero_when_inbox_is_empty(tmp_path):
    service, _ = _service(tmp_path)
    config = _config(tmp_path, [{"id": "intro", "order": 1}])
    assert service.apply_corrections("doc1", config) == 0


def test_apply_corrections_replaces_text_and_records_applied_entry(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    count = service.apply_corrections("doc1", config)

    assert count == 1
    updated = section_repo.read_raw_text(section_repo.section_path("doc1", 1, "intro"))
    assert updated == "Hola gente"
    applied_state = json.loads(Path(config["paths"]["corrections_applied"]).read_text(encoding="utf-8"))
    assert applied_state["applied"][0]["id"] == "c1"


def test_apply_corrections_skips_already_applied_ids(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    service.apply_corrections("doc1", config)
    second_count = service.apply_corrections("doc1", config)

    assert second_count == 0


def test_apply_corrections_raises_when_expected_hash_does_not_match(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text(
        "id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\nexpected_hash: deadbeef\n", encoding="utf-8"
    )
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    with pytest.raises(RuntimeError, match="esperaba hash deadbeef"):
        service.apply_corrections("doc1", config)


def test_apply_corrections_falls_back_to_glob_match_when_canonical_path_missing(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    # Write under a different order than the config declares, forcing the fallback glob.
    section_repo.write_section("doc1", 9, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    count = service.apply_corrections("doc1", config)

    assert count == 1
    updated = section_repo.read_raw_text(section_repo.section_path("doc1", 9, "intro"))
    assert updated == "Hola gente"


def test_apply_corrections_raises_when_find_text_not_present(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: ausente\nreplace: x\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    with pytest.raises(RuntimeError, match="No se encontró texto objetivo"):
        service.apply_corrections("doc1", config)
