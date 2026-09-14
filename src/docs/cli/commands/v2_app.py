"""Opt-in CLI surface for the workspace-backed v2 pipeline."""

from __future__ import annotations

import hashlib
import inspect as inspect_module
import json
import mimetypes
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from difflib import unified_diff
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import typer

from docs.application.artifact_build_service_v2 import (
    ArtifactBuildErrorV2,
    ArtifactBuildServiceV2,
)
from docs.application.atomic_transform_v2 import AtomicTransform, TransformSpec
from docs.application.build_manifest_service_v2 import BuildManifestServiceV2
from docs.application.package_service_v2 import (
    PackageFileV2,
    PackagePublicationError,
    PackageServiceV2,
)
from docs.application.pipeline_components_v2 import PUBLIC_PIPELINES
from docs.application.pipeline_service_v2 import (
    PipelineServiceV2,
    PublicationSpec,
)
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.application.review_stages import ReviewStageService
from docs.application.source_pipeline_v2 import SourcePipelineV2
from docs.application.stage_provider_v2 import StageProviderV2
from docs.application.visual_baseline import VisualBaselineError, VisualBaselineService
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_content, sha256_file
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline_kernel import ArtifactRecord, StageResult
from docs.domain.pipeline_policy import PipelineMode, PipelinePolicy
from docs.domain.review import ReviewDimension, ReviewResult
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry
from docs.infrastructure.docx.deterministic_zip import normalize_docx_zip_timestamps
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
from docs.infrastructure.ingest.atomic_file_adapter import AtomicFileAdapter
from docs.infrastructure.ingest.md_normalize_adapter import MdNormalizeAdapter
from docs.infrastructure.locking import directory_handle_guard, owned_directory_lock
from docs.infrastructure.tools.tool_capability_detector_adapter import NativeToolCapabilityDetector

v2_app = typer.Typer(help="Workspace-backed v2 pipeline commands.")


def _source_pipeline(deps: Any) -> SourcePipelineV2 | None:
    """Compose the source pipeline while tolerating older dependency fixtures."""
    ingest = getattr(deps, "ingest", None)
    if ingest is None:
        return None
    normalizer = getattr(deps, "markdown_normalizer", None) or MdNormalizeAdapter()
    file_writer = getattr(deps, "atomic_file_writer", None) or AtomicFileAdapter()
    return SourcePipelineV2(ingest, normalizer, file_writer)


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

        first = pdfium.PdfDocument(str(original))
        second = pdfium.PdfDocument(str(rebuilt))
        try:
            if len(first) != len(second):
                return False, "PDF reproducibility changed the page count"
            for index in range(len(first)):
                if first[index].get_size() != second[index].get_size():
                    return False, f"PDF reproducibility changed page geometry at page {index + 1}"
        finally:
            first.close()
            second.close()
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
                    part.startswith((".v2-", ".atomic-"))
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
    """Compatibility seam for callers that construct a v2 manifest directly."""
    service = BuildManifestServiceV2(
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
    ctx: typer.Context, document_root: Path, output_format: str
) -> tuple[Any, dict[str, Any], Any]:
    """Resolve fresh publish inputs through the active composition root."""
    deps = ctx.obj["deps"]
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


def _capabilities_for(renderer: Any, output_format: str, document_root: Path) -> ToolCapabilityRegistry:
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
    return ToolCapabilityRegistry(
        capabilities,
        NativeToolCapabilityDetector(SystemToolResolverAdapter().tool_version),
    )


def create_v2_service(
    deps: Any,
    output_format: str = "docx",
    policy: PipelinePolicy | None = None,
    document: str = "",
    pipeline_id: str = "document",
    provenance_run_id: str | None = None,
) -> PipelineServiceV2:
    """Adapt the composition-root services to the v2 pipeline contracts."""
    state: dict[str, Any] = {"resolved": None, "renderer": None, "artifact": None}
    scratch_dirs: list[Path] = []

    def active_context() -> Any:
        resolved = deps.resolve_context(document)
        state["resolved"] = resolved
        config = deepcopy(resolved.config)
        config.setdefault("output", {})["format"] = output_format
        state["config"] = config
        state["renderer"] = deps.resolve_renderer(config)
        return resolved

    # Keep publication outside output/final so verification can never promote
    # an artifact, even when the runtime has no explicit no-publish mode.
    initial = active_context()
    initial_root = deps.workspace.doc_root(initial.doc_id)
    initial_root.mkdir(parents=True, exist_ok=True)
    capabilities = _capabilities_for(state["renderer"], output_format, initial_root)
    destination = initial_root / "output" / "v2" / f"{initial.doc_id}.{output_format}"
    if pipeline_id in {"document-verify", "document-package", "document-publish"}:
        if destination.is_file():
            state["artifact"] = destination
        manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
        if manifest_path.is_file():
            try:
                state["manifest"] = BuildManifest.from_dict(
                    json.loads(manifest_path.read_text(encoding="utf-8"))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                # The stage that consumes this state emits the actionable
                # contract error; service construction remains deterministic.
                state["manifest"] = None
        candidate = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
        if candidate.is_file():
            state["package_candidate"] = candidate
    ledger = ProvenanceLedgerV2(initial_root / "runs" / "v2-provenance.json", trusted_root=initial_root)
    manifest_service = BuildManifestServiceV2(
        input_identities=_current_input_identities,
        build_inputs=_build_inputs,
        artifact_hash=sha256_file,
        write_text=_write_manifest_text,
    )
    state["run_id"] = provenance_run_id or f"cli-build-{output_format}-{uuid.uuid4().hex}"
    build_token = uuid.uuid4().hex

    stage_services: dict[str, Any] = {}
    compatibility_services = getattr(deps, "v2_compatibility", None)
    service_names = {
        "generate_visuals_service",
        "structural_audit_service",
        "rules_manifest_state",
        "generate_visuals",
        "compose_cover",
        "structural_audit",
        "ingest_sources",
        "normalize_sources",
        "compile_structure",
        "build_html",
        "build_pdf",
        "accessibility_review",
        "visual_review",
        "reproducibility_check",
        "evidence_review",
        "consistency_review",
        "package_release",
    }
    for name in service_names:
        service = getattr(deps, name, None)
        if service is None and compatibility_services is not None:
            service = getattr(compatibility_services, name, None)
        if service is not None:
            stage_services[name] = service
    def ensure_assets() -> tuple[bool, str]:
        return resolve_assets()

    stage_provider = StageProviderV2(
        stage_services,
        config=state["config"],
        output_format=output_format,
        ensure_assets=ensure_assets,
    )
    source_pipeline = _source_pipeline(deps)
    review_stage_service = None
    if output_format == "docx" and all(
        service is not None
        for service in (
            getattr(deps, "structural_audit_service", None),
            getattr(deps, "format_audit", None),
            getattr(deps, "review", None),
        )
    ):
        review_stage_service = ReviewStageService(
            structural_audit=deps.structural_audit_service,
            format_audit=deps.format_audit,
            document_review=deps.review,
            rules_manifest_state=getattr(deps, "rules_manifest_state", lambda _config: (False, 0)),
        )

    def _stage_service(name: str) -> Any:
        return stage_provider.get(name)

    def _callable_stage(name: str) -> Any:
        operation = _stage_service(name)
        return operation if callable(operation) else None

    def _build_with_format(format_name: str) -> tuple[bool, str]:
        resolved = state["resolved"]
        renderers = getattr(deps, "renderers", {})
        renderer = renderers.get(format_name) if isinstance(renderers, Mapping) else None
        if renderer is None:
            return False, f"renderer does not provide {format_name} output"
        config = deepcopy(state["config"])
        config.setdefault("output", {})["format"] = format_name
        service = ArtifactBuildServiceV2(
            build=lambda doc_id, build_config, output: renderer.build(
                doc_id, build_config, output=output
            ),
            scratch_factory=_scratch_directory,
            validator=_verify_readable_artifact,
        )
        try:
            result = service.build(
                document_id=resolved.doc_id,
                config=config,
                output_format=format_name,
                scratch_parent=initial_root,
            )
        except ArtifactBuildErrorV2 as exc:
            if exc.reason == "missing":
                return True, f"omitted: {exc}"
            return False, str(exc)
        scratch_dirs.append(result.scratch_dir)
        state.setdefault("artifacts", {})[format_name] = result.artifact
        return True, str(result.artifact)

    def _structural_audit() -> tuple[bool, str]:
        service = _stage_service("structural_audit_service")
        if service is None or not hasattr(service, "audit"):
            return False, "structural-audit service is not configured"
        template = state["resolved"].template
        contract = getattr(template, "template_contract", None)
        # Legacy templates predate the declarative contract.  They still need
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
            return successful("accessibility-review", f"not applicable to {output_format}")
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
            return successful("visual-review", f"not applicable to {output_format}")
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
        scratch_dir = Path(tempfile.mkdtemp(prefix=".v2-repro-", dir=initial_root))
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
        outcome = review_stage_service.run_stage(
            name,
            document_id=state["resolved"].doc_id,
            artifact_path=state["artifact"],
            config=state["config"],
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
        """Package the verified, attested v2 artifact before publication."""
        artifact = state.get("artifact")
        manifest = state.get("manifest")
        if not isinstance(artifact, Path) or not isinstance(manifest, BuildManifest):
            return False, "package-release requires a verified artifact and manifest"
        destination = initial_root / "output" / "release" / f"{initial.doc_id}.zip"
        source_dir = initial_root / "output" / "v2"
        source_dir.mkdir(parents=True, exist_ok=True)
        candidate = destination.with_name(f".{destination.name}.candidate")
        # A package stage runs before this format reaches output/v2.  Stage a
        # complete snapshot of the already-published formats plus this run's
        # attested artifact, so repeatable --format builds accumulate one
        # release archive instead of replacing it format by format.
        with _package_lock(destination):
            staging = Path(tempfile.mkdtemp(prefix=".v2-package-", dir=source_dir.parent))
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
                _write_package_archive(candidate, staging, _allow_staging=True, _lock_held=True)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        state["package_candidate"] = candidate
        return successful("package-release", str(candidate))

    def successful(name: str, detail: str = "") -> tuple[bool, str]:
        return True, detail or f"{name} completed"

    def resolve_config() -> tuple[bool, str]:
        resolved = active_context()
        return successful("resolve-config", f"document={resolved.doc_id}")

    def resolve_template() -> tuple[bool, str]:
        resolved = state["resolved"]
        return successful("resolve-template", f"template={resolved.template.type}")

    def resolve_context() -> tuple[bool, str]:
        resolved = state["resolved"]
        return successful("resolve-context", f"document={resolved.doc_id}")

    def resolve_assets() -> tuple[bool, str]:
        # A migrated workspace may already contain authored figure assets and
        # bindings but no ingest-generated catalog.  Reconstruct that derived
        # catalog from the existing assets once, without touching authored
        # Markdown or replacing a non-empty curated catalog.
        configured_paths = state["config"].get("paths", {})
        sections_dir = Path(configured_paths.get("sections_dir", initial_root / "sections"))
        catalog_path = sections_dir / "figure-catalog.json"
        bindings_path = sections_dir / "figure-bindings.json"
        figure_pipeline = getattr(getattr(deps, "ingest", None), "figures", None)
        if figure_pipeline is not None and bindings_path.is_file():
            try:
                catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.is_file() else {}
                if not catalog.get("figures"):
                    assets_dir = Path(configured_paths.get("assets_dir", initial_root / "assets")) / "figures"
                    candidates = tuple(
                        (path, path.relative_to(initial_root).as_posix())
                        for path in sorted(assets_dir.iterdir(), key=lambda item: item.name)
                        if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".svg"}
                    ) if assets_dir.is_dir() else ()
                    if candidates:
                        figure_pipeline.build_figure_catalog_for(
                            Path(configured_paths.get("inbox_dir", initial_root / "inbox")),
                            sections_dir,
                            list(candidates),
                            [],
                            entries=[],
                            assets_dir=None,
                        )
                        return successful("resolve-assets", f"catalogued {len(candidates)} existing figure assets")
            except (OSError, TypeError, ValueError, AttributeError) as exc:
                return False, f"could not resolve existing figure assets: {exc}"
        return successful("resolve-assets")

    def _source_stage(name: str) -> tuple[bool, str]:
        if source_pipeline is None:
            operation = _callable_stage(name.replace("-", "_"))
            if operation is None:
                return False, f"{name} service is not configured"
            return operation()
        return source_pipeline.run_stage(name, initial.doc_id, initial_root, state["config"])

    def _review_stage_operation(stage: str, fallback: Any) -> Any:
        if review_stage_service is not None:
            return lambda: _review_stage(stage)
        return fallback

    def validate_contracts() -> tuple[bool, str]:
        resolved = state["resolved"]
        if getattr(state["renderer"], "output_format", "") != output_format:
            return False, f"renderer does not provide {output_format} output"
        return successful("validate-contracts", f"document={resolved.doc_id}")

    def render() -> tuple[bool, str]:
        resolved = state["resolved"]
        # The attested render is retained at one deterministic path per
        # document/format. This avoids unbounded random runs directories
        # while leaving the source available through package-release and
        # later provenance verification.
        runs_dir = initial_root / "runs"
        retained_dir = runs_dir / "v2-artifacts"
        if any(path.is_symlink() for path in (initial_root, runs_dir, retained_dir, *runs_dir.parents)):
            return False, "render retention path must not contain symlinked directories"
        retained_dir.mkdir(parents=True, exist_ok=True)
        retained_identity = _directory_identity(retained_dir)
        service = ArtifactBuildServiceV2(
            build=lambda doc_id, config, output: state["renderer"].build(doc_id, config, output=output),
            scratch_factory=_scratch_directory,
            validator=_verify_readable_artifact,
        )
        try:
            result = service.build(
                document_id=resolved.doc_id,
                config=state["config"],
                output_format=output_format,
                scratch_parent=runs_dir,
            )
        except ArtifactBuildErrorV2 as exc:
            return False, str(exc)
        scratch_dirs.append(result.scratch_dir)
        retained = retained_dir / f"{build_token}.{result.artifact.name}"
        with directory_handle_guard(retained_dir):
            os.replace(result.artifact, retained)
        try:
            _assert_directory_identity(retained_dir, retained_identity, operation="render retention")
        except (OSError, RuntimeError) as exc:
            return False, str(exc)
        state["artifact"] = retained
        return successful("render", str(state["artifact"]))

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

    explicit_stages: dict[str, Any] = {
        "generate_visuals": stage_provider.operation("generate_visuals"),
        "compose_cover": stage_provider.operation("compose_cover"),
        "structural_audit": _structural_audit if _stage_service("structural_audit_service") is not None else _callable_stage("structural_audit"),
        "accessibility_review": _callable_stage("accessibility_review") or (
            (lambda: _review_stage("accessibility-review"))
            if review_stage_service is not None
            else _native_accessibility_review
        ),
        "visual_review": _callable_stage("visual_review") or (
            (lambda: _review_stage("visual-review"))
            if review_stage_service is not None
            else _native_visual_review
        ),
        "reproducibility_check": _callable_stage("reproducibility_check") or (
            (lambda: _review_stage("reproducibility-check"))
            if review_stage_service is not None
            else _native_reproducibility_check
        ),
    }
    if output_format != "html":
        explicit_stages["build_html"] = lambda: _build_with_format("html")
    else:
        explicit_stages["build_html"] = render
    if output_format != "pdf":
        explicit_stages["build_pdf"] = lambda: _build_with_format("pdf")
    else:
        explicit_stages["build_pdf"] = render
    explicit_stages = {name: operation for name, operation in explicit_stages.items() if operation is not None}

    def provenance() -> tuple[bool, str]:
        resolved = state["resolved"]
        manifest = manifest_service.create_manifest(
            resolved=resolved,
            config=state["config"],
            renderer=state["renderer"],
            root=initial_root,
            artifact=state["artifact"],
            destination=destination,
            output_format=output_format,
            run_id=state["run_id"],
            verification=state.get("verification"),
        )
        manifest.validate_for_publication()
        state["manifest"] = manifest
        manifest_service.record_provenance(
            ledger,
            state["run_id"],
            initial_root,
            state["artifact"],
            manifest,
        )
        return successful("provenance")

    def publish(scratch: Path) -> None:
        staged = scratch / f"primary.{output_format}"
        staged_manifest = scratch / f"primary.{output_format}.manifest.json"
        staged_package = scratch / f"{initial.doc_id}.zip"
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(state["artifact"], staged)
        manifest_service.write_manifest(state["manifest"], staged_manifest)
        package_candidate = state.get("package_candidate")
        if not isinstance(package_candidate, Path) or not package_candidate.is_file():
            raise RuntimeError("package-release completed without a safe release candidate")
        shutil.copyfile(package_candidate, staged_package)

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
        "package-release": _callable_stage("package_release") or _native_package_release,
    }
    operations.update(
        {name.replace("_", "-"): operation for name, operation in explicit_stages.items()}
    )
    return PipelineServiceV2(
        operations=operations,
        publication=PublicationSpec(
            (f"primary.{output_format}", f"primary.{output_format}.manifest.json", f"{initial.doc_id}.zip"),
            (destination, manifest_destination, release_destination),
            publish,
        ),
        capabilities=capabilities,
        ledger=ledger,
        atomic_transform=AtomicTransform(),
        policy=policy,
        run_id_sink=lambda value: state.__setitem__("run_id", value),
        excluded_stages=frozenset(
            {"build-docx", "build-html", "build-pdf"} - {f"build-{output_format}"}
        ),
        cleanup=lambda: _cleanup_scratch_dirs(scratch_dirs),
    )


def _cleanup_scratch_dirs(scratch_dirs: list[Path]) -> None:
    for path in scratch_dirs:
        shutil.rmtree(path, ignore_errors=True)


def _promote_release_candidate(
    document_root: Path, document_id: str, *, allow_consumed_candidate: bool = False
) -> None:
    """Commit the package only after its format publication has succeeded."""
    release_dir = document_root / "output" / "release"
    candidate = release_dir / f".{document_id}.zip.candidate"
    destination = release_dir / f"{document_id}.zip"
    if not candidate.is_file() or candidate.is_symlink():
        if allow_consumed_candidate and destination.is_file() and not destination.is_symlink():
            # The publication transaction already committed this exact destination.
            # A concurrent/older final ZIP is never accepted because this path is only
            # used after the transaction has reported success.
            return
        raise RuntimeError("package-release completed without a safe release candidate")
    if any(path.is_symlink() for path in (release_dir, *release_dir.parents)):
        raise RuntimeError("release directory must not be symlinked")
    candidate_identity = os.stat(candidate, follow_symlinks=False)
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    with _package_lock(destination):
        parent_identity = _directory_identity(release_dir)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")
        current = os.stat(candidate, follow_symlinks=False)
        if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
            candidate_identity.st_dev,
            candidate_identity.st_ino,
            candidate_identity.st_size,
            candidate_identity.st_mtime_ns,
        ) or hashlib.sha256(candidate.read_bytes()).hexdigest() != candidate_hash:
            raise RuntimeError("release candidate changed before publication")
        with directory_handle_guard(release_dir):
            os.replace(candidate, destination)
        _assert_directory_identity(release_dir, parent_identity, operation="release publication")


def _run(
    ctx: typer.Context,
    command: str,
    json_output: bool,
    formats: list[str] | None,
    policy: PipelineMode | None,
    dimensions: list[ReviewDimension] | None = None,
    pipeline_id: str = "document",
) -> None:
    selected_document = ctx.obj.get("doc", "")
    if formats is None:
        resolved = ctx.obj["deps"].resolve_context(selected_document)
        configured_format: str | None = None
        if isinstance(resolved.config, Mapping):
            output_config = resolved.config.get("output")
            if isinstance(output_config, Mapping):
                output_format = output_config.get("format")
                if isinstance(output_format, str):
                    configured_format = output_format
        requested = [configured_format or "docx"]
    else:
        requested = formats
    reports: list[dict[str, Any]] = []
    batch_backup: Path | None = None
    batch_root: Path | None = None
    batch_journal: Path | None = None
    if command == "build":
        resolved_for_backup = ctx.obj["deps"].resolve_context(selected_document)
        batch_root = ctx.obj["deps"].workspace.doc_root(resolved_for_backup.doc_id)
        batch_root.mkdir(parents=True, exist_ok=True)
        batch_journal = _batch_journal_path(batch_root)
        _recover_batch_transaction(batch_journal)
        batch_backup = Path(tempfile.mkdtemp(prefix=".v2-batch-", dir=batch_root))
        batch_paths = (Path("output") / "v2", Path("output") / "release")
        for relative in batch_paths:
            current = batch_root / relative
            if current.exists() and not current.is_symlink():
                shutil.copytree(current, batch_backup / relative)
        _write_batch_journal(batch_journal, batch_root, batch_backup, batch_paths)
    def restore_batch() -> None:
        if batch_backup is None or batch_root is None:
            return
        for relative in (Path("output") / "v2", Path("output") / "release"):
            current = batch_root / relative
            saved = batch_backup / relative
            if current.exists() and not current.is_symlink():
                shutil.rmtree(current) if current.is_dir() else current.unlink()
            if saved.exists():
                shutil.copytree(saved, current)
    try:
        for output_format in requested:
            selected_policy = PipelinePolicy(policy) if policy is not None else None
            provenance_run_id = f"cli-build-{output_format}-{uuid.uuid4().hex}" if command == "build" else None
            service = create_v2_service(
                ctx.obj["deps"],
                output_format,
                selected_policy,
                document=selected_document,
                pipeline_id=pipeline_id,
                provenance_run_id=provenance_run_id,
            )
            report = service.run(
                provenance_run_id or f"cli-{command}-{output_format}",
                publish=command == "build"
                and pipeline_id in {"document", "document-publish"},
                pipeline_id=pipeline_id,
            )
            report_payload = report.to_dict()
            if dimensions:
                stage_dimensions = {
                    "editorial-review": ReviewDimension.EDITORIAL,
                    "evidence-review": ReviewDimension.EVIDENCE,
                    "consistency-review": ReviewDimension.CONSISTENCY,
                    "structural-audit": ReviewDimension.STRUCTURAL,
                    "accessibility-review": ReviewDimension.ACCESSIBILITY,
                    "visual-review": ReviewDimension.VISUAL,
                    "reproducibility-check": ReviewDimension.REPRODUCIBILITY,
                }
                selected = set(dimensions)
                execution = report_payload.get("execution")
                if isinstance(execution, dict):
                    results = execution.get("results", [])
                    if isinstance(results, list):
                        execution["results"] = [
                            item
                            for item in results
                            if isinstance(item, dict)
                            and isinstance(item.get("stage"), str)
                            and stage_dimensions.get(item["stage"]) in selected
                        ]
                        report_payload["succeeded"] = all(
                            item.get("ok", False) for item in execution["results"]
                        )
                report_payload["dimensions"] = [dimension.value for dimension in dimensions]
            item: dict[str, Any] = {
                "command": command,
                "integration": "workspace",
                "format": output_format,
                "report": report_payload,
            }
            if command == "build" and bool(report_payload.get("succeeded")):
                resolved = ctx.obj["deps"].resolve_context(selected_document)
                _promote_release_candidate(
                    ctx.obj["deps"].workspace.doc_root(resolved.doc_id),
                    resolved.doc_id,
                    allow_consumed_candidate=True,
                )
                draft_dir = resolved.config.get("paths", {}).get("output_draft_dir")
                resolved_root = ctx.obj["deps"].workspace.doc_root(resolved.doc_id)
                if isinstance(draft_dir, str):
                    artifact = Path(draft_dir).parent / "v2" / f"{resolved.doc_id}.{output_format}"
                    if artifact.is_file():
                        ledger = ProvenanceLedgerV2(resolved_root / "runs" / "v2-provenance.json", trusted_root=resolved_root)
                        recorded = ledger.load_attestation(provenance_run_id or "")
                        if recorded is None:
                            raise RuntimeError("missing pre-publication build attestation")
                        BuildManifest.from_dict(recorded.get("manifest", recorded))
                        manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
                        if not manifest_path.is_file():
                            raise RuntimeError("missing atomic build manifest sidecar")
                        item["manifest"] = str(manifest_path)
            reports.append(item)
    except Exception:
        restore_batch()
        raise
    finally:
        if batch_backup is not None and reports and not all(
            item["report"].get("succeeded", False) for item in reports
        ):
            restore_batch()
        if batch_backup is not None:
            shutil.rmtree(batch_backup, ignore_errors=True)
        if batch_journal is not None:
            batch_journal.unlink(missing_ok=True)
    payload = reports[0] if len(reports) == 1 else reports
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for item in reports:
            typer.echo(f"v2 {command} ({item['format']}): workspace integration")
            typer.echo(json.dumps(item["report"], indent=2, sort_keys=True))
    if not all(item["report"].get("succeeded", False) for item in reports):
        raise typer.Exit(code=1)


def _batch_journal_path(root: Path) -> Path:
    return root / "runs" / "v2-batch-transaction.json"


def _write_batch_journal(journal: Path, root: Path, backup: Path, paths: tuple[Path, ...]) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "docs.batch/v1",
        "root": str(root.resolve()),
        "backup": str(backup.resolve()),
        "paths": [path.as_posix() for path in paths],
    }
    temporary = journal.with_name(f".{journal.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    os.replace(temporary, journal)


def _recover_batch_transaction(journal: Path) -> None:
    if not journal.exists():
        return
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
        root = Path(payload["root"]).resolve()
        backup = Path(payload["backup"]).resolve()
        if backup.parent != root.resolve():
            raise RuntimeError("batch recovery backup escapes document root")
        paths = tuple(Path(value) for value in payload["paths"])
        for relative in paths:
            current = root / relative
            saved = backup / relative
            if current.is_symlink():
                raise RuntimeError("batch recovery refuses symlinked output")
            if current.exists():
                shutil.rmtree(current) if current.is_dir() else current.unlink()
            if saved.exists():
                shutil.copytree(saved, current)
    finally:
        journal.unlink(missing_ok=True)


def _document_create_payload(deps: Any, doc_id: str, template: str, title: str) -> dict[str, str]:
    template_name = template or (deps.document_repository.list_templates()[:1] or [""])[0]
    if not template_name:
        raise RuntimeError("No templates are available. Create one in templates/.")
    deps.documents.create(doc_id, template_name, title=title)
    return {
        "document_id": doc_id,
        "path": str((deps.workspace.doc_root(doc_id) / "document.json").resolve()),
        "template": template_name,
        "title": title or doc_id,
    }


@v2_app.command("create")
def create(
    ctx: typer.Context,
    doc_id: str = typer.Argument(..., metavar="id"),
    template: str = typer.Option("", "--template"),
    title: str = typer.Option("", "--title"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a document through the existing workspace document service."""
    payload = _document_create_payload(ctx.obj["deps"], doc_id, template, title)
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        typer.echo(payload["path"])
        typer.echo(f"Document `{payload['document_id']}` created from `{payload['template']}` and marked active.")


@v2_app.command("release")
def release(
    ctx: typer.Context,
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode = typer.Option(PipelineMode.release, "--policy"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Execute the complete verified release pipeline for the active document."""
    _run(
        ctx,
        "build",
        json_output,
        formats,
        policy,
        pipeline_id="document",
    )


def _run_source_command(ctx: typer.Context, command: str, json_output: bool) -> None:
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    root = deps.workspace.doc_root(resolved.doc_id)
    service = _source_pipeline(deps)
    if service is None:
        raise typer.BadParameter("source ingest dependencies are unavailable")
    report = (
        service.ingest(resolved.doc_id, root, resolved.config)
        if command == "ingest"
        else service.prepare(resolved.doc_id, root, resolved.config)
    )
    output = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    typer.echo(output if json_output else json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["succeeded"]:
        raise typer.Exit(code=1)


@v2_app.command("ingest")
def ingest(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Ingest document sources through the native v2 source stage."""
    _run_source_command(ctx, "ingest", json_output)


@v2_app.command("prepare")
def prepare(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Ingest, normalize, and compile the document source structure."""
    _run_source_command(ctx, "prepare", json_output)


@v2_app.command("status")
def status(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
    """Report domain status, including v2 manifest and provenance details."""
    deps = ctx.obj["deps"]
    resolved = deps.resolve_context(ctx.obj.get("doc", ""))
    result = deps.status.status_summary(
        resolved.doc_id,
        resolved.template,
        resolved.config,
        normative=resolve_normative_settings(resolved.config),
    )
    payload = result.to_dict()
    output = resolved.config.get("output", {})
    output_format = output.get("format", "docx") if isinstance(output, Mapping) else "docx"
    renderer = deps.resolve_renderer(resolved.config)
    capability_registry = _capabilities_for(
        renderer, output_format, deps.workspace.doc_root(resolved.doc_id)
    )
    v2_status = payload.get("v2", {})
    current_v2 = dict(v2_status) if isinstance(v2_status, Mapping) else {}
    payload["v2"] = {
        **current_v2,
        "capabilities": capability_registry.report(),
        "capability_diagnostics": capability_registry.diagnostics(),
        "unsupported_stages": current_v2.get("unsupported_stages", []),
        "publication_blockers": current_v2.get("publication_blockers", []),
        "public_pipelines": [spec.pipeline_id for spec in PUBLIC_PIPELINES],
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


@v2_app.command("plan")
def plan(
    ctx: typer.Context,
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to inspect."),
    output_format: str = typer.Option("docx", "--format"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show the ordered stages and external contracts of a registered pipeline."""
    deps = ctx.obj["deps"]
    service = create_v2_service(
        deps, output_format, document=ctx.obj.get("doc", ""), pipeline_id=pipeline_id
    )
    try:
        registered = service.registry.resolve(pipeline_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    definition = registered.definition
    payload = {
        "pipeline_id": pipeline_id,
        "stages": list(definition.plan()),
        "external_artifacts": sorted(definition.external_artifacts),
        "contracts": [contract.to_dict() for contract in definition.artifacts],
    }
    typer.echo(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


@v2_app.command("build")
def build(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode | None = typer.Option(None, "--policy"),
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to execute."),
) -> None:
    """Build verified v2 artifacts in one or more requested formats."""
    _run(ctx, "build", json_output, formats, policy, pipeline_id=pipeline_id)


@v2_app.command("verify")
def verify(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
    formats: list[str] | None = typer.Option(None, "--format"),
    policy: PipelineMode | None = typer.Option(None, "--policy"),
    dimensions: list[ReviewDimension] | None = typer.Option(None, "--dimension"),
    pipeline_id: str = typer.Option("document", "--pipeline", help="Registered pipeline boundary to execute."),
) -> None:
    """Verify v2 artifacts without publishing them."""
    _run(ctx, "verify", json_output, formats, policy, dimensions, pipeline_id)


def _artifact_payload(path: Path) -> dict[str, object]:
    digest = sha256_file(path)
    return {
        "path": str(path.resolve()),
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "sha256": digest,
        "size_bytes": path.stat().st_size,
    }


def _require_contained(path: Path, root: Path, label: str) -> None:
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise typer.BadParameter(f"publish refuses symlinked {label}: {path.name}")
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise typer.BadParameter(f"publish {label} path escapes its intended root") from exc


def _package_files(
    source_dir: Path, *, _allow_staging: bool = False, _verify_attestation: bool = True
) -> tuple[tuple[str, bytes], ...]:
    """Validate the complete v2 artifact set before creating a package."""
    valid_source = source_dir.name == "v2" and source_dir.parent.name == "output"
    valid_staging = (
        _allow_staging
        and source_dir.name.startswith(".v2-package-")
        and source_dir.parent.name == "output"
    )
    if not (valid_source or valid_staging):
        raise typer.BadParameter("package requires an output/v2 source directory")
    if any(path.is_symlink() for path in (source_dir, *source_dir.parents)):
        raise typer.BadParameter("package refuses a symlinked source boundary")
    candidates = tuple(sorted(source_dir.rglob("*"), key=lambda path: path.relative_to(source_dir).as_posix()))
    unsafe = next((path for path in candidates if path.is_symlink()), None)
    if unsafe is not None:
        raise typer.BadParameter(f"package refuses symlinked path: {unsafe.name}")
    files = tuple(path for path in candidates if path.is_file() and not path.is_symlink())
    artifacts = tuple(path for path in files if not path.name.endswith(".manifest.json"))
    if not artifacts:
        raise typer.BadParameter("package requires at least one v2 artifact")
    document_root = source_dir.parent.parent
    ledger = ProvenanceLedgerV2(document_root / "runs" / "v2-provenance.json", trusted_root=document_root)
    expected_manifests: set[Path] = set()
    snapshots: dict[str, bytes] = {}
    generation_identity: tuple[tuple[object, ...], dict[str, tuple[tuple[str, str], ...]]] | None = None
    for artifact in artifacts:
        manifest_path = artifact.with_suffix(artifact.suffix + ".manifest.json")
        if not manifest_path.is_file():
            raise typer.BadParameter(f"package requires a matching manifest for {artifact.name}")
        try:
            artifact_bytes = _read_package_file(artifact, document_root)
            manifest_bytes = _read_package_file(manifest_path, document_root)
            manifest = BuildManifest.from_dict(json.loads(manifest_bytes.decode(encoding="utf-8")))
            manifest.validate_for_publication()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"package requires a valid manifest for {artifact.name}: {exc}") from exc
        artifact_digest = hashlib.sha256(artifact_bytes).hexdigest()
        matching = [
            entry
            for entry in manifest.artifacts
            if (
                entry.path == str(artifact.resolve())
                or (_allow_staging and entry.sha256 == artifact_digest)
            )
        ]
        if len(matching) != 1 or matching[0].sha256 != artifact_digest:
            raise typer.BadParameter(f"package requires the manifest artifact hash to match {artifact.name}")
        if _verify_attestation and not ledger.verify_attestation(manifest.provenance_run or "", manifest.attestation()):
            raise typer.BadParameter(f"package requires a verifiable provenance attestation for {artifact.name}")
        shared_identity = (
            manifest.document_id,
            manifest.source_hash,
            manifest.template_hash,
            manifest.config_hash,
            manifest.context_hash,
            tuple(sorted(manifest.asset_hashes.items())),
        )
        format_name = artifact.suffix.lstrip(".")
        renderer_identity = tuple(sorted(manifest.renderer_versions.items()))
        if generation_identity is None:
            generation_identity = (shared_identity, {format_name: renderer_identity})
        elif shared_identity != generation_identity[0]:
            raise typer.BadParameter(
                f"package refuses mixed source generation for {artifact.name}"
            )
        elif format_name in generation_identity[1] and renderer_identity != generation_identity[1][format_name]:
            raise typer.BadParameter(
                f"package refuses mixed renderer generation for {artifact.name}"
            )
        else:
            generation_identity[1][format_name] = renderer_identity
        expected_manifests.add(manifest_path)
        snapshots[artifact.relative_to(source_dir).as_posix()] = artifact_bytes
        snapshots[manifest_path.relative_to(source_dir).as_posix()] = manifest_bytes
    actual_manifests = {path for path in files if path.name.endswith(".manifest.json")}
    if actual_manifests != expected_manifests:
        raise typer.BadParameter("package requires each manifest to match one v2 artifact")
    return tuple((relative, snapshots[relative]) for relative in sorted(snapshots))


def _read_package_file(path: Path, document_root: Path) -> bytes:
    """Read one immutable package input through a regular-file descriptor."""
    try:
        path.resolve(strict=True).relative_to(document_root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(f"package file escapes document root: {path.name}") from exc
    if any(candidate.is_symlink() for candidate in (path, *path.parents)):
        raise typer.BadParameter(f"package refuses symlinked path: {path.name}")
    resolved = path.resolve(strict=True)
    ancestors = tuple(
        (ancestor, (os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino))
        for ancestor in (document_root, *path.parents)
        if ancestor.exists()
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise typer.BadParameter(f"package refuses unsafe file: {path.name}: {exc}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode) or path.is_symlink():
            raise typer.BadParameter(f"package requires a regular non-symlink file: {path.name}")
        if any(
            (os.stat(ancestor, follow_symlinks=False).st_dev, os.stat(ancestor, follow_symlinks=False).st_ino) != identity
            for ancestor, identity in ancestors
        ):
            raise typer.BadParameter(f"package path boundary changed while reading: {path.name}")
        opened = os.fstat(descriptor)
        expected = os.stat(resolved, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise typer.BadParameter(f"package input changed while reading: {path.name}")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _directory_identity(path: Path) -> tuple[int, int]:
    identity = os.stat(path, follow_symlinks=False)
    return identity.st_dev, identity.st_ino


def _assert_directory_identity(path: Path, expected: tuple[int, int], *, operation: str) -> None:
    if _directory_identity(path) != expected or path.is_symlink() or not path.is_dir():
        raise typer.BadParameter(f"package output parent changed during {operation}: {path}")


@contextmanager
def _package_lock(output: Path):
    """Serialize package read/merge/write transactions across processes."""
    with owned_directory_lock(output.with_name(output.name + ".lock")):
        yield


def _write_package_archive(
    output: Path,
    source_dir: Path,
    *,
    _allow_staging: bool = False,
    _verify_attestation: bool = True,
    _lock_held: bool = False,
) -> None:
    """Validate v2 package inputs and delegate atomic archive publication."""
    with nullcontext() if _lock_held else _package_lock(output):
        files = _package_files(
            source_dir,
            _allow_staging=_allow_staging,
            _verify_attestation=_verify_attestation,
        )
        try:
            PackageServiceV2(
                lock=owned_directory_lock,
                directory_guard=directory_handle_guard,
                normalize_docx_zip_timestamps=normalize_docx_zip_timestamps,
                assert_directory_identity=_assert_directory_identity,
            ).write(
                output,
                tuple(PackageFileV2(relative, content) for relative, content in files),
                lock_held=True,
            )
        except PackagePublicationError as exc:
            raise typer.BadParameter(str(exc)) from exc


@v2_app.command("baseline")
def baseline(
    source_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    destination_dir: Path = typer.Option(..., "--destination", "-d", file_okay=False),
    update: bool = typer.Option(False, "--update", help="Replace an existing baseline explicitly."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Explicitly snapshot rendered PNG previews as a visual baseline."""
    try:
        published = VisualBaselineService().update(source_dir, destination_dir, overwrite=update)
    except VisualBaselineError as exc:
        raise typer.BadParameter(str(exc)) from exc
    payload = {
        "source": str(source_dir.resolve()),
        "destination": str(destination_dir.resolve()),
        "updated": update,
        "pages": [str(path.resolve()) for path in published],
    }
    typer.echo(
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if json_output
        else json.dumps(payload, indent=2, sort_keys=True)
    )


@v2_app.command("inspect")
def inspect(
    artifact: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect an artifact identity without modifying it."""
    payload = _artifact_payload(artifact)
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))


@v2_app.command("diff")
def diff(
    left: Path = typer.Argument(..., exists=True, readable=True),
    right: Path = typer.Argument(..., exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Compare two derived artifacts by identity and readable text when available."""
    left_payload = _artifact_payload(left)
    right_payload = _artifact_payload(right)
    changes: list[str] = []
    try:
        left_text = left.read_text(encoding="utf-8").splitlines(keepends=True)
        right_text = right.read_text(encoding="utf-8").splitlines(keepends=True)
        changes = list(unified_diff(left_text, right_text, fromfile=str(left), tofile=str(right)))
    except UnicodeDecodeError:
        changes = []
    payload = {"same": left_payload["sha256"] == right_payload["sha256"], "left": left_payload, "right": right_payload, "text_diff": changes}
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True) if json_output else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


@v2_app.command("package")
def package(
    source_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Package verified derived artifacts atomically as a ZIP archive."""
    _write_package_archive(output, source_dir)
    payload = {"path": str(output.resolve()), "artifact": _artifact_payload(output)}
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))


@v2_app.command("publish")
def publish(
    ctx: typer.Context,
    source: Path = typer.Argument(..., exists=True, readable=True),
    destination: Path = typer.Argument(...),
    policy: PipelineMode = typer.Option(PipelineMode.release, "--policy"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Publish one verified artifact only under a policy that permits release."""
    selected = PipelinePolicy(policy)
    if not selected.can_publish():
        raise typer.BadParameter("publish requires --policy strict or --policy release")
    manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    document_root = source.parent.parent.parent
    if source.parent.name != "v2" or source.parent.parent.name != "output":
        raise typer.BadParameter("publish requires a v2 artifact with its matching manifest")
    _require_contained(source, document_root / "output" / "v2", "source")
    _require_contained(manifest_path, document_root / "output" / "v2", "manifest")
    if not manifest_path.is_file():
        raise typer.BadParameter("publish requires a v2 artifact with its matching manifest")
    _require_contained(destination, document_root, "destination")
    try:
        manifest_bytes = _read_package_file(manifest_path, document_root)
        manifest = BuildManifest.from_dict(json.loads(manifest_bytes.decode(encoding="utf-8")))
        manifest.validate_for_publication()
    except (ValueError, json.JSONDecodeError) as exc:
        raise typer.BadParameter(f"publish requires a valid manifest: {exc}") from exc
    source_identity = str(source.resolve())
    source_bytes = _read_package_file(source, document_root)
    _require_contained(source, document_root / "output" / "v2", "source")
    _require_contained(manifest_path, document_root / "output" / "v2", "manifest")
    matching = [artifact for artifact in manifest.artifacts if artifact.path == source_identity]
    if len(matching) != 1 or matching[0].sha256 != hashlib.sha256(source_bytes).hexdigest():
        raise typer.BadParameter("publish requires the manifest artifact hash to match the source")
    output_format = source.suffix.removeprefix(".")
    try:
        resolved, config, renderer = _resolve_publish_inputs(ctx, document_root, output_format)
        current = _current_input_identities(
            resolved=resolved,
            config=config,
            renderer=renderer,
            root=document_root,
            output_format=output_format,
        )
    except Exception as exc:
        raise typer.BadParameter(f"publish requires resolvable current inputs: {exc}") from exc
    for field, label in (
        ("template_hash", "template"),
        ("config_hash", "config"),
        ("context_hash", "context"),
        ("asset_hashes", "asset"),
        ("renderer_versions", "renderer"),
        ("source_hash", "source inputs"),
    ):
        if current[field] != getattr(manifest, field):
            raise typer.BadParameter(f"publish requires unchanged {label} identity")
    ledger = ProvenanceLedgerV2(document_root / "runs" / "v2-provenance.json", trusted_root=document_root)
    if not ledger.verify_attestation(manifest.provenance_run or "", manifest.attestation()):
        raise typer.BadParameter("publish requires a present, verifiable provenance attestation")
    destination_manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    def write_publication(scratch: Path) -> None:
        (scratch / "artifact").write_bytes(source_bytes)
        (scratch / "manifest").write_bytes(manifest_bytes)

    publication = AtomicTransform().run(
        TransformSpec(
            expected_outputs=("artifact", "manifest"),
            destinations=(destination, destination_manifest),
        ),
        write_publication,
    )
    if not publication.ok:
        raise typer.BadParameter(f"publish failed: {publication.error}")
    payload = {
        "published": True,
        "artifact": _artifact_payload(destination),
        "manifest": str(destination_manifest.resolve()),
        "warnings": list(publication.warnings),
    }
    typer.echo(json.dumps(payload, sort_keys=True) if json_output else json.dumps(payload, indent=2, sort_keys=True))
