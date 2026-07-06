# src/docs/application/docx_assembly.py
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.application.output_names import resolve_body_docx_name, resolve_draft_docx_name
from docs.domain.docx_structure import sections_index, structure_parts
from docs.domain.markdown_text import split_frontmatter
from docs.domain.ports.docx_assembly_port import DocxAssemblyPort
from docs.domain.ports.tool_resolver_port import ToolResolverPort


class DocxRendererAdapter:
    """`DocumentRendererPort` implementation for DOCX output (PR4 rename of
    the former `DocxAssemblyService` — behavior unchanged, only the hardcoded
    draft/body doc names now come from `config["output"]`)."""

    output_format = "docx"

    def __init__(self, port: DocxAssemblyPort, asset_service: AssetService, tool_resolver: ToolResolverPort) -> None:
        self.port = port
        self.asset_service = asset_service
        self.tool_resolver = tool_resolver

    def stage_plan(self) -> list[tuple[str, bool]]:
        return [
            ("build-docx", True),
            ("format-audit-docx", True),
            ("qa-docx", True),
        ]

    def _draft_docx_name(self, config: dict[str, Any]) -> str:
        return resolve_draft_docx_name(config)

    def _body_docx_name(self, config: dict[str, Any]) -> str:
        return resolve_body_docx_name(config)

    def _resolve_cover_asset_path(self, doc_id: str, parts: list[dict[str, Any]]) -> Path | None:
        leading = parts[: sections_index(parts)]
        for part in leading:
            if part.get("type") == "cover_from_asset":
                return self.asset_service.asset_path(doc_id, part.get("asset", "cover"))
        return None

    def _resolve_embed_paths(self, doc_id: str, parts: list[dict[str, Any]], region: str) -> list[Path]:
        idx = sections_index(parts)
        chosen = parts[:idx] if region == "front" else parts[idx + 1 :]
        paths: list[Path] = []
        for part in chosen:
            if part.get("type") != "embed_docx":
                continue
            path = self.asset_service.asset_path(doc_id, part.get("asset", ""))
            if not path.exists():
                raise FileNotFoundError(
                    f"embed_docx referencia un asset inexistente: {part.get('asset')} ({path})."
                )
            paths.append(path)
        return paths

    def assemble(self, doc_id: str, config: dict[str, Any], body_docx: Path, output_docx: Path) -> None:
        parts = structure_parts(config)
        cover_asset_path = self._resolve_cover_asset_path(doc_id, parts)
        front = self._resolve_embed_paths(doc_id, parts, "front")
        back = self._resolve_embed_paths(doc_id, parts, "back")
        self.port.assemble(
            config,
            body_docx,
            output_docx,
            cover_asset_path=cover_asset_path,
            embed_front_paths=front,
            embed_back_paths=back,
        )

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path:
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
        if not pandoc:
            raise RuntimeError("Pandoc no está disponible en PATH. Instálalo y vuelve a ejecutar `build-docx`.")

        sections = sorted(config["sections"], key=lambda item: item["order"])
        sections_dir = Path(config["paths"]["sections_dir"])
        existing_sections = [
            sections_dir / f"{section['order']:03d}-{section['id']}.md"
            for section in sections
            if (sections_dir / f"{section['order']:03d}-{section['id']}.md").exists()
        ]
        if not existing_sections:
            raise RuntimeError("No hay secciones Markdown para ensamblar. Ejecuta `build-section resumen` primero.")

        output_dir = Path(config["paths"]["output_draft_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output or output_dir / self._draft_docx_name(config)
        body_docx = output_dir / self._body_docx_name(config)

        # Legacy strips YAML/JSON frontmatter from each section before invoking
        # pandoc. `split_frontmatter` (docs.domain.markdown_text) already matches
        # that behavior byte-for-byte; reused here rather than re-derived.
        stripped_sections = self._strip_frontmatter_to_temp(existing_sections)
        self.port.render_pandoc(pandoc, stripped_sections, body_docx)
        self.assemble(doc_id, config, body_docx, output)
        self.port.insert_toc_field(output)
        return output

    def _strip_frontmatter_to_temp(self, sections: list[Path]) -> list[Path]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="docs_sections_"))
        stripped: list[Path] = []
        for section_path in sections:
            _metadata, body = split_frontmatter(section_path.read_text(encoding="utf-8"))
            target = tmp_dir / section_path.name
            target.write_text(body, encoding="utf-8")
            stripped.append(target)
        return stripped
