# tests/integration/test_docx_assembly_service.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from docx import Document

from docs.application.asset import AssetService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


def _pandoc_styled_docx(tmp_path: Path, text: str, name: str) -> Path:
    # A real-world template/cover .docx is a Word document with named styles
    # that match pandoc's docx output (e.g. "First Paragraph", "Body Text") —
    # not a blank python-docx Document(). Generating it via pandoc itself
    # keeps these tests on the realistic path: pandoc always stamps a
    # document's first paragraph with "First Paragraph", a style Word's blank
    # template doesn't define. Mapping/importing missing styles onto an
    # arbitrary template is Slice 11b's `safe_style_name` (stubbed as a no-op
    # in this slice), so a blank-template happy path is not achievable here.
    seed = tmp_path / f"_seed_{name}.md"
    seed.write_text(f"{text}\n", encoding="utf-8")
    target = tmp_path / name
    subprocess.run([shutil.which("pandoc"), str(seed), "-o", str(target)], check=True)
    return target


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def asset_service(workspace: Workspace) -> AssetService:
    return AssetService(FilesystemAssetRepository(), workspace)


@pytest.fixture
def service(asset_service: AssetService) -> DocxRendererAdapter:
    return DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())


# --- DocumentRendererPort contract ----------------------------------------------


def test_docx_renderer_adapter_declares_docx_output_format(service):
    assert service.output_format == "docx"


def test_docx_renderer_adapter_satisfies_document_renderer_port(service: DocumentRendererPort):
    assert service.output_format == "docx"
    assert service.stage_plan() == [
        ("build-docx", True),
        ("format-audit-docx", True),
        ("qa-docx", True),
    ]


def test_docx_renderer_adapter_resolves_via_registry_by_format(asset_service):
    from docs.cli._shared import resolve_renderer

    adapter = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())
    registry = {"docx": adapter}
    resolved = resolve_renderer(registry, "docx")
    assert resolved is adapter


def test_resolve_renderer_raises_clear_error_on_unregistered_format(asset_service):
    from docs.cli._shared import resolve_renderer

    adapter = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())
    registry = {"docx": adapter}
    with pytest.raises(ValueError, match="pdf"):
        resolve_renderer(registry, "pdf")


# --- _resolve_cover_asset_path ------------------------------------------------


def test_resolve_cover_asset_path_returns_none_when_no_cover_from_asset_part(service):
    parts = [{"type": "cover_from_template"}, {"type": "sections"}]
    assert service._resolve_cover_asset_path("doc-1", parts) is None


def test_resolve_cover_asset_path_ignores_parts_after_sections(service):
    parts = [{"type": "sections"}, {"type": "cover_from_asset", "asset": "cover"}]
    assert service._resolve_cover_asset_path("doc-1", parts) is None


def test_resolve_cover_asset_path_uses_asset_service_with_given_doc_id(workspace, asset_service, service):
    cover_dir = workspace.assets_dir("doc-1")
    cover_dir.mkdir(parents=True)
    Document().save(cover_dir / "cover.docx")

    parts = [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}]
    result = service._resolve_cover_asset_path("doc-1", parts)
    assert result == asset_service.asset_path("doc-1", "cover")


def test_resolve_cover_asset_path_defaults_asset_name_to_cover(workspace, service):
    cover_dir = workspace.assets_dir("doc-1")
    cover_dir.mkdir(parents=True)
    Document().save(cover_dir / "cover.docx")

    parts = [{"type": "cover_from_asset"}, {"type": "sections"}]
    assert service._resolve_cover_asset_path("doc-1", parts) == cover_dir / "cover.docx"


def test_resolve_cover_asset_path_isolates_by_doc_id(workspace, service):
    doc1_dir = workspace.assets_dir("doc-1")
    doc1_dir.mkdir(parents=True)
    Document().save(doc1_dir / "cover.docx")
    doc2_dir = workspace.assets_dir("doc-2")
    doc2_dir.mkdir(parents=True)
    Document().save(doc2_dir / "cover.docx")

    parts = [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}]
    result_1 = service._resolve_cover_asset_path("doc-1", parts)
    result_2 = service._resolve_cover_asset_path("doc-2", parts)
    assert result_1 == doc1_dir / "cover.docx"
    assert result_2 == doc2_dir / "cover.docx"
    assert result_1 != result_2


# --- _resolve_embed_paths ------------------------------------------------------


def test_resolve_embed_paths_resolves_front_assets(workspace, service):
    assets_dir = workspace.assets_dir("doc-1")
    assets_dir.mkdir(parents=True)
    Document().save(assets_dir / "front.docx")

    parts = [{"type": "embed_docx", "asset": "front"}, {"type": "sections"}]
    result = service._resolve_embed_paths("doc-1", parts, "front")
    assert result == [assets_dir / "front.docx"]


def test_resolve_embed_paths_resolves_back_assets(workspace, service):
    assets_dir = workspace.assets_dir("doc-1")
    assets_dir.mkdir(parents=True)
    Document().save(assets_dir / "back.docx")

    parts = [{"type": "sections"}, {"type": "embed_docx", "asset": "back"}]
    result = service._resolve_embed_paths("doc-1", parts, "back")
    assert result == [assets_dir / "back.docx"]


def test_resolve_embed_paths_ignores_non_embed_parts(service):
    parts = [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}]
    assert service._resolve_embed_paths("doc-1", parts, "front") == []


def test_resolve_embed_paths_raises_when_asset_missing(service):
    parts = [{"type": "embed_docx", "asset": "missing"}, {"type": "sections"}]
    with pytest.raises(FileNotFoundError):
        service._resolve_embed_paths("doc-1", parts, "front")


def test_resolve_embed_paths_isolates_by_doc_id(workspace, service):
    doc1_assets = workspace.assets_dir("doc-1")
    doc1_assets.mkdir(parents=True)
    Document().save(doc1_assets / "front.docx")

    parts = [{"type": "embed_docx", "asset": "front"}, {"type": "sections"}]
    result = service._resolve_embed_paths("doc-1", parts, "front")
    assert result == [doc1_assets / "front.docx"]
    with pytest.raises(FileNotFoundError):
        service._resolve_embed_paths("doc-2", parts, "front")


# --- assemble ------------------------------------------------------------------


def test_assemble_resolves_cover_asset_path_via_asset_service(tmp_path, workspace, service):
    cover_dir = workspace.assets_dir("doc-1")
    cover_dir.mkdir(parents=True)
    cover = Document()
    cover.add_paragraph("COVER MARKER")
    cover.save(cover_dir / "cover.docx")

    config = {"structure": [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}]}
    body = tmp_path / "body.docx"
    Document().save(body)
    output = tmp_path / "out.docx"

    service.assemble("doc-1", config, body, output)

    assert output.exists()
    result = Document(str(output))
    assert any("COVER MARKER" in p.text for p in result.paragraphs)


def test_assemble_raises_when_embed_asset_missing(tmp_path, service):
    config = {"structure": [{"type": "embed_docx", "asset": "missing"}, {"type": "sections"}]}
    body = tmp_path / "body.docx"
    Document().save(body)
    output = tmp_path / "out.docx"

    with pytest.raises(FileNotFoundError):
        service.assemble("doc-1", config, body, output)


def test_assemble_resolves_and_passes_embed_paths_to_port(tmp_path, workspace, service):
    # docxcompose is now a declared, installed dependency (PR1 quick-debt fix);
    # embedding the front asset must succeed end-to-end, proving doc_id-threaded
    # asset resolution reaches real docxcompose composition without error.
    assets_dir = workspace.assets_dir("doc-1")
    assets_dir.mkdir(parents=True)
    Document().save(assets_dir / "front.docx")

    config = {"structure": [{"type": "embed_docx", "asset": "front"}, {"type": "sections"}]}
    body = tmp_path / "body.docx"
    Document().save(body)
    output = tmp_path / "out.docx"

    service.assemble("doc-1", config, body, output)

    assert output.exists()
    Document(str(output))  # must open without raising


# --- _strip_frontmatter_to_temp -------------------------------------------------


def test_strip_frontmatter_to_temp_removes_frontmatter_block(tmp_path, service):
    section = tmp_path / "001-resumen.md"
    section.write_text('---\n{"title": "Resumen"}\n---\n# Resumen\n\nCuerpo.\n', encoding="utf-8")

    stripped = service._strip_frontmatter_to_temp([section])

    assert len(stripped) == 1
    assert stripped[0] != section
    assert stripped[0].read_text(encoding="utf-8") == "# Resumen\n\nCuerpo.\n"


def test_strip_frontmatter_to_temp_preserves_content_without_frontmatter(tmp_path, service):
    section = tmp_path / "001-resumen.md"
    section.write_text("# Resumen\n\nCuerpo.\n", encoding="utf-8")

    stripped = service._strip_frontmatter_to_temp([section])
    assert stripped[0].read_text(encoding="utf-8") == "# Resumen\n\nCuerpo.\n"


def test_strip_frontmatter_to_temp_handles_multiple_sections_in_order(tmp_path, service):
    first = tmp_path / "001-resumen.md"
    first.write_text('---\n{"title": "Resumen"}\n---\nUno.\n', encoding="utf-8")
    second = tmp_path / "002-intro.md"
    second.write_text("Dos.\n", encoding="utf-8")

    stripped = service._strip_frontmatter_to_temp([first, second])

    assert [path.read_text(encoding="utf-8") for path in stripped] == ["Uno.\n", "Dos.\n"]


# --- build ----------------------------------------------------------------------


def test_build_raises_when_pandoc_unavailable(tmp_path, monkeypatch, service):
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = {"sections": [], "paths": {"sections_dir": str(tmp_path), "output_draft_dir": str(tmp_path)}}
    with pytest.raises(RuntimeError, match="Pandoc"):
        service.build("doc-1", config)


def test_build_raises_when_no_markdown_sections_exist(tmp_path, service):
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(tmp_path / "sections"), "output_draft_dir": str(tmp_path / "draft")},
    }
    (tmp_path / "sections").mkdir()
    with pytest.raises(RuntimeError, match="No hay secciones"):
        service.build("doc-1", config)


# --- config-driven output names (PR4: move hardcoded doc names to config) ------


def test_build_default_output_names_are_backward_compatible(tmp_path, service):
    # No config["output"] key at all — existing fixtures/callers keep working
    # with the same "tesina-draft.docx"/"tesina-body.docx" defaults as before.
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(tmp_path / "sections"), "output_draft_dir": str(tmp_path / "draft")},
    }
    (tmp_path / "sections").mkdir()
    with pytest.raises(RuntimeError, match="No hay secciones"):
        service.build("doc-1", config)
    assert service._draft_docx_name(config) == "tesina-draft.docx"
    assert service._body_docx_name(config) == "tesina-body.docx"


def test_build_uses_configured_output_names_when_present(service):
    config = {"output": {"draft_name": "custom-draft.docx", "body_name": "custom-body.docx"}}
    assert service._draft_docx_name(config) == "custom-draft.docx"
    assert service._body_docx_name(config) == "custom-body.docx"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_produces_docx_at_configured_draft_and_body_names(tmp_path, service):
    # Behavior-level proof for the config-driven output names (fresh-context
    # review finding: the private-helper-only test above would not have
    # caught application/pipeline.py's audit/QA stages still hardcoding the
    # default name — this test exercises the real build() end-to-end).
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nContenido.\n", encoding="utf-8")
    template = _pandoc_styled_docx(tmp_path, "Plantilla.", "template.docx")

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {
            "sections_dir": str(sections_dir),
            "output_draft_dir": str(draft_dir),
            "template_docx": str(template),
        },
        "output": {"draft_name": "custom-draft.docx", "body_name": "custom-body.docx"},
    }

    output = service.build("doc-1", config)

    assert output == draft_dir / "custom-draft.docx"
    assert output.exists()
    assert (draft_dir / "custom-body.docx").exists()
    assert not (draft_dir / "tesina-draft.docx").exists()
    assert not (draft_dir / "tesina-body.docx").exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_produces_docx_with_default_output_path(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text(
        "# Resumen\n\nContenido del resumen.\n", encoding="utf-8"
    )
    template = _pandoc_styled_docx(tmp_path, "Plantilla.", "template.docx")

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {
            "sections_dir": str(sections_dir),
            "output_draft_dir": str(draft_dir),
            "template_docx": str(template),
        },
    }

    output = service.build("doc-1", config)

    assert output == draft_dir / "tesina-draft.docx"
    assert output.exists()
    document = Document(str(output))
    assert any("Contenido del resumen" in p.text for p in document.paragraphs)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_writes_to_custom_output_path_when_given(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nTexto.\n", encoding="utf-8")
    template = _pandoc_styled_docx(tmp_path, "Plantilla.", "template.docx")

    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {
            "sections_dir": str(sections_dir),
            "output_draft_dir": str(draft_dir),
            "template_docx": str(template),
        },
    }
    custom_output = tmp_path / "custom" / "final.docx"

    output = service.build("doc-1", config, output=custom_output)

    assert output == custom_output
    assert output.exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_skips_sections_with_no_markdown_file_on_disk(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nTexto.\n", encoding="utf-8")
    template = _pandoc_styled_docx(tmp_path, "Plantilla.", "template.docx")

    config = {
        "sections": [
            {"id": "resumen", "order": 1},
            {"id": "no-existe", "order": 2},
        ],
        "paths": {
            "sections_dir": str(sections_dir),
            "output_draft_dir": str(draft_dir),
            "template_docx": str(template),
        },
    }

    output = service.build("doc-1", config)
    assert output.exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_resolves_cover_asset_via_asset_service_with_doc_id(tmp_path, workspace, service):
    cover_dir = workspace.assets_dir("doc-1")
    cover_dir.mkdir(parents=True)
    _pandoc_styled_docx(cover_dir, "COVER FROM BUILD", "cover.docx")

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    draft_dir = tmp_path / "draft"
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nTexto.\n", encoding="utf-8")

    config = {
        "structure": [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}],
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(draft_dir)},
    }

    output = service.build("doc-1", config)
    document = Document(str(output))
    assert any("COVER FROM BUILD" in p.text for p in document.paragraphs)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_produces_working_toc_field_not_literal_placeholder(tmp_path, service):
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nContenido.\n", encoding="utf-8")
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
        "structure": [{"type": "cover_from_template"}, {"type": "toc"}, {"type": "sections"}],
    }

    output = service.build("tesina-demo", config)
    result = Document(str(output))
    assert not any(p.text.strip() == "[[TOC]]" for p in result.paragraphs)
    assert any('w:fldCharType="begin"' in p._p.xml for p in result.paragraphs)
