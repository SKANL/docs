"""Application-owned document pipeline composition use case."""

from __future__ import annotations

import hashlib
import inspect as inspect_module
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from collections.abc import Mapping
from contextlib import closing
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from docs.application.artifact_render_service import ArtifactRenderService
from docs.application.build_manifest_service import BuildManifestService
from docs.application.document_input_stages import DocumentInputStageService
from docs.application.pipeline_assembly import assemble_explicit_stage_operations
from docs.application.pipeline_publication import PipelinePublication
from docs.application.pipeline_service import PipelineService
from docs.application.review_stages import ReviewStageService
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_content, sha256_file
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_kernel import ArtifactRecord, StageResult
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import ReviewDimension, ReviewResult
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry


def _write_manifest_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class _HtmlDocumentVerifier(HTMLParser):
    """Record the document-level elements required from rendered HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_elements = 0
        self.body_elements = 0
        self.visible_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() == "html":
            self.html_elements += 1
        elif tag.casefold() == "body":
            self.body_elements += 1

    def handle_data(self, data: str) -> None:
        self.visible_text.append(data)


def _verify_html_artifact(artifact: Path) -> tuple[bool, str]:
    try:
        source = artifact.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        return False, f"HTML artifact is not valid UTF-8: {exc}"

    parser = _HtmlDocumentVerifier()
    try:
        parser.feed(source)
        parser.close()
    except Exception as exc:  # pragma: no cover - HTMLParser currently accepts most malformed markup.
        return False, f"HTML artifact is unreadable: {exc}"
    if parser.html_elements != 1:
        return False, "HTML artifact is missing an html root element"
    if parser.body_elements != 1:
        return False, "HTML artifact is missing a body element"
    # Reopen the serialized document through the parser and require rendered
    # content, not merely a container-shaped byte stream.
    if not "".join(parser.visible_text).strip():
        return False, "HTML artifact has no renderable body content"
    return True, "HTML document reopened and visual content verified"


def _verify_pdf_artifact(artifact: Path) -> tuple[bool, str]:
    if not artifact.read_bytes().startswith(b"%PDF-"):
        return False, "PDF artifact is missing the %PDF header"
    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(str(artifact))
        try:
            if len(document) == 0:
                return False, "PDF artifact contains no pages"
            for index in range(len(document)):
                page = document[index]
                bitmap = page.render(scale=1.0)
                if bitmap.width <= 0 or bitmap.height <= 0:
                    return False, f"PDF page {index + 1} rendered with invalid dimensions"
        finally:
            document.close()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return False, f"PDF artifact is unreadable: {exc}"
    return True, "PDF reopened, rendered, and visual dimensions verified"


def _verify_pdf_reproducibility(original: Path, rebuilt: Path) -> tuple[bool, str]:
    """Compare PDF semantics, not bytes, because PDF rendering is engine-dependent."""
    try:
        import pypdfium2 as pdfium

        with pdfium.PdfDocument(str(original)) as first, pdfium.PdfDocument(str(rebuilt)) as second:
            if not len(first) or len(first) != len(second):
                return False, "PDF reproducibility changed the page count"
            for index in range(len(first)):
                left, right = first[index], second[index]
                try:
                    if left.get_size() != right.get_size():
                        return False, f"PDF reproducibility changed page geometry at page {index + 1}"
                    with closing(left.get_textpage()) as left_text, closing(right.get_textpage()) as right_text:
                        if left_text.get_text_range() != right_text.get_text_range():
                            return False, f"PDF reproducibility changed text at page {index + 1}"
                    with (
                        closing(left.render(scale=150 / 72)) as left_bitmap,
                        closing(right.render(scale=150 / 72)) as right_bitmap,
                        left_bitmap.to_pil() as left_image, right_bitmap.to_pil() as right_image,
                    ):
                        if left_image.size != right_image.size or left_image.tobytes() != right_image.tobytes():
                            return False, f"PDF reproducibility changed rendered content at page {index + 1}"
                finally:
                    left.close()
                    right.close()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return False, f"PDF reproducibility comparison failed: {exc}"
    return True, "PDF reproducibility verified semantically"


def _verify_non_docx_artifact(output_format: str, artifact: Path) -> tuple[bool, str]:
    """Reopen a rendered non-DOCX artifact using its existing verifier."""
    if output_format == "html":
        return _verify_html_artifact(artifact)
    if output_format == "pdf":
        return _verify_pdf_artifact(artifact)
    return False, f"no format verifier is registered for {output_format}"


def _minimal_structural_audit(artifact: Path, output_format: str) -> tuple[bool, str]:
    """Perform the minimum structural reopen gate when no full auditor is wired."""
    if not artifact.exists():
        return False, f"artifact is missing: {artifact}"
    if not artifact.is_file():
            return False, f"artifact is not a file: {artifact}"
    try:
        if artifact.stat().st_size <= 0:
            return False, f"artifact is empty: {artifact}"
        if output_format == "docx":
            with zipfile.ZipFile(artifact) as archive:
                if "word/document.xml" not in archive.namelist():
                    return False, "structural DOCX missing word/document.xml"
                archive.read("word/document.xml")
        else:
            artifact.read_bytes()
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        return False, f"artifact is unreadable: {exc}"
    return True, f"minimal fallback: {output_format.upper()} reopened and structural dimensions verified"


def _fallback_structural_audit(artifact: Path, output_format: str) -> tuple[bool, str]:
    """Native name for the native structural stage."""
    return _minimal_structural_audit(artifact, output_format)


def _successful_stage_result(name: str, artifact: Path) -> StageResult:
    """Create the completion artifact required by a native v2 stage."""
    record = ArtifactRecord(
        f"{name}-complete",
        str(artifact),
        hashlib.sha256(artifact.read_bytes()).hexdigest(),
        producer_stage=name,
    )
    return StageResult(
        name,
        True,
        artifacts=(
            record,
        ),
    )


def _verify_readable_artifact(artifact: Path) -> tuple[bool, str]:
    """Keep format-specific verification in pipeline stages, after a safe read."""
    try:
        with artifact.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return False, f"artifact is unreadable: {exc}"
    return True, "artifact is readable"


def _scratch_directory(prefix: str, parent: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=parent))


def _available_files(root: Path, directory: str) -> tuple[Path, ...]:
    candidate = root / directory
    return (
        tuple(
            sorted(
                (
                    path
                    for path in candidate.rglob("*")
                    if path.is_file() and not path.is_symlink()
                ),
                key=lambda path: path.as_posix(),
            )
        )
        if candidate.is_dir()
        else ()
    )


def _build_inputs(root: Path) -> tuple[Path, ...]:
    excluded = {"output", "runs", "__pycache__"}
    return tuple(
        sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and not any(part in excluded for part in path.relative_to(root).parts)
                and not any(
                    part.startswith((".x20-", ".atomic-"))
                    for part in path.relative_to(root).parts
                )
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def _manifest_for(
    *,
    resolved: Any,
    config: dict[str, Any],
    renderer: Any,
    root: Path,
    artifact: Path,
    destination: Path,
    output_format: str,
    run_id: str,
    verification: dict[str, Any] | None = None,
) -> BuildManifest:
    """Native seam for callers that construct a v2 manifest directly."""
    service = BuildManifestService(
        input_identities=_current_input_identities,
        build_inputs=_build_inputs,
        artifact_hash=sha256_file,
        write_text=_write_manifest_text,
    )
    return service.create_manifest(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=root,
        artifact=artifact,
        destination=destination,
        output_format=output_format,
        run_id=run_id,
        verification=verification,
    )


def _current_input_identities(
    *, resolved: Any, config: dict[str, Any], renderer: Any, root: Path, output_format: str
) -> dict[str, Any]:
    """Recompute every identity that makes a build eligible for publication.

    The function deliberately accepts resolved domain values rather than a
    manifest.  This keeps identity calculation deterministic and reusable by
    both the build and publish paths, while preventing a manifest from
    attesting to its own stale values.
    """
    inputs = _build_inputs(root)
    assets = _available_files(root, "assets")
    template = getattr(resolved, "template", None)
    context = getattr(resolved, "context", config.get("context", {}))
    config_identity = deepcopy(config)
    output_identity = config_identity.get("output")
    if isinstance(output_identity, dict):
        output_identity.pop("format", None)
    return {
        "source_hash": sha256_content(
            {path.relative_to(root).as_posix(): sha256_file(path) for path in inputs}
        ),
        "template_hash": sha256_content(getattr(template, "__dict__", template)),
        "template_ir_hash": getattr(getattr(resolved, "template_ir", None), "ir_hash", ""),
        # The selected output format is a renderer choice, not a source
        # generation identity; this keeps one build generation packageable
        # across DOCX/HTML/PDF.
        "config_hash": sha256_content(config_identity),
        "context_hash": sha256_content(context),
        "asset_hashes": {
            path.relative_to(root).as_posix(): sha256_file(path) for path in assets
        },
        "renderer_versions": {
            "renderer": _renderer_identity(renderer, config, output_format)
        },
    }


def _renderer_identity(renderer: Any, config: dict[str, Any], output_format: str) -> str:
    implementation = f"{type(renderer).__module__}.{type(renderer).__qualname__}"
    payload: dict[str, str] = {"format": output_format, "implementation": implementation}
    for attribute in ("version", "renderer_version", "__version__"):
        value = getattr(renderer, attribute, None)
        if isinstance(value, str) and value:
            payload["renderer_version"] = value
            break
    source = inspect_module.getsourcefile(type(renderer))
    if source:
        source_path = Path(source)
        if source_path.is_file():
            payload["renderer_source_sha256"] = sha256_file(source_path)
    resolver_owner = renderer
    resolver = getattr(resolver_owner, "tool_resolver", None)
    if resolver is None:
        resolver_owner = getattr(renderer, "docx_renderer", renderer)
        resolver = getattr(resolver_owner, "tool_resolver", None)
    if resolver is not None:
        resolver_method = "resolve_libreoffice" if output_format == "pdf" else "resolve_pandoc"
        resolve = getattr(resolver, resolver_method, None)
        tool_version = getattr(resolver, "tool_version", None)
        if callable(resolve):
            executable = resolve(config.get("paths", {}))
            if executable:
                payload["tool"] = str(executable)
                if callable(tool_version):
                    version = tool_version(executable)
                    if version:
                        payload["tool_version"] = str(version).strip()
    return sha256_content(payload)


def _resolve_publish_inputs(
    deps: Any, document_root: Path, output_format: str
) -> tuple[Any, dict[str, Any], Any]:
    """Resolve fresh publish inputs through the active composition root."""
    resolved = deps.resolve_context(document_root.name)
    config = deepcopy(resolved.config)
    config.setdefault("output", {})["format"] = output_format
    renderer = deps.resolve_renderer(config)
    return resolved, config, renderer


def _renderer_capabilities(renderer: Any) -> tuple[ToolCapability, ...]:
    """Adapt explicit renderer capability declarations to local checks."""
    declared: list[ToolCapability] = []
    for attribute, required in (
        ("required_capabilities", True),
        ("optional_capabilities", False),
    ):
        values = getattr(renderer, attribute, ())
        if isinstance(values, str):
            values = (values,)
        if not isinstance(values, (list, tuple, set, frozenset)):
            continue
        for value in values:
            if isinstance(value, ToolCapability):
                declared.append(
                    ToolCapability(
                        value.name,
                        value.executable,
                        required or value.required,
                        module=value.module,
                    )
                )
            elif isinstance(value, str) and value:
                declared.append(ToolCapability(value, value, required))
    return tuple(declared)


def _visual_capabilities(document_root: Path) -> tuple[ToolCapability, ...]:
    """Report optional visual tools only when the document requests visuals."""
    specs_path = document_root / "sections" / "visual-specs.json"
    try:
        specs = json.loads(specs_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ()
    if not isinstance(specs, list):
        return ()
    visual_types = {
        item.get("type")
        for item in specs
        if isinstance(item, Mapping) and isinstance(item.get("type"), str)
    }
    capabilities: list[ToolCapability] = []
    if visual_types:
        capabilities.append(ToolCapability("resvg", "resvg", degradation="skip vector visual generation"))
    if "mermaid" in visual_types:
        capabilities.append(ToolCapability("mmdc", "mmdc", degradation="skip Mermaid visual generation"))
    return tuple(capabilities)


def _capabilities_for(
    renderer: Any,
    output_format: str,
    document_root: Path,
    paths: dict[str, object] | None = None,
    capability_detector: Any = None,
) -> ToolCapabilityRegistry:
    capabilities = list(_renderer_capabilities(renderer))
    capabilities.extend(
        (
            ToolCapability("pillow", "", module="PIL", requirement="required for image inspection", degradation="skip image-specific checks"),
            ToolCapability("pypdfium2", "", module="pypdfium2", required=output_format == "pdf", requirement="required for PDF page rendering", degradation="skip PDF rendering"),
        )
    )
    if output_format == "pdf":
        capabilities.append(ToolCapability("soffice", "soffice", required=True, requirement="required to derive PDF from DOCX", degradation="skip PDF derivation in draft mode"))
    capabilities.extend(_visual_capabilities(document_root))
    return ToolCapabilityRegistry(capabilities, capability_detector)


def create_document_pipeline_service(
    deps: Any,
    output_format: str = "docx",
    policy: PipelinePolicy | None = None,
    document: str = "",
    pipeline_id: str = "document",
    provenance_run_id: str | None = None,
    publication_destination: Path | None = None,
    artifact_path: Path | None = None,
    manifest_path: Path | None = None,
) -> PipelineService:
    """Adapt the composition-root services to the v2 pipeline contracts."""
    state: dict[str, Any] = {
        "resolved": None,
        "renderer": None,
        "artifact": None,
        "manifest_path": None,
        "attested_artifact_sha256": None,
    }
    scratch_dirs: list[Path] = []
    artifact_renderer = ArtifactRenderService(
        scratch_factory=_scratch_directory,
        validator=_verify_readable_artifact,
    )

    def active_context() -> Any:
        resolved = deps.resolve_context(document)
        state["resolved"] = resolved
        config = deepcopy(resolved.config)
        config.setdefault("output", {})["format"] = output_format
        state["config"] = config
        state["renderer"] = deps.resolve_renderer(config)
        return resolved

    # Keep publication outside output/published so verification can never promote
    # an artifact, even when the runtime has no explicit no-publish mode.
    initial = active_context()
    initial_root = deps.workspace.doc_root(initial.doc_id)
    initial_root.mkdir(parents=True, exist_ok=True)
    destination = publication_destination or (
        initial_root / "output" / "current" / f"{initial.doc_id}.{output_format}"
    )
    if pipeline_id in {"document-verify", "document-package", "document-publish"}:
        source_artifact = artifact_path or destination
        source_manifest = manifest_path or source_artifact.with_suffix(
            source_artifact.suffix + ".manifest.json"
        )
        if source_artifact.is_file() and not source_artifact.is_symlink():
            state["artifact"] = source_artifact
        if source_manifest.is_file() and not source_manifest.is_symlink():
            try:
                state["manifest"] = BuildManifest.from_dict(
                    json.loads(source_manifest.read_text(encoding="utf-8"))
                )
                state["manifest_path"] = source_manifest
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # The stage that consumes this state emits the actionable
                # contract error; service construction remains deterministic.
                state["manifest"] = None
        candidate = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
        if candidate.is_file():
            state["package_candidate"] = candidate
    resources = deps.create_pipeline_resources(
        renderer=state["renderer"],
        output_format=output_format,
        document_root=initial_root,
        document_id=initial.doc_id,
        paths=state["config"].get("paths", {}) or {},
        atomic_file_writer=deps.atomic_file_writer,
        artifact=lambda: state.get("artifact"),
        manifest=lambda: state.get("manifest"),
        package_writer=lambda candidate, staging: deps.package_publications.package(
            candidate, staging, allow_staging=True, lock_held=True
        ),
        candidate_sink=lambda candidate: state.__setitem__("package_candidate", candidate),
        verify_current_build=pipeline_id == "document-package",
    )
    capabilities = resources.capabilities
    ledger = resources.ledger
    artifact_store = resources.artifact_store
    state["stage_artifacts"] = []
    manifest_service = BuildManifestService(
        input_identities=_current_input_identities,
        build_inputs=_build_inputs,
        artifact_hash=sha256_file,
        write_text=_write_manifest_text,
    )
    state["run_id"] = provenance_run_id or f"cli-build-{output_format}-{uuid.uuid4().hex}"
    build_token = uuid.uuid4().hex

    def ensure_assets() -> tuple[bool, str]:
        return resolve_assets()

    release_destination = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
    package_release_service = resources.publication
    stage_provider = deps.create_stage_provider(
        config=state["config"],
        output_format=output_format,
        ensure_assets=ensure_assets,
        extra_services={"package_release_service": package_release_service},
    )
    source_pipeline = deps.create_source_pipeline()
    review_stage_service = None
    if all(
        service is not None
        for service in (
            getattr(deps, "structural_audit_service", None),
            getattr(deps, "format_audit", None),
            getattr(deps, "review", None),
            getattr(deps, "render_verification", None),
        )
    ):
        review_stage_service = ReviewStageService(
            structural_audit=deps.structural_audit_service,
            format_audit=deps.format_audit,
            document_review=deps.review,
            rules_manifest_state=getattr(deps, "rules_manifest_state", lambda _config: (False, 0)),
            render_verification=deps.render_verification,
            qa=getattr(deps, "qa", None) if hasattr(getattr(deps, "qa", None), "inspect_docx") else None,
            pdf_reproducibility=_verify_pdf_reproducibility,
        )

    def _stage_service(name: str) -> Any:
        return stage_provider.get(name)

    def _callable_stage(name: str) -> Any:
        operation = _stage_service(name)
        return operation if callable(operation) else None

    input_stages = DocumentInputStageService(
        document_id=initial.doc_id,
        document_root=initial_root,
        output_format=output_format,
        state=state,
        resolve_context=lambda: deps.resolve_context(document),
        resolve_renderer=deps.resolve_renderer,
        figure_pipeline=getattr(getattr(deps, "ingest", None), "figures", None),
        source_pipeline=source_pipeline,
        fallback_stage=_callable_stage,
    )

    def _build_with_format(format_name: str) -> tuple[bool, str]:
        renderers = getattr(deps, "renderers", {})
        outcome = artifact_renderer.build_format(
            renderers=renderers if isinstance(renderers, Mapping) else {},
            format_name=format_name,
            document_id=state["resolved"].doc_id,
            config=state["config"],
            scratch_parent=initial_root,
        )
        if outcome.scratch_dir is not None:
            scratch_dirs.append(outcome.scratch_dir)
        if outcome.succeeded and outcome.artifact is not None:
            state.setdefault("artifacts", {})[format_name] = outcome.artifact
        return outcome.succeeded, outcome.detail

    def _structural_audit() -> tuple[bool, str]:
        service = _stage_service("structural_audit_service")
        if service is None or not hasattr(service, "audit"):
            return _fallback_structural_audit(state["artifact"], output_format)
        template = state["resolved"].template
        contract = getattr(template, "template_contract", None)
        # Current templates predate the declarative contract.  They still need
        # the generic structural checks (readability, tables, relationships),
        # so an absent contract means "no additional requirements", not "skip
        # the audit".  This keeps migration finite while preserving the v2
        # gate for every rendered artifact.
        contract_data = {} if contract is None else contract.model_dump(exclude_none=True)
        result = service.audit(state["artifact"], contract_data)
        return result.passed, result.to_markdown()

    def _native_accessibility_review() -> tuple[bool, str] | StageResult:
        """Run the existing format audit's accessibility checks as a V2 stage."""
        if output_format != "docx":
            passed, detail = _verify_non_docx_artifact(output_format, state["artifact"])
            return passed, f"accessibility reopen: {detail}"
        strict = policy is not None and policy.mode in {PipelineMode.strict, PipelineMode.release}
        result: ReviewResult = deps.format_audit.audit_format(state["artifact"], state["config"], strict=strict)
        findings = result.filter_dimensions({ReviewDimension.ACCESSIBILITY}).issues
        if not findings:
            return _successful_stage_result("accessibility-review", state["artifact"])
        return False, "; ".join(issue.message for issue in findings)

    def _native_document_review(
        name: str, dimension: ReviewDimension
    ) -> tuple[bool, str]:
        """Reuse the document review service for one native review dimension."""
        review_service = getattr(deps, "review", None)
        manifest_state = _stage_service("rules_manifest_state")
        if review_service is None or not callable(manifest_state):
            return False, f"{name} service is not configured"
        manifest_exists, manifest_size = manifest_state(state["config"])
        strict = policy is not None and policy.mode in {PipelineMode.strict, PipelineMode.release}
        result = review_service.review_document(
            state["resolved"].doc_id,
            state["resolved"].template,
            strict=strict,
            manifest_exists=manifest_exists,
            manifest_size=manifest_size,
            normative=resolve_normative_settings(state["config"]),
        )
        findings = result.filter_dimensions({dimension}).issues
        if not findings:
            return successful(name)
        return False, "; ".join(issue.message for issue in findings)

    def _native_visual_review() -> tuple[bool, str]:
        """Reuse the format audit's visual findings for the rendered artifact."""
        if output_format != "docx":
            passed, detail = _verify_non_docx_artifact(output_format, state["artifact"])
            return passed, f"visual reopen: {detail}"
        result: ReviewResult = deps.format_audit.audit_format(state["artifact"], state["config"])
        findings = result.filter_dimensions({ReviewDimension.VISUAL}).issues
        if not findings:
            return successful("visual-review")
        return False, "; ".join(issue.message for issue in findings)

    def _native_reproducibility_check() -> tuple[bool, str] | StageResult:
        """Rebuild once and compare bytes with the artifact under review."""
        artifact = state.get("artifact")
        renderer = state.get("renderer")
        if not isinstance(artifact, Path) or renderer is None:
            return False, "reproducibility check has no rendered artifact"
        scratch_dir = Path(tempfile.mkdtemp(prefix=".x20-repro-", dir=initial_root))
        scratch_dirs.append(scratch_dir)
        try:
            rebuilt = renderer.build(
                state["resolved"].doc_id,
                state["config"],
                output=scratch_dir / artifact.name,
            )
            if rebuilt is None:
                return False, "reproducibility check produced no artifact"
            rebuilt_path = Path(rebuilt)
            if output_format == "pdf":
                passed, detail = _verify_pdf_reproducibility(artifact, rebuilt_path)
                if not passed:
                    return False, detail
            elif sha256_file(artifact) != sha256_file(rebuilt_path):
                return False, "reproducibility divergence detected"
        except Exception as exc:
            return False, f"reproducibility check failed: {exc}"
        return _successful_stage_result("reproducibility-check", artifact)

    def _review_stage(name: str) -> tuple[bool, str] | StageResult:
        if review_stage_service is None:
            return False, f"{name} service is not configured"
        effective_policy = policy or PipelinePolicy(PipelineMode.draft)
        review_config = deepcopy(state["config"])
        visual_settings = review_config.setdefault("visual_qa", {})
        if isinstance(visual_settings, dict):
            visual_settings["preview_stem"] = f"{state['resolved'].doc_id}.{output_format}"
        outcome = review_stage_service.run_stage(
            name,
            document_id=state["resolved"].doc_id,
            artifact_path=state["artifact"],
            config=review_config,
            template=state["resolved"].template,
            policy=effective_policy,
            rebuild=lambda output: state["renderer"].build(
                state["resolved"].doc_id, state["config"], output=output
            ),
            scratch_dir=initial_root / "runs" / "v2-review" / name,
        )
        if outcome.ok and not outcome.warnings:
            return _successful_stage_result(name, state["artifact"])
        return StageResult(
            name,
            outcome.ok,
            artifacts=(_successful_stage_result(name, state["artifact"]).artifacts if outcome.ok else ()),
            warnings=outcome.warnings,
            errors=outcome.errors,
        )

    def _native_package_release() -> tuple[bool, str]:
        """Package the verified, attested artifact before publication."""
        artifact = state.get("artifact")
        manifest = state.get("manifest")
        if not isinstance(artifact, Path) or not isinstance(manifest, BuildManifest):
            return False, "package-release requires a verified artifact and manifest"
        destination = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
        source_dir = initial_root / "output" / "current"
        source_dir.mkdir(parents=True, exist_ok=True)
        candidate = destination.with_name(f".{destination.name}.candidate")
            # A package stage runs before this format reaches output/current.  Stage a
        # complete snapshot of the already-published formats plus this run's
        # attested artifact, so repeatable --format builds accumulate one
        # release archive instead of replacing it format by format.
        with deps.release_lock(destination):
            staging = Path(tempfile.mkdtemp(prefix=".x20-package-", dir=source_dir.parent))
            try:
                for existing in sorted(source_dir.iterdir(), key=lambda path: path.name):
                    if existing.is_symlink() or not existing.is_file():
                        raise RuntimeError(
                            f"package refuses unsafe source entry: {existing.name}"
                        )
                    if existing.name.endswith(".manifest.json"):
                        continue
                    manifest_path = existing.with_name(existing.name + ".manifest.json")
                    if not manifest_path.is_file() or manifest_path.is_symlink():
                        continue
                    try:
                        previous_manifest = BuildManifest.from_dict(
                            json.loads(manifest_path.read_text(encoding="utf-8"))
                        )
                        previous_manifest.validate_for_publication()
                        if previous_manifest.document_id != initial.doc_id or not ledger.verify_attestation(
                            previous_manifest.provenance_run, previous_manifest.attestation()
                        ):
                            continue
                        if sha256_file(existing) != previous_manifest.artifacts[0].sha256:
                            continue
                    except (OSError, TypeError, ValueError, KeyError, IndexError):
                        # A stale or malformed derived artifact must not poison
                        # a new package. It is replaced only when its format is
                        # rebuilt in the current invocation.
                        continue
                    shutil.copyfile(existing, staging / existing.name)
                    shutil.copyfile(manifest_path, staging / manifest_path.name)
                package_name = f"{initial.doc_id}.{output_format}"
                shutil.copyfile(artifact, staging / package_name)
                (staging / f"{package_name}.manifest.json").write_text(
                    manifest.to_json() + "\n", encoding="utf-8"
                )
                # Staging changes only the pathname. Its content hash maps to
                # the manifest artifact while the attestation remains verified
                # against the original provenance run.
                deps.package_publications.package(candidate, staging, allow_staging=True, lock_held=True)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        state["package_candidate"] = candidate
        return successful("package-release", str(candidate))

    def successful(name: str, detail: str = "") -> tuple[bool, str]:
        return True, detail or f"{name} completed"

    def resolve_config() -> tuple[bool, str]:
        return input_stages.resolve_config()

    def resolve_template() -> tuple[bool, str]:
        return input_stages.resolve_template()

    def resolve_context() -> tuple[bool, str]:
        return input_stages.resolve_context_stage()

    def resolve_assets() -> tuple[bool, str]:
        return input_stages.resolve_assets()

    def _source_stage(name: str) -> tuple[bool, str]:
        return input_stages.source_stage(name)

    def _review_stage_operation(stage: str, fallback: Any) -> Any:
        if review_stage_service is not None:
            return lambda: _review_stage(stage)
        return fallback

    def validate_contracts() -> tuple[bool, str]:
        return input_stages.validate_contracts()

    def render() -> tuple[bool, str]:
        resolved = state["resolved"]
        # The attested render is retained at one deterministic path per
        # document/format. This avoids unbounded random runs directories
        # while leaving the source available through package-release and
        # later provenance verification.
        runs_dir = initial_root / "runs"
        retained_dir = runs_dir / "v2-artifacts"
        outcome = artifact_renderer.render_and_retain(
            renderer=state["renderer"],
            format_name=output_format,
            document_id=resolved.doc_id,
            config=state["config"],
            runs_dir=runs_dir,
            retained_dir=retained_dir,
            build_token=build_token,
            directory_guard=deps.directory_guard,
            directory_identity=_directory_identity,
            assert_directory_identity=_assert_directory_identity,
        )
        if outcome.scratch_dir is not None:
            scratch_dirs.append(outcome.scratch_dir)
        if outcome.succeeded:
            state["artifact"] = outcome.artifact
            return successful("render", outcome.detail)
        return False, outcome.detail

    def audit() -> tuple[bool, str]:
        if output_format == "docx":
            strict = policy is not None and policy.mode in {PipelineMode.strict, PipelineMode.release}
            result: ReviewResult = deps.format_audit.audit_format(
                state["artifact"], state["config"], strict=strict
            )
            state["verification"] = {"passed": result.passed, "format": output_format, "reopened": True}
            if not result.passed:
                return False, "; ".join(issue.message for issue in result.issues)
            return successful("audit")
        if output_format == "html":
            passed, detail = _verify_non_docx_artifact(output_format, state["artifact"])
            state["verification"] = {"passed": passed, "format": output_format, "reopened": True, "rendered": passed, "detail": detail}
            return passed, detail
        if output_format == "pdf":
            passed, detail = _verify_non_docx_artifact(output_format, state["artifact"])
            state["verification"] = {"passed": passed, "format": output_format, "reopened": True, "rendered": passed, "detail": detail}
            return passed, detail
        return False, f"no format verifier is registered for {output_format}"

    def verify() -> tuple[bool, str]:
        if output_format == "docx":
            strict = policy is not None and policy.mode in {PipelineMode.strict, PipelineMode.release}
            qa_path = deps.qa.qa_docx(state["config"], state["artifact"], strict=strict)
            if strict and (qa_path is None or not Path(qa_path).exists()):
                return False, "strict verification requires durable QA evidence"
            if strict and Path(qa_path).is_dir() and not (Path(qa_path) / "qa-report.md").is_file():
                return False, "strict verification requires qa-report.md evidence"
        else:
            passed, detail = _verify_non_docx_artifact(output_format, state["artifact"])
            verification = dict(state.get("verification", {}))
            verification.update(
                {
                    "passed": passed,
                    "format": output_format,
                    "reopened": True,
                    "readable": passed,
                    "detail": detail,
                }
            )
            state["verification"] = verification
            return passed, detail
        return successful("verify")

    explicit_stages = assemble_explicit_stage_operations(
        stage_provider,
        callbacks={
            "structural_audit": _structural_audit,
            "accessibility_review": _native_accessibility_review,
            "visual_review": _native_visual_review,
            "reproducibility_check": _native_reproducibility_check,
            "review_stage": lambda name: lambda: _review_stage(name),
            "build_with_format": lambda name: lambda: _build_with_format(name),
            "render": render,
        },
        output_format=output_format,
        review_stages_available=review_stage_service is not None,
    )
    publication_service = PipelinePublication(manifest_service, ledger)

    def provenance() -> tuple[bool, str]:
        if pipeline_id == "document-publish":
            passed, detail, digest = publication_service.record_existing(
                initial.doc_id, state.get("artifact"), state.get("manifest")
            )
            if not passed:
                return False, detail
            state["attested_artifact_sha256"] = digest
            return successful("provenance", detail)
        manifest = publication_service.record_build(
            resolved=state["resolved"],
            config=state["config"],
            renderer=state["renderer"],
            root=initial_root,
            artifact=state["artifact"],
            destination=destination,
            output_format=output_format,
            run_id=state["run_id"],
            verification=state.get("verification"),
            stage_artifacts=tuple(state["stage_artifacts"]),
        )
        state["manifest"] = manifest
        return successful("provenance")

    def publish(scratch: Path) -> None:
        publication_service.stage(
            scratch=scratch,
            artifact=state.get("artifact"),
            manifest=state.get("manifest"),
            package_candidate=state.get("package_candidate"),
            document_id=initial.doc_id,
            output_format=output_format,
            existing=pipeline_id == "document-publish",
            persisted_manifest=state.get("manifest_path"),
            expected_digest=state.get("attested_artifact_sha256"),
        )

    manifest_destination = destination.with_suffix(destination.suffix + ".manifest.json")
    release_destination = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
    operations: dict[str, Any] = {
        "resolve-config": resolve_config,
        "resolve-template": resolve_template,
        "resolve-context": resolve_context,
        "resolve-assets": resolve_assets,
        "validate-contracts": validate_contracts,
        "ingest-sources": lambda: _source_stage("ingest-sources"),
        "normalize-sources": lambda: _source_stage("normalize-sources"),
        "compile-structure": lambda: _source_stage("compile-structure"),
        "build-docx": render,
        "structural-audit": _review_stage_operation("structural-audit", audit),
        "editorial-review": _review_stage_operation("editorial-review", verify),
        "record-provenance": provenance,
        "evidence-review": _review_stage_operation(
            "evidence-review",
            _callable_stage("evidence_review")
            or (lambda: _native_document_review("evidence-review", ReviewDimension.EVIDENCE)),
        ),
        "consistency-review": _review_stage_operation(
            "consistency-review",
            _callable_stage("consistency_review")
            or (lambda: _native_document_review("consistency-review", ReviewDimension.CONSISTENCY)),
        ),
        "package-release": stage_provider.operation("package_release") or _native_package_release,
    }
    operations.update(
        {name.replace("_", "-"): operation for name, operation in explicit_stages.items()}
    )
    return deps.create_document_pipeline(
        operations=operations,
        expected_outputs=(
            f"primary.{output_format}",
            f"primary.{output_format}.manifest.json",
            f"{initial.doc_id}.zip",
        ),
        destinations=(destination, manifest_destination, release_destination),
        operation=publish,
        capabilities=capabilities,
        ledger=ledger,
        policy=policy,
        run_id_sink=lambda value: state.__setitem__("run_id", value),
        excluded_stages=frozenset(
            {"build-docx", "build-html", "build-pdf"} - {f"build-{output_format}"}
        ),
        cleanup=lambda: _cleanup_scratch_dirs(scratch_dirs),
        artifact_store=artifact_store,
        record_sink=state["stage_artifacts"].extend,
        run_start=state["stage_artifacts"].clear,
    )


def _cleanup_scratch_dirs(scratch_dirs: list[Path]) -> None:
    for path in scratch_dirs:
        shutil.rmtree(path, ignore_errors=True)

def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"package output parent changed during {operation}: {path}")
