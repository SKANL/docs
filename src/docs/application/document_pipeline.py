"""Application-owned document pipeline composition use case."""

from __future__ import annotations

import inspect as inspect_module
import json
import shutil
import tempfile
import uuid
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from docs.application.artifact_render_service import ArtifactRenderService
from docs.application.build_manifest_service import BuildManifestService
from docs.application.document_input_stages import DocumentInputStageService
from docs.application.document_pipeline_build import BuildStages
from docs.application.document_pipeline_context import PipelineContext
from docs.application.document_pipeline_publish import PublishStages
from docs.application.document_pipeline_review import ReviewStages, create_review_stage_service
from docs.application.document_pipeline_verifiers import _verify_readable_artifact
from docs.application.pipeline_assembly import assemble_explicit_stage_operations
from docs.application.pipeline_publication import PipelinePublication
from docs.application.pipeline_service import PipelineService
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_content, sha256_file
from docs.domain.pipeline_policy import PipelinePolicy
from docs.domain.review import ReviewDimension
from docs.domain.tool_capability import ToolCapability, ToolCapabilityRegistry


def _write_manifest_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


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
                    part.startswith((".docs-", ".atomic-"))
                    for part in path.relative_to(root).parts
                )
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
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
    return _DocumentPipelineBuilder(
        deps,
        output_format,
        policy,
        document,
        pipeline_id,
        provenance_run_id,
        publication_destination,
        artifact_path,
        manifest_path,
    ).build()


def _cleanup_scratch_dirs(scratch_dirs: list[Path]) -> None:
    for path in scratch_dirs:
        shutil.rmtree(path, ignore_errors=True)


class _DocumentPipelineBuilder:
    """Wire the composition-root services into one v2 document pipeline.

    Construction resolves the document and the collaborators; ``build`` maps
    each public stage name to the stage group that implements it.
    """

    def __init__(
        self,
        deps: Any,
        output_format: str,
        policy: PipelinePolicy | None,
        document: str,
        pipeline_id: str,
        provenance_run_id: str | None,
        publication_destination: Path | None,
        artifact_path: Path | None,
        manifest_path: Path | None,
    ) -> None:
        self._deps = deps
        self._output_format = output_format
        self._policy = policy
        self._document = document
        self._pipeline_id = pipeline_id
        self.state: dict[str, Any] = {
            "resolved": None,
            "renderer": None,
            "artifact": None,
            "manifest_path": None,
            "attested_artifact_sha256": None,
        }
        self._scratch_dirs: list[Path] = []

        resolved = self._activate_context()
        self.document_id = resolved.doc_id
        self.document_root = deps.workspace.doc_root(self.document_id)
        self.document_root.mkdir(parents=True, exist_ok=True)
        # Keep publication outside output/published so verification can never
        # promote an artifact, even when the runtime has no explicit
        # no-publish mode.
        self.destination = publication_destination or (
            self.document_root / "output" / "current" / f"{self.document_id}.{output_format}"
        )
        self.release_destination = (
            self.document_root / "output" / "release" / f"{self.document_id}.zip"
        )
        if pipeline_id in {"document-verify", "document-package", "document-publish"}:
            self._seed_existing_artifacts(artifact_path, manifest_path)

        self.resources = deps.create_pipeline_resources(
            renderer=self.state["renderer"],
            output_format=output_format,
            document_root=self.document_root,
            document_id=self.document_id,
            paths=self.state["config"].get("paths", {}) or {},
            atomic_file_writer=deps.atomic_file_writer,
            artifact=lambda: self.state.get("artifact"),
            manifest=lambda: self.state.get("manifest"),
            package_writer=lambda candidate, staging: deps.package_publications.package(
                candidate, staging, allow_staging=True, lock_held=True
            ),
            candidate_sink=lambda candidate: self.state.__setitem__("package_candidate", candidate),
            verify_current_build=pipeline_id == "document-package",
        )
        self.state["stage_artifacts"] = []
        self.state["run_id"] = provenance_run_id or f"cli-build-{output_format}-{uuid.uuid4().hex}"

        ctx = PipelineContext(
            deps=deps,
            output_format=output_format,
            policy=policy,
            state=self.state,
            scratch_dirs=self._scratch_dirs,
            document_root=self.document_root,
            document_id=self.document_id,
            ledger=self.resources.ledger,
        )
        artifact_renderer = ArtifactRenderService(
            scratch_factory=_scratch_directory,
            validator=_verify_readable_artifact,
        )
        self.stage_provider = deps.create_stage_provider(
            config=self.state["config"],
            output_format=output_format,
            ensure_assets=self._ensure_assets,
            extra_services={"package_release_service": self.resources.publication},
        )
        source_pipeline = deps.create_source_pipeline()
        self.review = ReviewStages(
            ctx, self.stage_provider, create_review_stage_service(deps)
        )
        self.input_stages = DocumentInputStageService(
            document_id=self.document_id,
            document_root=self.document_root,
            output_format=output_format,
            state=self.state,
            resolve_context=lambda: deps.resolve_context(document),
            resolve_renderer=deps.resolve_renderer,
            figure_pipeline=getattr(getattr(deps, "ingest", None), "figures", None),
            source_pipeline=source_pipeline,
            fallback_stage=self._callable_stage,
        )
        self.build_stages = BuildStages(ctx, artifact_renderer, uuid.uuid4().hex)
        self.publish_stages = PublishStages(
            ctx,
            PipelinePublication(
                BuildManifestService(
                    input_identities=_current_input_identities,
                    build_inputs=_build_inputs,
                    artifact_hash=sha256_file,
                    write_text=_write_manifest_text,
                ),
                self.resources.ledger,
            ),
            self.destination,
            pipeline_id,
        )

    def _activate_context(self) -> Any:
        resolved = self._deps.resolve_context(self._document)
        self.state["resolved"] = resolved
        config = deepcopy(resolved.config)
        config.setdefault("output", {})["format"] = self._output_format
        self.state["config"] = config
        self.state["renderer"] = self._deps.resolve_renderer(config)
        return resolved

    def _seed_existing_artifacts(
        self, artifact_path: Path | None, manifest_path: Path | None
    ) -> None:
        """Load the previously built artifact, manifest and package candidate."""
        state = self.state
        source_artifact = artifact_path or self.destination
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
        if self.release_destination.is_file():
            state["package_candidate"] = self.release_destination

    def _ensure_assets(self) -> tuple[bool, str]:
        return self.input_stages.resolve_assets()

    def _callable_stage(self, name: str) -> Any:
        operation = self.stage_provider.get(name)
        return operation if callable(operation) else None

    def _review_stage_operation(self, stage: str, fallback: Any) -> Any:
        if self.review.service is not None:
            return lambda: self.review.review_stage(stage)
        return fallback

    def build(self) -> PipelineService:
        deps = self._deps
        output_format = self._output_format
        build_stages = self.build_stages
        publish_stages = self.publish_stages
        review = self.review
        input_stages = self.input_stages
        state = self.state
        explicit_stages = assemble_explicit_stage_operations(
            self.stage_provider,
            callbacks={
                "structural_audit": review.structural_audit,
                "accessibility_review": review.accessibility_review,
                "visual_review": review.visual_review,
                "reproducibility_check": review.reproducibility_check,
                "review_stage": lambda name: lambda: review.review_stage(name),
                "build_with_format": lambda name: lambda: build_stages.build_with_format(name),
                "render": build_stages.render,
            },
            output_format=output_format,
            review_stages_available=review.service is not None,
        )
        operations: dict[str, Any] = {
            "resolve-config": input_stages.resolve_config,
            "resolve-template": input_stages.resolve_template,
            "resolve-context": input_stages.resolve_context_stage,
            "resolve-assets": input_stages.resolve_assets,
            "validate-contracts": input_stages.validate_contracts,
            "ingest-sources": lambda: input_stages.source_stage("ingest-sources"),
            "normalize-sources": lambda: input_stages.source_stage("normalize-sources"),
            "compile-structure": lambda: input_stages.source_stage("compile-structure"),
            "build-docx": build_stages.render,
            "structural-audit": self._review_stage_operation("structural-audit", build_stages.audit),
            "editorial-review": self._review_stage_operation("editorial-review", build_stages.verify),
            "record-provenance": publish_stages.provenance,
            "evidence-review": self._review_stage_operation(
                "evidence-review",
                self._callable_stage("evidence_review")
                or (lambda: review.document_review("evidence-review", ReviewDimension.EVIDENCE)),
            ),
            "consistency-review": self._review_stage_operation(
                "consistency-review",
                self._callable_stage("consistency_review")
                or (lambda: review.document_review("consistency-review", ReviewDimension.CONSISTENCY)),
            ),
            "package-release": self.stage_provider.operation("package_release")
            or publish_stages.native_package_release,
        }
        operations.update(
            {name.replace("_", "-"): operation for name, operation in explicit_stages.items()}
        )
        return deps.create_document_pipeline(
            operations=operations,
            expected_outputs=(
                f"primary.{output_format}",
                f"primary.{output_format}.manifest.json",
                f"{self.document_id}.zip",
            ),
            destinations=(
                self.destination,
                self.destination.with_suffix(self.destination.suffix + ".manifest.json"),
                self.release_destination,
            ),
            operation=publish_stages.publish,
            capabilities=self.resources.capabilities,
            ledger=self.resources.ledger,
            policy=self._policy,
            run_id_sink=lambda value: state.__setitem__("run_id", value),
            excluded_stages=frozenset(
                {"build-docx", "build-html", "build-pdf"} - {f"build-{output_format}"}
            ),
            cleanup=lambda: _cleanup_scratch_dirs(self._scratch_dirs),
            artifact_store=self.resources.artifact_store,
            record_sink=state["stage_artifacts"].extend,
            run_start=state["stage_artifacts"].clear,
        )
