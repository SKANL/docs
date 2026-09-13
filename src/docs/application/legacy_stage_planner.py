# src/docs/application/legacy_stage_planner.py
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docs.application.context_files import CONCERNS, CURATED_INDEX_FILENAME, build_context_files, build_context_index
from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.ports.document_renderer_port import DocumentRendererPort
from docs.domain.rules import review_rules

if TYPE_CHECKING:
    from docs.application.pipeline import PipelineService


class LegacyStagePlanner:
    """Build the legacy pipeline's ordered stage callable map."""

    def plan(
        self,
        pipeline: PipelineService,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        repo_root: Path,
        strict: bool,
        renderer: DocumentRendererPort,
    ) -> dict[str, Callable[[], tuple[bool, str]]]:
        # Populated by stage_build_docx once it runs; format-audit/qa read the
        # actual built path from here instead of re-deriving a hardcoded name,
        # so a custom config["output"]["draft_name"] is honored end-to-end.
        built_docx_path: dict[str, Path] = {}

        def _draft_docx_path() -> Path:
            return built_docx_path.get("path") or (
                Path(config["paths"]["output_draft_dir"]) / pipeline._resolve_draft_docx_name(doc_id, config)
            )

        def stage_doctor() -> tuple[bool, str]:
            result = pipeline.doctor_service.run_doctor(doc_id, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_build_rules() -> tuple[bool, str]:
            return True, str(pipeline.evidence_service.build_rules(config))

        def stage_review_rules() -> tuple[bool, str]:
            manifest_exists, manifest_size = pipeline.rules_manifest_state(config)
            result = review_rules(template, manifest_exists, manifest_size, strict=strict)
            return result.passed, result.to_markdown()

        def stage_collect_sources() -> tuple[bool, str]:
            return True, str(pipeline.collection_service.collect_sources(config))

        def stage_collect_code_evidence() -> tuple[bool, str]:
            return True, str(pipeline.collection_service.collect_code_evidence(config, repo_root))

        def stage_collect_issues() -> tuple[bool, str]:
            try:
                return True, str(pipeline.collection_service.collect_issues(config, repo_root))
            except Exception as exc:  # best-effort: gh puede no estar disponible
                return True, f"omitido: {exc}"

        def stage_build_ledger() -> tuple[bool, str]:
            path = Path(config["paths"]["fact_ledger"])
            path.parent.mkdir(parents=True, exist_ok=True)
            context_lines = pipeline.context_confirmed_lines(doc_id, template)
            path.write_text(pipeline.evidence_service.render_fact_ledger(config, context_lines), encoding="utf-8")
            return True, str(path)

        def stage_build_sections() -> tuple[bool, str]:
            paths = [str(pipeline.build_section(doc_id, template, section.id, config)) for section in template.sections]
            return True, f"{len(paths)} secciones"

        def stage_gap_report() -> tuple[bool, str]:
            section_bodies: dict[str, str] = {}
            for section in template.sections:
                if pipeline.review_service.repository.section_exists(doc_id, section.order, section.id):
                    _metadata, body = pipeline.review_service.repository.read_section(doc_id, section.order, section.id)
                    section_bodies[section.id] = body
            sections_dir = Path(config["paths"]["sections_dir"])
            # Reuse the SAME atomic writer instance already wired to
            # IngestService (design.md Decision 9: ContextService gains no
            # new constructor dependency for this artifact).
            report = pipeline.context_service.build_gap_report(
                doc_id, template, section_bodies, sections_dir, writer=pipeline.ingest_service.writer
            )
            gap_count = len(report["context_gaps"]) + len(report["section_gaps"])
            detail = f"{len(report['context_gaps'])} gaps de contexto, {len(report['section_gaps'])} gaps de sección"
            if gap_count and strict:
                return False, f"{detail} (modo estricto bloquea antes de producir salida final)."
            return True, detail

        def stage_pack_context() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = pipeline.rules_manifest_state(config)
            paths = [
                str(pipeline.context_pack_service.pack_context(doc_id, template, section.id, config, normative=normative))
                for section in template.sections
            ]
            pipeline.context_pack_service.pack_context_document(
                doc_id, template, config,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            )
            return True, f"{len(paths)} context packs + 1 documento"

        def stage_review_document() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = pipeline.rules_manifest_state(config)
            result = pipeline.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            )
            return result.passed, result.to_markdown()

        def stage_build_docx() -> tuple[bool, str]:
            path = renderer.build(doc_id, config)
            if path is None:
                # Unlike build-html/build-pdf, DOCX is the PRIMARY format:
                # every later stage (format-audit-docx, qa-docx) reads the
                # artifact this one produces, so a skip here is a failure,
                # not a degrade.
                return False, "no se generó el .docx: el renderer no produjo artefacto"
            built_docx_path["path"] = path
            return True, str(path)

        def stage_build_html() -> tuple[bool, str]:
            # HtmlRendererAdapter.build() returns None (already WARNed to
            # stderr) when pandoc is absent -- degrade like the best-effort
            # `stage_collect_issues` pattern (ok=True, "omitido: ..." detail)
            # rather than failing the whole pipeline for a secondary,
            # opt-in output format (item C-html).
            path = renderer.build(doc_id, config)
            if path is None:
                return True, "omitido: pandoc no disponible"
            return True, str(path)

        def stage_build_pdf() -> tuple[bool, str]:
            # PdfRendererAdapter.build() returns None (already WARNed to
            # stderr) when the LibreOffice/soffice toolchain is absent --
            # degrade like build-html/stage_collect_issues (ok=True,
            # "omitido: ..." detail) rather than failing the whole pipeline
            # for a secondary, opt-in output format (item C-pdf).
            path = renderer.build(doc_id, config)
            if path is None:
                return True, "omitido: LibreOffice/soffice no disponible"
            return True, str(path)

        def stage_format_audit() -> tuple[bool, str]:
            docx_path = _draft_docx_path()
            result = pipeline.format_audit_service.audit_format(docx_path, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_qa_docx() -> tuple[bool, str]:
            docx_path = _draft_docx_path()
            qa_dir = pipeline.qa_service.qa_docx(config, docx_path, strict=strict)
            if pipeline.structural_audit_service is not None and template.template_contract is not None:
                structural = pipeline.structural_audit_service.audit(
                    docx_path, template.template_contract.model_dump(exclude_none=True)
                )
                if not structural.passed:
                    return False, structural.to_markdown()
            # The visual render is the half of QA that needs LibreOffice, and
            # it degrades to a skip in draft. `qa-report.md` says so, but
            # saying it only there made the pipeline line read as a clean
            # success for 24 consecutive runs on a real workspace while half
            # the stage never ran. `build-html` and `build-pdf` report their
            # own degradation right here ("omitido: ..."); this now matches
            # them instead of asking the reader to open a file.
            if not any(Path(qa_dir).glob("*.pdf")):
                return True, f"{qa_dir} (sin render visual: falta LibreOffice; la auditoría de formato sí corrió)"
            return True, str(qa_dir)

        def stage_ingest() -> tuple[bool, str]:
            inbox_dir = Path(config["paths"]["inbox_dir"])
            sections_dir = Path(config["paths"]["sections_dir"])
            assets_dir_value = config["paths"].get("assets_dir")
            assets_dir = Path(assets_dir_value) if assets_dir_value else None
            report = pipeline.ingest_service.ingest_inbox(
                inbox_dir, sections_dir, strict=strict, assets_dir=assets_dir
            )
            errors = [f for f in report["files"] if f.get("status") == "error"]
            detail = f"{report['processed']} archivos procesados"
            if errors:
                detail += f"; {len(errors)} con error"
            # SUGGESTION-2 (fresh-context verify, PR2 fix batch): media
            # cleanup is computed on every ingest run -- surface it in the
            # CLI-facing detail so it is never invisible activity.
            media_cleanup = report.get("media_cleanup", {})
            removed = media_cleanup.get("removed", [])
            refused = media_cleanup.get("refused", [])
            if removed or refused:
                detail += f"; media: {len(removed)} eliminado(s), {len(refused)} rechazado(s)"
            return not errors, detail

        def stage_generate_visuals() -> tuple[bool, str]:
            # Format-agnostic, fail_fast=False (domain/pipeline.py:
            # _GENERATE_VISUALS) -- `GenerateVisualsService.generate` never
            # raises (per-visual WARN+skip), so this stage always reports
            # ok=True; a missing/absent `GenerateVisualsService` (e.g. a
            # caller building `PipelineService` without one) degrades the
            # same "omitido:" way as stage_collect_issues/stage_build_html,
            # never a KeyError on `config["paths"]["assets_dir"]`.
            if pipeline.generate_visuals_service is None:
                return True, "omitido: GenerateVisualsService no configurado"
            sections_dir = Path(config["paths"]["sections_dir"])
            assets_dir = Path(config["paths"]["assets_dir"])
            result = pipeline.generate_visuals_service.generate(sections_dir, assets_dir)
            return True, f"{result.generated} generado(s), {result.skipped} omitido(s)"

        def stage_build_context_files() -> tuple[bool, str]:
            context_dir = Path(config["paths"]["context_dir"])
            ingested_dir = Path(config["paths"]["sections_dir"]) / "ingested"
            ingested_texts = (
                {path.stem: path.read_text(encoding="utf-8") for path in sorted(ingested_dir.glob("*.md"))}
                if ingested_dir.is_dir()
                else {}
            )
            existing_files = {
                concern: (context_dir / f"{concern}.md").read_text(encoding="utf-8")
                for concern in CONCERNS
                if (context_dir / f"{concern}.md").exists()
            }
            files = build_context_files(ingested_texts, existing_files)
            context_dir.mkdir(parents=True, exist_ok=True)
            for concern, content in files.items():
                (context_dir / f"{concern}.md").write_text(content, encoding="utf-8")
            return True, f"{len(files)} archivos de contexto"

        def stage_build_context_index() -> tuple[bool, str]:
            # Reads only the known CONCERNS files (never a wildcard glob of
            # `context_dir`) so the pre-existing Topic/Q&A subsystem's own
            # per-topic files never get mistaken for curated-concern content.
            context_dir = Path(config["paths"]["context_dir"])
            concern_files = {
                concern: (context_dir / f"{concern}.md").read_text(encoding="utf-8")
                for concern in CONCERNS
                if (context_dir / f"{concern}.md").exists()
            }
            index_text = build_context_index(concern_files)
            index_path = context_dir / CURATED_INDEX_FILENAME
            index_path.write_text(index_text, encoding="utf-8")
            return True, str(index_path)

        return {
            "doctor": stage_doctor,
            "build-rules": stage_build_rules,
            "review-rules": stage_review_rules,
            "collect-sources": stage_collect_sources,
            "collect-code-evidence": stage_collect_code_evidence,
            "collect-issues": stage_collect_issues,
            "build-ledger": stage_build_ledger,
            "build-sections": stage_build_sections,
            "gap-report": stage_gap_report,
            "pack-context": stage_pack_context,
            "review-document": stage_review_document,
            "build-docx": stage_build_docx,
            "build-html": stage_build_html,
            "build-pdf": stage_build_pdf,
            "format-audit-docx": stage_format_audit,
            "ingest": stage_ingest,
            "generate-visuals": stage_generate_visuals,
            "build-context-files": stage_build_context_files,
            "build-context-index": stage_build_context_index,
            "qa-docx": stage_qa_docx,
        }

