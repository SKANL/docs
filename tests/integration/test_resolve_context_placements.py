# tests/integration/test_resolve_context_placements.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.cli._shared import Deps
from docs.domain.docx_structure import structure_parts

_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": False}],
    "section_contracts": {"introduccion": {}},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    templates = tmp_path / "templates"
    documents.mkdir()
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def _write_confirmed_cover_placement(inbox_dir: Path) -> None:
    inbox_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": 1,
        "sources": [],
        "duplicates": [],
        "placements": [
            {
                "relative_path": "cover.docx",
                "proposed_kind": "cover",
                "confirmed_placement": "cover",
                "routed": True,
                "structure_part": {"type": "cover_from_asset", "asset": "cover.docx"},
            }
        ],
    }
    (inbox_dir / "_source-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


def test_confirmed_cover_placement_is_usable_by_assembly(workspace):
    """Spec: asset-management, "Confirmed placement is recorded and usable"
    -- assembly must be able to reference the asset at its confirmed
    placement. Reproduces the verifier's exact check: call the REAL,
    unedited `structure_parts(config)` consumer directly against a resolved
    document config, after externally confirming a cover placement."""
    deps = Deps()
    deps.documents.create("doc1", "tesina")
    inbox_dir = deps.workspace.doc_root("doc1") / "inbox"
    _write_confirmed_cover_placement(inbox_dir)

    resolved = deps.resolve_context("doc1")
    parts = structure_parts(resolved.config)

    cover_parts = [p for p in parts if p.get("type") == "cover_from_asset"]
    assert cover_parts == [{"type": "cover_from_asset", "asset": "cover.docx"}]


def test_no_confirmed_placement_leaves_default_structure_untouched(workspace):
    deps = Deps()
    deps.documents.create("doc2", "tesina")

    resolved = deps.resolve_context("doc2")
    parts = structure_parts(resolved.config)

    assert not any(p.get("type") == "cover_from_asset" for p in parts)
    assert parts[0]["type"] == "cover_from_template"
