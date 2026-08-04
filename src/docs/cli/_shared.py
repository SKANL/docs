# src/docs/cli/_shared.py
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from docs.application.asset import AssetService
from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.application.context_pack import ContextPackService
from docs.application.corrections import CorrectionsService
from docs.application.doctor import DoctorService
from docs.application.documents import DocumentService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.generate_visuals import GenerateVisualsService
from docs.application.html_render import HtmlRendererAdapter
from docs.application.ingest import _SOURCE_MANIFEST_NAME, IngestService
from docs.application.pdf_render import PdfRendererAdapter
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.application.revision import RevisionService
from docs.application.status import StatusService
from docs.domain.models.template import Template
from docs.domain.docx_structure import structure_parts
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.workspace import Workspace
from docs.domain.workspace_config import resolve_workspace_roots
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.ingest.content_probe_adapter import FilesystemContentProbeAdapter
from docs.infrastructure.ingest.filesystem_ingest_artifact_writer import FilesystemIngestArtifactWriter
from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.ingest.opendataloader_pdf_adapter import OpendataloaderPdfAdapter
from docs.infrastructure.ingest.pandoc_ingest_adapter import PandocIngestAdapter
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@dataclass(frozen=True)
class ResolvedContext:
    doc_id: str
    config: dict[str, Any]
    template: Template


def _ctx(ctx: typer.Context) -> tuple[Deps, str]:
    """Shared `ctx.obj` unpacking helper (moved from cli/main.py during the
    PR3 composition-root split — cli/commands/*_app.py modules import this
    instead of main.py to avoid a main.py <-> commands.* import cycle)."""
    return ctx.obj["deps"], ctx.obj["doc"]


WORKSPACE_CONFIG_FILENAME = "docs.config.json"


def _load_workspace_config() -> dict[str, str] | None:
    """Best-effort read of `docs.config.json` in cwd (spec: workspace-config
    "Persisted Workspace Configuration"). A malformed file WARNs to stderr and
    is ignored — fail-open, never bricks a command (design.md item A)."""
    path = Path.cwd() / WORKSPACE_CONFIG_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARN: no se pudo leer {path}, se ignora ({exc}).", file=sys.stderr)
        return None


def build_workspace() -> Workspace:
    """Workspace roots: `docs.config.json` (cwd) -> env vars (injectable in
    tests) -> cwd-relative defaults, in that precedence order (spec:
    workspace-config "Config Precedence Resolution"). Legacy hardcoded
    HARNESS_ROOT/documents & templates; no library equivalent (Judgment call
    2)."""
    documents_dir, templates_dir = resolve_workspace_roots(
        _load_workspace_config(), os.environ, (Path("documents"), Path("templates"))
    )
    return Workspace(documents_dir=documents_dir, templates_dir=templates_dir)


class Deps:
    """Composition root — builds every adapter + service exactly as the
    integration-test _service() helpers do, plus config assembly."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace or build_workspace()
        document_repo = JsonDocumentRepository(self.workspace)
        evidence_repo = JsonEvidenceRepository()
        section_repo = JsonSectionRepository(self.workspace)
        source_repo = FilesystemSourceRepository()
        context_repo = JsonContextRepository(self.workspace)
        self.document_repository = document_repo
        self.context_repository = context_repo
        self.source_repository = source_repo

        asset_service = AssetService(FilesystemAssetRepository(), self.workspace)
        evidence_service = EvidenceService(evidence_repo)
        review_service = ReviewService(section_repo)
        collection_service = CollectionService(source_repo, evidence_repo)
        context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
        tool_resolver = SystemToolResolverAdapter()
        docx_assembly_service = DocxRendererAdapter(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
        html_renderer_service = HtmlRendererAdapter(tool_resolver)
        # Stateless (no instance state) -- one instance shared by QaService's
        # existing visual-QA PDF render and PdfRendererAdapter's `--format
        # pdf` conversion, never two separate adapter instances for the same
        # soffice subprocess call (item C-pdf, mirrors the content-probe
        # single-instance pattern below).
        libreoffice_qa_adapter = LibreOfficeQaAdapter()
        pdf_renderer_service = PdfRendererAdapter(docx_assembly_service, libreoffice_qa_adapter)
        self.renderers: dict[str, DocumentRendererPort] = {
            docx_assembly_service.output_format: docx_assembly_service,
            html_renderer_service.output_format: html_renderer_service,
            pdf_renderer_service.output_format: pdf_renderer_service,
        }
        format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
        qa_service = QaService(libreoffice_qa_adapter, format_audit_service)
        # Stateless -- one instance shared by the doctor's manual auto-detect
        # (item E) and ingest's content-based classification (item D, PR4),
        # never a second port/adapter (design.md ADR-D).
        content_probe_adapter = FilesystemContentProbeAdapter()
        doctor_service = DoctorService(
            evidence_repo, asset_service, tool_resolver, content_probe=content_probe_adapter
        )

        pandoc_ingest_adapter = PandocIngestAdapter(tool_resolver)
        pdf_ingest_adapter = OpendataloaderPdfAdapter(tool_resolver)
        md_ingest_adapter = MdNormalizeAdapter()
        ingest_handlers: dict[str, SourceIngestPort] = {
            "docx": pandoc_ingest_adapter,
            "odt": pandoc_ingest_adapter,
            "pdf": pdf_ingest_adapter,
            "md": md_ingest_adapter,
            "txt": md_ingest_adapter,
        }
        # Item F, PR5: guarded import -- pypdfium2/pillow are optional
        # toolchain deps (doctor's `pdf_page_render` capability check, item
        # L). Missing -> `None`, IngestService degrades to WARN + skip
        # (design.md ADR-F), never a hard dependency for the whole CLI.
        try:
            from docs.infrastructure.pdf.pdfium2_pdf_render_adapter import Pdfium2PdfRenderAdapter

            pdf_render_adapter = Pdfium2PdfRenderAdapter()
        except Exception:
            pdf_render_adapter = None
        self.ingest = IngestService(
            FiletypeDetectorAdapter(),
            ingest_handlers,
            writer=FilesystemIngestArtifactWriter(),
            image_metadata=PythonDocxImageMetadataAdapter(),
            content_probe=content_probe_adapter,
            pdf_render=pdf_render_adapter,
        )

        # matplotlib is a hard declared dependency (pyproject.toml), but the
        # import is still guarded (mirrors the pypdfium2 guard above): if it
        # ever fails to import, the "chart" renderer is simply absent from
        # the registry rather than crashing `Deps()` construction (design.md
        # Migration/Rollout: additive/opt-in, never a hard `Deps()` failure).
        self.visual_renderers: dict[str, Any] = {}
        try:
            from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer

            chart_renderer = ChartSvgRenderer()
            self.visual_renderers[chart_renderer.type] = chart_renderer
        except Exception:
            pass

        # `mmdc` is an OPTIONAL, PATH-resolved external toolchain (never a
        # pip/npm dependency of this project) -- unlike the chart renderer,
        # construction never touches `mmdc` itself (resolution happens lazily
        # inside `render()`), so this is always registered; a missing `mmdc`
        # degrades per-visual at render time (WARN+skip, Slice 5), never at
        # `Deps()` construction (mirrors the pypdfium2/matplotlib guard
        # shape above for defense-in-depth against an unexpected import
        # failure).
        try:
            from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer

            mermaid_renderer = MermaidSvgRenderer(tool_resolver)
            self.visual_renderers[mermaid_renderer.type] = mermaid_renderer
        except Exception:
            pass

        # `resvg` is an OPTIONAL, PATH-resolved external toolchain (never a
        # pip/npm dependency of this project) -- construction never touches
        # `resvg` itself (resolution happens lazily inside `rasterize()`), so
        # this is always wired; a missing `resvg` degrades per-visual at
        # render time (WARN+skip, Slice 5), never at `Deps()` construction
        # (mirrors the mermaid-renderer guard shape above for
        # defense-in-depth against an unexpected import failure).
        try:
            from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter

            self.svg_rasterizer: Any = ResvgRasterizerAdapter(tool_resolver)
        except Exception:
            self.svg_rasterizer = None

        # Slice 5b (on-demand-visual-generation): composition-root wiring of
        # the `generate-visuals` pipeline stage. Reuses the SAME
        # `visual_renderers` registry and `svg_rasterizer` built above (no
        # second registry) and the EXISTING `PythonDocxImageMetadataAdapter`
        # (no new dims port, mirrors `ingest.py`'s reuse). Guarded like the
        # renderer/rasterizer blocks above for defense-in-depth -- a missing
        # renderer/rasterizer degrades to per-visual WARN+skip inside the
        # service itself, never a `Deps()` construction failure.
        self.generate_visuals_service: Any = None
        try:
            self.generate_visuals_service = GenerateVisualsService(
                visual_renderers=self.visual_renderers,
                svg_rasterizer=self.svg_rasterizer,
                image_metadata=PythonDocxImageMetadataAdapter(),
                writer=FilesystemIngestArtifactWriter(),
            )
        except Exception:
            self.generate_visuals_service = None

        self.assets = asset_service
        self.evidence = evidence_service
        self.review = review_service
        self.collection = collection_service
        self.context_pack = context_pack_service
        self.docx = docx_assembly_service
        self.format_audit = format_audit_service
        self.qa = qa_service
        self.doctor = doctor_service
        self.documents = DocumentService(document_repo, self.workspace)
        self.corrections = CorrectionsService(section_repo, evidence_repo)
        self.context = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
        self.status = StatusService(section_repo, self.context, review_service, document_repo)
        self.revision = RevisionService(section_repo, review_service, self.context, evidence_repo)
        self.pipeline = PipelineService(
            doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
            review_service, context_pack_service, context_repo, docx_assembly_service,
            format_audit_service, qa_service, self.workspace, self.ingest,
            context_service=self.context,
            generate_visuals_service=self.generate_visuals_service,
        )

    def resolve_renderer(self, config: dict[str, Any]) -> DocumentRendererPort:
        """Resolve the active `DocumentRendererPort` from `config["output"]["format"]`
        (default `"docx"`) against the `renderers` registry built at construction."""
        output_format = config.get("output", {}).get("format", "docx")
        return resolve_renderer(self.renderers, output_format)

    # ── config assembly (migrated resolve_config / load_document) ──────────
    def resolve_context(self, doc: str = "") -> ResolvedContext:
        doc_id = doc or self.document_repository.active_id()
        if not doc_id:
            raise RuntimeError("No hay documento activo. Usa `doc new <id>` o `doc use <id>`.")
        document = self.document_repository.read_document(doc_id)      # Document (extra allowed)
        template = self.document_repository.load_template(document.template)
        merged = _deep_merge(template.model_dump(), document.model_dump())
        merged = _expand_tokens(merged, _standard_tokens(self.workspace, self.workspace.doc_root(doc_id)))
        paths = dict(merged.get("paths", {}))
        paths.update(_computed_paths(self.workspace.doc_root(doc_id)))
        # prompts_dir: per-document default, template/document override wins if set
        paths.setdefault("prompts_dir", str(self.workspace.doc_root(doc_id) / "prompts"))
        merged["paths"] = paths
        merged["doc_id"] = doc_id
        merged["structure"] = _apply_confirmed_placements(
            structure_parts(merged), Path(paths["inbox_dir"])
        )
        return ResolvedContext(doc_id=doc_id, config=merged, template=Template.model_validate(merged))


def resolve_renderer(renderers: dict[str, DocumentRendererPort], output_format: str) -> DocumentRendererPort:
    """Format-registry resolution at the composition root (document-render
    spec: `Format-Registry Resolution at Composition Root`). Raises a clear
    error naming the unsupported format — never falls back to DOCX silently."""
    renderer = renderers.get(output_format)
    if renderer is None:
        available = ", ".join(sorted(renderers)) or "ninguno"
        raise ValueError(
            f"Formato de salida no registrado: '{output_format}'. "
            f"Formatos disponibles: {available}."
        )
    return renderer


def _apply_confirmed_placements(parts: list[dict[str, Any]], inbox_dir: Path) -> list[dict[str, Any]]:
    """CRITICAL-1 fix (PR5 verify): the WRITE half of design.md Decision 6a's
    "confirmation lands TWICE" -- reads confirmed placements' precomputed
    `structure_part` from `inbox/_source-manifest.json` (IngestService's own
    output, `_route_and_queue_assets`) and splices them into the resolved
    document structure, so the EXISTING `structure_parts()` consumer
    (docx_assembly.py/doctor.py) can actually see them. No new consumer.
    """
    manifest_path = inbox_dir / _SOURCE_MANIFEST_NAME
    if not manifest_path.exists():
        return parts
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return parts
    confirmed_parts = [
        placement["structure_part"]
        for placement in manifest.get("placements", [])
        if placement.get("structure_part")
    ]
    if not confirmed_parts:
        return parts
    parts = list(parts)
    for part in confirmed_parts:
        if part.get("type") == "cover_from_asset":
            # A confirmed cover REPLACES whatever cover the template already
            # declared -- cover_from_template OR its own cover_from_asset (the
            # real reporte-estadia-tic declares the latter, and filtering only
            # cover_from_template left the document with two covers). There is
            # exactly one cover.
            parts = [
                p
                for p in parts
                if p.get("type") not in ("cover_from_template", "cover_from_asset")
            ]
            parts.insert(0, part)
        else:
            # embed_docx ("back" kind) -- appended after the sections part.
            parts.append(part)
    return parts


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def _expand_tokens(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _expand_tokens(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_tokens(v, tokens) for v in value]
    if isinstance(value, str):
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
    return value


def _standard_tokens(workspace: Workspace, doc_root: Path) -> dict[str, str]:
    # Harness-global tokens have no library equivalent (Judgment call 2);
    # expand only what the workspace/cwd can supply. Unresolved tokens stay literal.
    # `{doc_root}`/`{inbox_dir}` are per-document: a template's source paths point
    # into the document's OWN inbox, since every document is an isolated workspace
    # and its material arrives by being dropped there.
    return {
        "{templates_dir}": str(workspace.templates_dir.resolve()),
        "{documents_dir}": str(workspace.documents_dir.resolve()),
        "{doc_root}": str(doc_root.resolve()),
        "{inbox_dir}": str((doc_root / "inbox").resolve()),
        "{cwd}": str(Path.cwd().resolve()),
    }


def _computed_paths(doc_root: Path) -> dict[str, str]:
    sections = doc_root / "sections"
    context = doc_root / "context"
    corrections = doc_root / "corrections"
    output = doc_root / "output"
    return {
        "context_dir": str(context),
        "context_index": str(context / "index.json"),
        "context_requests": str(context / "_requests.md"),
        "assets_dir": str(doc_root / "assets"),
        "inbox_dir": str(doc_root / "inbox"),
        "sections_dir": str(sections),
        "source_manifest": str(sections / "source-manifest.json"),
        "issues_manifest": str(sections / "issues-manifest.json"),
        "code_evidence_manifest": str(sections / "code-evidence-manifest.json"),
        "rules_manifest": str(sections / "manual-rules.json"),
        "fact_ledger": str(sections / "00-fact-ledger.md"),
        "corrections_inbox_dir": str(corrections / "inbox"),
        "corrections_applied": str(corrections / "applied.json"),
        "output_draft_dir": str(output / "draft"),
        "output_final_dir": str(output / "final"),
        "output_qa_dir": str(output / "qa"),
        "runs_dir": str(doc_root / "runs"),
    }


def emit_result(result: Any, as_json: bool) -> None:
    """Migrated _emit_result (3152-3157). Prints to stdout."""
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
