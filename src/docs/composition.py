# src/docs/composition.py
# ponytail: `owned_directory_lock`, `directory_handle_guard` and `atomic_write_text`
# are re-exported from here so cli/sidecar reach them through the root; no wrapper until
# one needs a seam.
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from docs.application.artifact_report_service import ArtifactReportService
from docs.application.asset import AssetService
from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.application.context_pack import ContextPackService
from docs.application.corrections import CorrectionsService
from docs.application.doctor import DoctorService
from docs.application.document_verification import DocumentVerificationService
from docs.application.documents import DocumentService
from docs.application.docx_assembly import DocxRendererAdapter
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.generate_visuals import GenerateVisualsService
from docs.application.html_render import HtmlRendererAdapter
from docs.application.ingest import IngestService
from docs.application.package_publication_service import PackagePublicationService
from docs.application.package_service import PackageService, assert_directory_identity
from docs.application.pdf_render import PdfRendererAdapter
from docs.application.provenance import LedgerFactory, ProvenanceLedgerPort
from docs.application.qa import QaService
from docs.application.render_verification import RenderVerificationService
from docs.application.review import ReviewService
from docs.application.revision import RevisionService
from docs.application.run_history import RunHistoryService, RunRecorderService
from docs.application.section import SectionService
from docs.application.source_pipeline import SourcePipeline
from docs.application.status import StatusService
from docs.application.status_reader import StatusReader
from docs.application.structural_audit import StructuralAuditService
from docs.application.workspace_config import (
    apply_confirmed_placements,
    computed_paths,
    deep_merge,
    expand_tokens,
    load_workspace_config,
    rules_manifest_state,
    standard_tokens,
    try_compile_template,
)
from docs.application.workspaces import WorkspaceRegistry
from docs.domain.docx_structure import structure_parts
from docs.domain.models.template import Template
from docs.domain.ports.atomic_file_port import AtomicFilePort
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.ports.markdown_normalizer_port import MarkdownNormalizerPort
from docs.domain.ports.pdf_classify_port import PdfClassifyPort
from docs.domain.ports.pdf_render_port import PdfRenderPort
from docs.domain.ports.pdf_text_edit_port import PdfTextEditPort
from docs.domain.ports.source_ingest_port import SourceIngestPort
from docs.domain.ports.source_repository import SourceRepository
from docs.domain.ports.svg_rasterizer_port import SvgRasterizerPort
from docs.domain.ports.visual_renderer_port import VisualRendererPort
from docs.domain.workspace import Workspace
from docs.domain.workspace_config import resolve_workspace_roots
from docs.domain.workspace_format import validate_workspace_layout, validate_workspace_marker
from docs.infrastructure.atomic_write import atomic_write_text
from docs.infrastructure.audit.structural_audit_adapter import StructuralAuditAdapter
from docs.infrastructure.docx.deterministic_zip import normalize_docx_zip_timestamps
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.docx.python_docx_image_metadata_adapter import PythonDocxImageMetadataAdapter
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.graph.document_graph_reader import DocumentGraphReader
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.content_probe_adapter import FilesystemContentProbeAdapter
from docs.infrastructure.ingest.filesystem_ingest_artifact_writer import FilesystemIngestArtifactWriter
from docs.infrastructure.ingest.filetype_detector_adapter import FiletypeDetectorAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.ingest.opendataloader_pdf_adapter import OpendataloaderPdfAdapter
from docs.infrastructure.ingest.pandoc_ingest_adapter import PandocIngestAdapter
from docs.infrastructure.locking import directory_handle_guard, owned_directory_lock
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.idempotency import SqliteIdempotencyStore
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository
from docs.infrastructure.persistence.sqlite_runtime import (
    SqliteArtifactStore,
    SqliteFindingStore,
    SqliteGraphStore,
    SqliteJobQueue,
    SqliteLeaseStore,
    SqlitePassportStore,
    SqlitePublicationStore,
    SqliteRunStore,
)
from docs.infrastructure.process.pandoc_runner_adapter import SubprocessPandocRunner
from docs.infrastructure.provenance.ledger import ProvenanceLedger
from docs.infrastructure.tools.tool_capability_detector_adapter import NativeToolCapabilityDetector
from docs.infrastructure.transform.system_transform import AtomicTransform
from docs.infrastructure.verification.render_verification_adapter import RenderVerificationAdapter
from docs.observability import ObservabilityPort, create_observability_from_env
from docs.template_compiler import TemplateIR, source_template


@dataclass(frozen=True)
class ResolvedContext:
    doc_id: str
    config: dict[str, Any]
    template: Template
    template_ir: TemplateIR | None = None


def _validated_workspace(root: Path, documents_dir: Path, templates_dir: Path) -> Workspace:
    """Build a canonical workspace only after its read-only guards pass."""
    validate_workspace_layout(root, documents_dir, templates_dir)
    validate_workspace_marker(root)
    return Workspace(root=root, documents_dir=documents_dir, templates_dir=templates_dir)


def build_workspace() -> Workspace:
    """Resolve and validate workspace roots before exposing them to services.

    Bootstrap commands establish canonical state through their
    dedicated flows. All ordinary config, environment, default, and selected
    workspace resolution paths are read-only and reject an unmarked root before
    any service can construct adapters or create state.
    """
    config = load_workspace_config()
    # A selected local workspace is the CLI's durable source of truth when no
    # explicit per-cwd config or environment override is supplied. This keeps
    # `docs workspace use` aligned with the sidecar and avoids silently
    # operating on the harness checkout's default documents/ directory.
    if config is None and not os.environ.get("DOCS_DOCUMENTS_DIR") and not os.environ.get("DOCS_TEMPLATES_DIR"):
        local_registry = Path.cwd() / ".docs" / "workspaces.json"
        registry = open_workspace_registry(local_registry if local_registry.is_file() else None)
        active = registry.active()
        if active is not None:
            root = Path(str(active["root"])).resolve()
            return _validated_workspace(root, root / "documents", root / "templates")
    documents_dir, templates_dir = resolve_workspace_roots(
        config, os.environ, (Path("documents"), Path("templates"))
    )
    root = Path.cwd()
    resolved_documents = documents_dir.expanduser().resolve()
    resolved_templates = templates_dir.expanduser().resolve()
    if config is None and resolved_documents.parent == resolved_templates.parent:
        # Explicit environment roots can select a canonical sibling workspace
        # without changing cwd. This is exact-parent identity, never a broad
        # common-ancestor inference for legacy split roots.
        root = resolved_documents.parent
    return _validated_workspace(root, documents_dir, templates_dir)


logger = logging.getLogger(__name__)


def open_workspace_registry(registry_path: str | Path | None = None) -> WorkspaceRegistry:
    """Open the workspace registry with the atomic file writer wired in."""
    return WorkspaceRegistry(registry_path, write_text=atomic_write_text)


def open_provenance_ledger(log_path: Path, *, trusted_root: Path | None = None) -> ProvenanceLedgerPort:
    """Open the filesystem provenance ledger stored at ``log_path``."""
    return ProvenanceLedger(log_path, trusted_root=trusted_root)


def open_document_graph_reader(root: Path) -> DocumentGraphReader:
    """Open the read-only, mtime-cached document graph of one workspace root."""
    return DocumentGraphReader(root)


def resolve_workspace_registry(workspace_root: Path) -> WorkspaceRegistry:
    """Prefer the workspace-local registry over the process-wide one.

    A document configured by this cwd must never fall back to the process-wide
    active workspace unless the caller supplied `DOCS_WORKSPACE_REGISTRY`;
    that fallback can enqueue a run for a different project.
    """
    local = workspace_root / ".docs" / "workspaces.json"
    # `None` lets the registry apply its own env-then-home fallback.
    return open_workspace_registry(local if local.is_file() else None)


def resolve_runtime_root(workspace_root: Path) -> Path:
    """Root that owns the durable runtime state: the active workspace, else `workspace_root`."""
    root = workspace_root.resolve()
    active = resolve_workspace_registry(root).active()
    return Path(str(active["root"])).resolve() if active is not None else root


def runtime_state_path(root: Path) -> Path:
    """The one location of a workspace's durable runtime SQLite file."""
    return root / ".docs" / "runtime.sqlite3"


class RuntimeStores:
    """Durable runtime stores for one workspace root, each built on first use.

    Construction creates the SQLite file and schema, so stores stay lazy: a
    caller that only reads runs never touches the queue or lease tables.
    """

    def __init__(self, root: Path) -> None:
        self.state = runtime_state_path(root)

    @cached_property
    def runs(self) -> SqliteRunStore:
        return SqliteRunStore(self.state)

    @cached_property
    def queue(self) -> SqliteJobQueue:
        return SqliteJobQueue(self.state)

    @cached_property
    def passports(self) -> SqlitePassportStore:
        return SqlitePassportStore(self.state)

    @cached_property
    def artifacts(self) -> SqliteArtifactStore:
        return SqliteArtifactStore(self.state)

    @cached_property
    def findings(self) -> SqliteFindingStore:
        return SqliteFindingStore(self.state)

    @cached_property
    def publications(self) -> SqlitePublicationStore:
        return SqlitePublicationStore(self.state)

    @cached_property
    def graph(self) -> SqliteGraphStore:
        return SqliteGraphStore(self.state)

    @cached_property
    def leases(self) -> SqliteLeaseStore:
        return SqliteLeaseStore(self.state)

    @cached_property
    def idempotency(self) -> SqliteIdempotencyStore:
        return SqliteIdempotencyStore(self.state)


@dataclass(init=False)
class ApplicationComposition:
    """Composition root — builds every adapter + service exactly as the
    integration-test _service() helpers do, plus config assembly."""

    workspace: Workspace
    observability: ObservabilityPort
    document_repository: JsonDocumentRepository
    context_repository: ContextRepository
    source_repository: SourceRepository
    renderers: dict[str, DocumentRendererPort]
    markdown_normalizer: MarkdownNormalizerPort
    atomic_file_writer: AtomicFilePort
    svg_rasterizer: SvgRasterizerPort | None
    ingest: IngestService
    visual_renderers: dict[str, VisualRendererPort]
    generate_visuals_service: GenerateVisualsService | None
    pdf_classifier: PdfClassifyPort | None
    pdf_text_editor: PdfTextEditPort | None
    pdf_render: PdfRenderPort | None
    assets: AssetService
    evidence: EvidenceService
    review: ReviewService
    collection: CollectionService
    context_pack: ContextPackService
    docx: DocumentRendererPort
    format_audit: FormatAuditService
    render_verification: RenderVerificationService
    qa: QaService
    doctor: DoctorService
    documents: DocumentService
    corrections: CorrectionsService
    context: ContextService
    section: SectionService
    status: StatusService
    revision: RevisionService
    history: RunHistoryService
    run_recorder: RunRecorderService
    verification: DocumentVerificationService
    structural_audit_service: StructuralAuditService
    artifact_reports: ArtifactReportService
    package_publications: PackagePublicationService
    provenance_ledger: LedgerFactory
    rules_manifest_state: Callable[[dict[str, Any]], tuple[bool, int]]

    def __init__(
        self,
        workspace: Workspace | None = None,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self.workspace = workspace or build_workspace()
        validate_workspace_layout(
            self.workspace.root,
            self.workspace.documents_dir,
            self.workspace.templates_dir,
        )
        validate_workspace_marker(self.workspace.root)
        self.observability: ObservabilityPort = observability or create_observability_from_env()
        self._wire_repositories()
        self._wire_core_services()
        self._wire_renderers_and_quality()
        self._wire_ingest()
        self._wire_visuals()
        self._wire_pdf_translation_tools()
        self._wire_document_services()
        self._wire_delivery()

    def _wire_repositories(self) -> None:
        self.document_repository = JsonDocumentRepository(self.workspace)
        self.evidence_repository = JsonEvidenceRepository()
        self.section_repository = JsonSectionRepository(self.workspace)
        self.source_repository = FilesystemSourceRepository()
        self.context_repository = JsonContextRepository(self.workspace)

    def _wire_core_services(self) -> None:
        self.assets = AssetService(FilesystemAssetRepository(), self.workspace)
        self.evidence = EvidenceService(self.evidence_repository)
        self.review = ReviewService(self.section_repository)
        self.collection = CollectionService(self.source_repository, self.evidence_repository)
        self.context_pack = ContextPackService(
            self.section_repository, self.evidence_repository, self.evidence, self.review
        )
        self.tool_resolver = SystemToolResolverAdapter()
        self.directory_guard = directory_handle_guard
        self.release_lock = owned_directory_lock

    def _wire_renderers_and_quality(self) -> None:
        self.docx = DocxRendererAdapter(PythonDocxAssemblyAdapter(), self.assets, self.tool_resolver)
        html_renderer = HtmlRendererAdapter(self.tool_resolver, SubprocessPandocRunner())
        # Stateless (no instance state) -- one instance shared by QaService's
        # existing visual-QA PDF render and PdfRendererAdapter's `--format
        # pdf` conversion, never two separate adapter instances for the same
        # soffice subprocess call.
        libreoffice_qa_adapter = LibreOfficeQaAdapter()
        pdf_renderer = PdfRendererAdapter(self.docx, libreoffice_qa_adapter)
        self.renderers: dict[str, DocumentRendererPort] = {
            self.docx.output_format: self.docx,
            html_renderer.output_format: html_renderer,
            pdf_renderer.output_format: pdf_renderer,
        }
        self.format_audit = FormatAuditService(PythonDocxAuditAdapter())
        self.render_verification = RenderVerificationService(RenderVerificationAdapter())
        self.structural_audit_service = StructuralAuditService(StructuralAuditAdapter())
        self.qa = QaService(
            libreoffice_qa_adapter, self.format_audit, render_verification_service=self.render_verification
        )
        # Stateless -- one instance shared by the doctor's manual auto-detect
        # and ingest's content-based classification, never a second adapter.
        self._content_probe = FilesystemContentProbeAdapter()
        self.doctor = DoctorService(
            self.evidence_repository, self.assets, self.tool_resolver, content_probe=self._content_probe
        )

    def _wire_ingest(self) -> None:
        pandoc_ingest_adapter = PandocIngestAdapter(self.tool_resolver)
        md_ingest_adapter = MdNormalizeAdapter()
        self.markdown_normalizer = md_ingest_adapter
        self.atomic_file_writer = AtomicFileAdapter()
        ingest_handlers: dict[str, SourceIngestPort] = {
            "docx": pandoc_ingest_adapter,
            "odt": pandoc_ingest_adapter,
            "pdf": OpendataloaderPdfAdapter(self.tool_resolver),
            "md": md_ingest_adapter,
            "txt": md_ingest_adapter,
        }
        # pypdfium2/pillow are optional toolchain deps (doctor's
        # `pdf_page_render` capability check). Missing -> `None`, and
        # IngestService degrades to WARN + skip, never a hard dependency.
        try:
            from docs.infrastructure.pdf.pdfium2_pdf_render_adapter import Pdfium2PdfRenderAdapter

            self.pdf_render = Pdfium2PdfRenderAdapter()
        except Exception as exc:
            logger.debug("PDF page renderer no registrado: %s", exc)
            self.pdf_render = None

        # `resvg` is an OPTIONAL, PATH-resolved external toolchain (never a
        # pip/npm dependency) -- construction never touches `resvg` itself
        # (resolution happens lazily inside `rasterize()`); a missing `resvg`
        # degrades per visual at render time. Built here so `self.ingest`
        # reuses the SAME instance for standalone-SVG figure cataloging.
        try:
            from docs.infrastructure.visuals.resvg_rasterizer_adapter import ResvgRasterizerAdapter

            self.svg_rasterizer: Any = ResvgRasterizerAdapter(self.tool_resolver)
        except Exception as exc:
            logger.debug("SVG rasterizer no registrado: %s", exc)
            self.svg_rasterizer = None

        self.ingest = IngestService(
            FiletypeDetectorAdapter(),
            ingest_handlers,
            writer=FilesystemIngestArtifactWriter(),
            image_metadata=PythonDocxImageMetadataAdapter(),
            content_probe=self._content_probe,
            pdf_render=self.pdf_render,
            svg_rasterizer=self.svg_rasterizer,
        )

    def _wire_visuals(self) -> None:
        # Every renderer is optional: an import failure removes that renderer
        # from the registry instead of failing composition. Degrading is
        # correct, swallowing silently is not, so each failure leaves a trace.
        self.visual_renderers = {}
        try:
            from docs.infrastructure.visuals.chart_svg_renderer import ChartSvgRenderer

            chart_renderer = ChartSvgRenderer()
            self.visual_renderers[chart_renderer.type] = chart_renderer
        except Exception as exc:
            logger.debug("visual renderer no registrado: %s", exc)

        # `mmdc` is an OPTIONAL, PATH-resolved external toolchain; resolution
        # happens lazily inside `render()`, so the renderer is always registered
        # and a missing `mmdc` degrades per visual at render time.
        try:
            from docs.infrastructure.visuals.mermaid_svg_renderer import MermaidSvgRenderer

            mermaid_renderer = MermaidSvgRenderer(self.tool_resolver)
            self.visual_renderers[mermaid_renderer.type] = mermaid_renderer
        except Exception as exc:
            logger.debug("visual renderer no registrado: %s", exc)

        # The `generate-visuals` pipeline stage reuses the SAME registry and
        # rasterizer built above. Without a rasterizer the stage is
        # unavailable and StageProvider reports it as skipped.
        self.generate_visuals_service: Any = None
        if self.svg_rasterizer is not None:
            try:
                self.generate_visuals_service = GenerateVisualsService(
                    visual_renderers=self.visual_renderers,
                    svg_rasterizer=self.svg_rasterizer,
                    image_metadata=PythonDocxImageMetadataAdapter(),
                    writer=FilesystemIngestArtifactWriter(),
                    file_writer=self.atomic_file_writer,
                )
            except Exception as exc:
                logger.debug("generate-visuals no disponible: %s", exc)

    def _wire_pdf_translation_tools(self) -> None:
        # `document-translate` adapters. Both `pypdfium2` and `pdf-inspector`
        # are declared dependencies, but an import failure must cost the
        # TRANSLATE command, not every command in the CLI. `None` means
        # `docs translate` reports why it cannot run.
        self.pdf_classifier = None
        self.pdf_text_editor = None
        try:
            from docs.infrastructure.fonts.dejavu_font_source import DejaVuFontSource
            from docs.infrastructure.pdf.pdf_inspector_classify_adapter import (
                PdfInspectorClassifyAdapter,
            )
            from docs.infrastructure.pdf.pypdfium2_text_edit_adapter import (
                Pypdfium2TextEditAdapter,
            )

            self.pdf_classifier = PdfInspectorClassifyAdapter()
            # Supplies a real face for characters base-14 cannot draw, which
            # would otherwise reach the page as empty boxes.
            self.pdf_text_editor = Pypdfium2TextEditAdapter(DejaVuFontSource())
        except Exception as exc:
            logger.debug("adaptadores de traduccion no registrados: %s", exc)

    def _wire_document_services(self) -> None:
        self.documents = DocumentService(self.document_repository, self.workspace)
        self.corrections = CorrectionsService(self.section_repository, self.evidence_repository)
        self.context = ContextService(self.context_repository, self.document_repository, ContextMarkdownAdapter())
        self.section = SectionService(self.review, self.evidence, self.context_repository)
        self.provenance_ledger = open_provenance_ledger
        self.status = StatusService(
            self.section_repository,
            self.context,
            self.review,
            self.document_repository,
            StatusReader(self.provenance_ledger),
        )
        self.revision = RevisionService(self.section_repository, self.review, self.context, self.evidence_repository)
        self.history = RunHistoryService(self.workspace)
        self.run_recorder = RunRecorderService(self.workspace, self.source_repository)
        self.verification = DocumentVerificationService(
            self.review, self.evidence_repository, self.format_audit, self.qa
        )

    def _wire_delivery(self) -> None:
        self.artifact_reports = ArtifactReportService()
        self.package_publications = PackagePublicationService(
            archive_writer=PackageService(
                lock=owned_directory_lock,
                directory_guard=directory_handle_guard,
                normalize_docx_zip_timestamps=normalize_docx_zip_timestamps,
                assert_directory_identity=assert_directory_identity,
            ),
            lock=owned_directory_lock,
            transform=AtomicTransform(),
            ledger_factory=self.provenance_ledger,
        )
        self.rules_manifest_state = rules_manifest_state

    def build_translate_service(self, memory_dir: Path, pending_file: Path) -> Any:
        """Build a `TranslateService` bound to this run's memory and slot file.

        The adapters are chosen here, in the composition root, like every
        other adapter in this class. Only the two PATHS vary per invocation,
        because the translation memory and the pending-slot file live beside
        the output document.

        Returns `(service, translator)`: the caller needs the translator to
        flush the pending-slot file after the run, and handing it back beats
        widening `TranslationPort` with a method only one adapter has.

        Returns `(None, None)` when the PDF adapters are unavailable, so the
        command can say so instead of raising an import error at the user.
        """
        if self.pdf_classifier is None or self.pdf_text_editor is None:
            return None, None

        from docs.application.translate import TranslateService
        from docs.infrastructure.translate.filesystem_translation_memory import (
            FilesystemTranslationMemory,
        )
        from docs.infrastructure.translate.pending_slot_translator import PendingSlotTranslator

        translator = PendingSlotTranslator(pending_file)
        service = TranslateService(
            classifier=self.pdf_classifier,
            editor=self.pdf_text_editor,
            translator=translator,
            memory=FilesystemTranslationMemory(memory_dir),
        )
        return service, translator

    def create_source_pipeline(self) -> SourcePipeline:
        """Build source preparation from this composition's shared adapters."""
        return SourcePipeline(self.ingest, self.markdown_normalizer, self.atomic_file_writer)

    def create_stage_provider(
        self,
        *,
        config: dict[str, Any],
        output_format: str,
        ensure_assets: Any,
        extra_services: dict[str, Any] | None = None,
    ) -> Any:
        """Register this application's pipeline-stage services and defaults."""
        from docs.application.pipeline_assembly import assemble_stage_provider

        return assemble_stage_provider(
            self,
            config=config,
            output_format=output_format,
            ensure_assets=ensure_assets,
            extra_services=extra_services,
        )

    def create_tool_capability_detector(self, paths: dict[str, object]) -> Any:
        """Bind native tool probing at the composition root."""
        resolvers = {
            "pandoc": self.tool_resolver.resolve_pandoc,
            "soffice": self.tool_resolver.resolve_libreoffice,
            "libreoffice": self.tool_resolver.resolve_libreoffice,
            "java": self.tool_resolver.resolve_java,
            "mmdc": self.tool_resolver.resolve_mmdc,
            "resvg": self.tool_resolver.resolve_resvg,
        }
        return NativeToolCapabilityDetector(
            self.tool_resolver.tool_version,
            executable_resolver=lambda executable, configured: (
                resolvers[executable](configured) if executable in resolvers else None
            ),
            paths=paths,
        )

    def create_pipeline_resources(self, **kwargs: Any) -> Any:
        """Wire concrete pipeline adapters into the application assembler."""
        from docs.application.pipeline_assembly import assemble_pipeline_resources

        paths = kwargs.get("paths", {})
        return assemble_pipeline_resources(
            **kwargs,
            capability_detector=self.create_tool_capability_detector(paths),
            ledger_factory=self.provenance_ledger,
        )

    def create_capability_registry(
        self,
        renderer: Any,
        output_format: str,
        document_root: Path,
        paths: dict[str, object],
    ) -> Any:
        """Build capability diagnostics without exposing adapters to the CLI."""
        from docs.application.document_pipeline import _capabilities_for

        return _capabilities_for(
            renderer,
            output_format,
            document_root,
            paths,
            capability_detector=self.create_tool_capability_detector(paths),
        )

    def create_document_pipeline_service(
        self,
        output_format: str = "docx",
        policy: Any = None,
        document: str = "",
        pipeline_id: str = "document",
        provenance_run_id: str | None = None,
        publication_destination: Path | None = None,
        artifact_path: Path | None = None,
        manifest_path: Path | None = None,
    ) -> Any:
        """Create the application-owned document pipeline use case."""
        from docs.application.document_pipeline import create_document_pipeline_service

        return create_document_pipeline_service(
            self,
            output_format=output_format,
            policy=policy,
            document=document,
            pipeline_id=pipeline_id,
            provenance_run_id=provenance_run_id,
            publication_destination=publication_destination,
            artifact_path=artifact_path,
            manifest_path=manifest_path,
        )

    def create_document_pipeline(
        self,
        *,
        operations: Any,
        expected_outputs: tuple[str, ...],
        destinations: tuple[Path, ...],
        operation: Any,
        capabilities: Any,
        ledger: ProvenanceLedgerPort,
        policy: Any = None,
        run_id_sink: Any = None,
        excluded_stages: frozenset[str] = frozenset(),
        cleanup: Any = None,
        artifact_store: Any = None,
        record_sink: Any = None,
        run_start: Any = None,
    ) -> Any:
        """Assemble the document pipeline at the canonical composition root."""
        from docs.application.pipeline_service import PipelineService, PublicationSpec

        return PipelineService(
            operations=operations,
            publication=PublicationSpec(expected_outputs, destinations, operation),
            capabilities=capabilities,
            ledger=ledger,
            atomic_transform=AtomicTransform(),
            policy=policy,
            run_id_sink=run_id_sink,
            excluded_stages=excluded_stages,
            cleanup=cleanup,
            artifact_store=artifact_store,
            record_sink=record_sink,
            run_start=run_start,
            observability=self.observability,
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
        try_compile_template(template)
        merged = deep_merge(template.model_dump(), document.model_dump())
        merged = expand_tokens(merged, standard_tokens(self.workspace, self.workspace.doc_root(doc_id)))
        paths = dict(merged.get("paths", {}))
        paths.update(computed_paths(self.workspace.doc_root(doc_id)))
        # prompts_dir: per-document default, template/document override wins if set
        paths.setdefault("prompts_dir", str(self.workspace.doc_root(doc_id) / "prompts"))
        merged["paths"] = paths
        merged["doc_id"] = doc_id
        merged["structure"] = apply_confirmed_placements(
            structure_parts(merged), Path(paths["inbox_dir"])
        )
        resolved_template = Template.model_validate(merged)
        resolved_template_ir = try_compile_template(resolved_template)
        return ResolvedContext(
            doc_id=doc_id,
            config=merged,
            template=(source_template(resolved_template_ir) if resolved_template_ir is not None else resolved_template),
            template_ir=resolved_template_ir,
        )


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


def compose_application(
    workspace: Workspace | None = None,
    observability: ObservabilityPort | None = None,
) -> ApplicationComposition:
    return ApplicationComposition(workspace=workspace, observability=observability)
