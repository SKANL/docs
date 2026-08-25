# src/docs/application/doctor.py
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.application.output_names import resolve_draft_docx_name
from docs.domain.doctor import Check, DoctorResult, find_manual_like, match_normalized
from docs.domain.docx_structure import structure_parts
from docs.domain.models.template import Template
from docs.domain.ports.content_probe_port import ContentProbePort
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.domain.rules import review_rules
from docs.domain.tool_versions import (
    MINIMUM_VERSIONS,
    describe_version,
    parse_version,
    version_meets,
)


class DoctorService:
    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        asset_service: AssetService,
        tool_resolver: ToolResolverPort,
        content_probe: ContentProbePort | None = None,
    ) -> None:
        self.evidence_repository = evidence_repository
        self.asset_service = asset_service
        self.tool_resolver = tool_resolver
        # Optional, like `IngestService`'s injected `pdf_render` (design.md
        # item F pattern): unwired callers keep working, they just lose the
        # manual auto-detect capability (fail-open, never a hard dependency).
        self.content_probe = content_probe

    def run_doctor(self, doc_id: str, config: dict[str, Any], strict: bool = False) -> DoctorResult:
        checks: list[Check] = []

        context_dir_value = config["paths"].get("context_dir")
        if context_dir_value:
            path = Path(context_dir_value)
            checks.append(Check("context_dir", path.exists() and path.is_dir(), str(path)))

        checks.append(self._manual_check(config["paths"], strict))

        if config["paths"].get("extracted_dir"):
            extracted = Path(config["paths"]["extracted_dir"])
            # De-hardcoded (verify follow-up NEW-SUGGESTION-1, sibling of PR1's
            # WARNING-2): was an unconditional comparison against a single
            # fixed expected policy string. Mirrors domain/rules.py's
            # _check_extracted_dir_policy exactly -- verifies a policy is
            # DECLARED (internal consistency), never a hardcoded expected value
            # (spec: document-pipeline "Extracted-dir policy checked only when
            # configured").
            extracted_dir_policy = config["paths"].get("extracted_dir_policy")
            checks.append(
                Check(
                    "extracted_dir_traceability_only",
                    bool(extracted_dir_policy) and isinstance(extracted_dir_policy, str),
                    f"{extracted} ({extracted_dir_policy or 'missing'})",
                    required=False,
                )
            )

        for name in ["template_docx", "example_pdf", "manual_pdf"]:
            value = config["paths"].get(name)
            if value:
                checks.append(self._declared_file_check(name, Path(value)))

        for part in structure_parts(config):
            if part.get("type") in {"cover_from_asset", "embed_docx"}:
                name = part.get("asset", "")
                path = self.asset_service.asset_path(doc_id, name)
                checks.append(
                    Check(
                        f"asset:{name}",
                        path.exists(),
                        str(path) if path.exists() else f"Falta el asset `{name}`. Agrégalo con `asset add`.",
                        required=False,
                    )
                )

        template = Template.model_validate(config)
        rules_path = Path(config["paths"]["rules_manifest"])
        manifest_exists = self.evidence_repository.file_exists(rules_path)
        manifest_size = self.evidence_repository.file_size(rules_path) if manifest_exists else 0
        rules_result = review_rules(template, manifest_exists, manifest_size, strict=False)
        checks.append(
            Check(
                "rules_config",
                rules_result.passed,
                "Contratos, APA 7 y preliminares configurados" if rules_result.passed else rules_result.to_markdown(),
                required=True,
            )
        )
        checks.append(
            Check("rules_manifest", manifest_exists, str(rules_path) if manifest_exists else "Ejecutar `build-rules`.", required=False)
        )

        checks.append(Check("python", True, sys.executable))
        uv = shutil.which("uv")
        checks.append(
            Check(
                "uv",
                bool(uv),
                uv or "No encontrado en PATH. Requerido para invocar el harness (`uv run ...`).",
                required=True,
            )
        )
        # Required toolchain (item L): the document literally cannot be built
        # without pandoc (design.md ADR-L: "required = document can't build
        # without it"). Kept `required=True` explicit, not just the default.
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
        pandoc_version = self._version_of(pandoc)
        checks.append(
            Check(
                "pandoc",
                bool(pandoc),
                f"{pandoc} ({describe_version(pandoc_version)})"
                if pandoc
                else "No encontrado en PATH. Instalar Pandoc para build-docx.",
                required=True,
            )
        )
        if pandoc:
            checks.append(self._version_check("pandoc", pandoc_version))
        libreoffice = self.tool_resolver.resolve_libreoffice(config.get("paths", {}))
        # Optional, unlike pandoc: LibreOffice only renders the visual QA PDF.
        # Its absence must not fail-fast the whole pipeline and deny the user a
        # document the harness can otherwise build (qa-docx degrades in draft).
        checks.append(
            Check(
                "libreoffice",
                bool(libreoffice),
                libreoffice or "No encontrado en PATH. Instalar LibreOffice para el QA visual (opcional).",
                required=False,
            )
        )
        checks.append(self._stale_drafts_check(config))
        checks.extend(self._image_page_caption_checks(config))
        checks.extend(self._capability_checks(config))

        scripts_dir_value = config.get("paths", {}).get("documents_scripts_dir")
        scripts_dir = Path(scripts_dir_value) if scripts_dir_value else None
        for script in config.get("documents_tools", {}).get("scripts", []):
            script_path = scripts_dir / script if scripts_dir else None
            checks.append(
                Check(
                    f"documents_script:{script}",
                    script_path is not None and script_path.exists(),
                    str(script_path) if script_path is not None and script_path.exists() else "No encontrado en plugin Documents.",
                    required=strict and config.get("documents_tools", {}).get("required_in_strict", True),
                )
            )
        gh = shutil.which("gh")
        checks.append(Check("gh", bool(gh), gh or "No encontrado. Requerido para collect-issues.", required=strict))

        try:
            import docx  # noqa: F401

            checks.append(Check("python-docx", True, "Disponible"))
        except Exception as exc:
            checks.append(Check("python-docx", False, f"No disponible: {exc}"))

        return DoctorResult(checks)

    def _resolve_declared_path(self, path: Path) -> Path:
        """The declared path, or its sibling that differs only in Unicode form.

        A filename can sit on disk decomposed (NFD) while a template declares
        it composed (NFC) -- the same name to a human, different strings to
        `Path.exists()`. A real OneDrive workspace hit exactly that and doctor
        called a guide PDF missing while listing the directory it was in.
        Listing is the I/O; `match_normalized` owns the comparison.
        """
        if path.exists() or not path.parent.is_dir():
            return path
        try:
            candidates = [entry.name for entry in path.parent.iterdir()]
        except OSError:  # pragma: no cover - unreadable directory
            return path
        matched = match_normalized(path.name, candidates)
        return path.parent / matched if matched else path

    def _declared_file_check(self, name: str, path: Path) -> Check:
        """A declared input file must exist AND be what its extension claims.

        Existing is the cheap half. `template_docx` is the cover base, so a
        text file renamed `.docx` used to pass here and die much later inside
        python-docx with an error that never named the file the user got
        wrong -- the same "found is not usable" shape as `safe_style_name`,
        `MermaidSvgRenderer` and the toolchain version checks.
        """
        path = self._resolve_declared_path(path)
        if not (path.exists() and path.is_file()):
            return Check(name, False, str(path), required=False)
        if self.content_probe is not None and not self.content_probe.probe(path).container_ok:
            return Check(
                name,
                False,
                f"{path} existe pero no se abre como `.docx`: la extensión dice "
                f"una cosa y el contenido otra. Revisá que sea el archivo correcto.",
                required=False,
            )
        return Check(name, True, str(path), required=False)

    def _stale_drafts_check(self, config: dict[str, Any]) -> Check:
        """More than one `*-draft.docx` in the output directory is a hazard.

        Found in a real workspace: `reporte-estadia-draft.docx` sitting next
        to `tesina-draft.docx`, left behind when the output name changed.
        Two files called "draft" and nothing saying which is current -- the
        wrong one is one careless copy away from being delivered.

        Reports, never deletes. Removing someone's output without asking is
        exactly what a harness must not do.
        """
        draft_dir_value = config.get("paths", {}).get("output_draft_dir")
        if not draft_dir_value:
            return Check("stale_drafts", True, "Sin directorio de salida configurado.", required=False)
        draft_dir = Path(draft_dir_value)
        if not draft_dir.is_dir():
            return Check("stale_drafts", True, "Todavía no se construyó nada.", required=False)
        drafts = sorted(p.name for p in draft_dir.glob("*-draft.docx"))
        if len(drafts) <= 1:
            return Check("stale_drafts", True, drafts[0] if drafts else "Sin borradores.", required=False)
        current = resolve_draft_docx_name(config.get("doc_id", ""), config)
        others = [name for name in drafts if name != current]
        return Check(
            "stale_drafts",
            False,
            f"Hay {len(drafts)} borradores en {draft_dir}: {', '.join(drafts)}. "
            f"El vigente es `{current}`; {', '.join(others)} quedaron de una "
            f"configuración anterior. Borralos vos para no entregar el equivocado.",
            required=False,
        )

    def _image_page_caption_checks(self, config: dict[str, Any]) -> list[Check]:
        """A full-page image with no `caption` falls back to its filename.

        Rebuilding a real document surfaced two of these -- the alt text read
        `carta-empresarial` and `carta-academica`. Better than the nothing
        they had before, and worse than a sentence the author could write in
        five seconds. A whole page that IS an image is the worst place for a
        screen reader to hear a filename.
        """
        checks: list[Check] = []
        for part in structure_parts(config):
            if part.get("type") != "image_page" or part.get("caption"):
                continue
            image = str(part.get("image", "(sin imagen)"))
            checks.append(
                Check(
                    f"image_page_caption:{image}",
                    False,
                    f"La página completa `{image}` no declara `caption`, así que su "
                    f"texto alternativo va a ser el nombre del archivo. Agregá "
                    f"`\"caption\"` a esa parte de `structure` para que un lector de "
                    f"pantalla anuncie qué es.",
                    required=False,
                )
            )
        return checks

    def _version_of(self, executable: str | None) -> tuple[int, ...] | None:
        """The parsed version of a resolved tool, or None when unreadable."""
        if not executable:
            return None
        reader = getattr(self.tool_resolver, "tool_version", None)
        if reader is None:  # pragma: no cover - a resolver predating the port method
            return None
        return parse_version(reader(executable))

    def _version_check(self, tool: str, found: tuple[int, ...] | None) -> Check:
        """"Is it new enough?" -- the question `doctor` never asked.

        Separate from the presence check on purpose: PRESENT and USABLE are
        different questions, and folding them into one check would force a
        single ok/not-ok on two independent facts. `required=False` because an
        old pandoc degrades `--format html` (it is `--embed-resources` that
        needs 2.19) while `--format docx` keeps working -- failing the whole
        run would deny a user the format they can still build.
        """
        minimum = MINIMUM_VERSIONS[tool]
        meets = version_meets(found, minimum)
        if meets is None:
            return Check(
                f"{tool}_version",
                True,
                f"No se pudo leer la versión de {tool} ({describe_version(found)}); "
                f"se asume utilizable. Mínimo soportado: {describe_version(minimum)}.",
                required=False,
            )
        if meets:
            return Check(f"{tool}_version", True, describe_version(found), required=False)
        return Check(
            f"{tool}_version",
            False,
            f"{tool} {describe_version(found)} es anterior al mínimo "
            f"{describe_version(minimum)}. `--format html` va a fallar "
            f"(usa `--embed-resources`, agregado en 2.19); `--format docx` sigue "
            f"funcionando. Actualizá {tool} para habilitar HTML.",
            required=False,
        )

    def _manual_check(self, paths: dict[str, Any], strict: bool) -> Check:
        """Item E: `manual_dir` is an OPTIONAL input -- WARN, not FAIL, when
        missing; `--strict` restores hard-fail. A declared-but-missing path
        is checked first; failing that, auto-detect any manual-like file
        anywhere under `inbox_dir` by content, never a hardcoded path."""
        declared = paths.get("manual_dir")
        if declared:
            path = Path(declared)
            if path.exists() and path.is_dir():
                return Check("manual_dir", True, str(path), required=False)

        detected = self._detect_manual(paths.get("inbox_dir"))
        if detected is not None:
            return Check(
                "manual_dir",
                True,
                f"Detectado automáticamente por contenido: {detected}",
                required=False,
            )

        return Check(
            "manual_dir",
            False,
            "No se detectó un manual/guía en inbox/; el documento se generará con "
            "las reglas por defecto -- agrega la guía (PDF, DOCX o Markdown) a "
            "inbox/ para que el harness aplique sus normas.",
            required=strict,
        )

    def _detect_manual(self, inbox_dir_value: Any) -> str | None:
        if not inbox_dir_value or self.content_probe is None:
            return None
        inbox_dir = Path(inbox_dir_value)
        if not inbox_dir.is_dir():
            return None
        candidates: list[tuple[str, str]] = []
        for path in sorted(inbox_dir.rglob("*")):
            if not path.is_file() or path.name.startswith("_"):
                continue
            signals = self.content_probe.probe(path)
            candidates.append((path.relative_to(inbox_dir).as_posix(), signals.extension))
        return find_manual_like(candidates)

    def _capability_checks(self, config: dict[str, Any]) -> list[Check]:
        """Item L: figure-render capabilities degrade the render step, never
        the pipeline -- each is `required=False` with install guidance
        (design.md ADR-L)."""
        checks: list[Check] = []
        try:
            import pypdfium2  # noqa: F401
            from PIL import Image  # noqa: F401

            checks.append(Check("pdf_page_render", True, "Disponible (pypdfium2 + pillow)", required=False))
        except Exception as exc:
            checks.append(
                Check(
                    "pdf_page_render",
                    False,
                    f"No disponible ({exc}). La extracción de figuras por renderizado de "
                    "página (PDFs vectoriales) se omitirá. Instalar con "
                    "`uv pip install pypdfium2 pillow`.",
                    required=False,
                )
            )

        try:
            import opendataloader_pdf  # noqa: F401

            checks.append(Check("pdf_raster_extract", True, "Disponible (opendataloader-pdf)", required=False))
        except Exception as exc:
            checks.append(
                Check(
                    "pdf_raster_extract",
                    False,
                    f"No disponible ({exc}). La extracción de figuras/rasters desde PDF vía "
                    "opendataloader-pdf se omitirá. Instalar con "
                    "`uv pip install opendataloader-pdf`.",
                    required=False,
                )
            )

        java = self.tool_resolver.resolve_java(config.get("paths", {}))
        checks.append(
            Check(
                "java",
                bool(java),
                java or "No encontrado en PATH. opendataloader-pdf requiere Java (JRE 11+) para ingerir PDFs.",
                required=False,
            )
        )

        # Slice 7 (on-demand-visual-generation): mmdc/resvg are OPTIONAL PATH
        # toolchains for `generate-visuals` (mermaid + SVG->PNG rasterization
        # respectively) -- absent tools degrade that stage to WARN+skip per
        # visual, never fail the build, same required=False shape as
        # pandoc/libreoffice above.
        mmdc = self.tool_resolver.resolve_mmdc(config.get("paths", {}))
        checks.append(
            Check(
                "mmdc",
                bool(mmdc),
                mmdc
                or "No encontrado en PATH. Instalar con `npm install -g @mermaid-js/mermaid-cli` "
                "para generar diagramas mermaid en generate-visuals (opcional).",
                required=False,
            )
        )
        resvg = self.tool_resolver.resolve_resvg(config.get("paths", {}))
        checks.append(
            Check(
                "resvg",
                bool(resvg),
                resvg
                or "No encontrado en PATH. Instalar resvg (https://github.com/linebender/resvg) "
                "para rasterizar visuales SVG a PNG en generate-visuals (opcional).",
                required=False,
            )
        )
        return checks
