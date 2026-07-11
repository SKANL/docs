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


def test_confirmed_cover_replaces_a_template_declared_cover_from_asset(workspace, tmp_path):
    """A template may already declare its own `cover_from_asset` (the real
    reporte-estadia-tic does). A confirmed cover must REPLACE it, not stack a
    second one -- a document has exactly one cover. Found against the real
    template: the resolved structure came back with two cover parts."""
    templates = tmp_path / "templates"
    template = dict(_TEMPLATE)
    template["structure"] = [
        {"type": "cover_from_asset", "asset": "cover"},
        {"type": "sections"},
    ]
    (templates / "conportada.json").write_text(json.dumps(template), encoding="utf-8")

    deps = Deps()
    deps.documents.create("doc3", "conportada")
    _write_confirmed_cover_placement(deps.workspace.doc_root("doc3") / "inbox")

    parts = structure_parts(deps.resolve_context("doc3").config)

    assert [p for p in parts if p.get("type") == "cover_from_asset"] == [
        {"type": "cover_from_asset", "asset": "cover.docx"}
    ]


def test_no_confirmed_placement_leaves_default_structure_untouched(workspace):
    deps = Deps()
    deps.documents.create("doc2", "tesina")

    resolved = deps.resolve_context("doc2")
    parts = structure_parts(resolved.config)

    assert not any(p.get("type") == "cover_from_asset" for p in parts)
    assert parts[0]["type"] == "cover_from_template"


def test_doc_root_and_inbox_dir_tokens_expand_in_template_paths(workspace, tmp_path):
    """A template's source paths point into the document's OWN inbox -- each
    document is an isolated workspace. Found against the real
    reporte-estadia-tic, whose paths carried an unexpanded `{tesina_root}`
    from the pre-inbox layout, so `doctor` failed on a literal token."""
    templates = tmp_path / "templates"
    template = dict(_TEMPLATE)
    template["paths"] = {"manual_dir": "{inbox_dir}/guides/manual", "root": "{doc_root}"}
    (templates / "contokens.json").write_text(json.dumps(template), encoding="utf-8")

    deps = Deps()
    deps.documents.create("doc4", "contokens")
    doc_root = deps.workspace.doc_root("doc4")

    paths = deps.resolve_context("doc4").config["paths"]

    # Compared as Path, not str: token expansion splices a resolved Windows path
    # into a forward-slash template value, and every consumer reads it via Path().
    assert Path(paths["manual_dir"]) == (doc_root / "inbox" / "guides" / "manual").resolve()
    assert Path(paths["root"]) == doc_root.resolve()
