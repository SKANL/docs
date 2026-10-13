"""Provenance, packaging and publication stages of the document pipeline."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from docs.application.document_pipeline_context import PipelineContext, stage_success
from docs.application.pipeline_publication import PipelinePublication
from docs.domain.artifacts import BuildManifest
from docs.domain.identity import sha256_file


class PublishStages:
    """Record provenance, package the release archive, and stage publication."""

    def __init__(
        self,
        ctx: PipelineContext,
        publication_service: PipelinePublication,
        destination: Path,
        pipeline_id: str,
    ) -> None:
        self._ctx = ctx
        self._publication = publication_service
        self._destination = destination
        self._pipeline_id = pipeline_id

    def provenance(self) -> tuple[bool, str]:
        ctx = self._ctx
        state = ctx.state
        if self._pipeline_id == "document-publish":
            passed, detail, digest = self._publication.record_existing(
                ctx.document_id, state.get("artifact"), state.get("manifest")
            )
            if not passed:
                return False, detail
            state["attested_artifact_sha256"] = digest
            return stage_success("provenance", detail)
        state["manifest"] = self._publication.record_build(
            resolved=state["resolved"],
            config=state["config"],
            renderer=state["renderer"],
            root=ctx.document_root,
            artifact=state["artifact"],
            destination=self._destination,
            output_format=ctx.output_format,
            run_id=state["run_id"],
            verification=state.get("verification"),
            stage_artifacts=tuple(state["stage_artifacts"]),
        )
        return stage_success("provenance")

    def publish(self, scratch: Path) -> None:
        ctx = self._ctx
        state = ctx.state
        self._publication.stage(
            scratch=scratch,
            artifact=state.get("artifact"),
            manifest=state.get("manifest"),
            package_candidate=state.get("package_candidate"),
            document_id=ctx.document_id,
            output_format=ctx.output_format,
            existing=self._pipeline_id == "document-publish",
            persisted_manifest=state.get("manifest_path"),
            expected_digest=state.get("attested_artifact_sha256"),
        )

    def native_package_release(self) -> tuple[bool, str]:
        """Package the verified, attested artifact before publication."""
        ctx = self._ctx
        artifact = ctx.state.get("artifact")
        manifest = ctx.state.get("manifest")
        if not isinstance(artifact, Path) or not isinstance(manifest, BuildManifest):
            return False, "package-release requires a verified artifact and manifest"
        release = ctx.document_root / "output" / "release" / f"{ctx.document_id}.zip"
        source_dir = ctx.document_root / "output" / "current"
        source_dir.mkdir(parents=True, exist_ok=True)
        candidate = release.with_name(f".{release.name}.candidate")
        # A package stage runs before this format reaches output/current.  Stage a
        # complete snapshot of the already-published formats plus this run's
        # attested artifact, so repeatable --format builds accumulate one
        # release archive instead of replacing it format by format.
        with ctx.deps.release_lock(release):
            staging = Path(tempfile.mkdtemp(prefix=".docs-package-", dir=source_dir.parent))
            try:
                self._stage_attested_publications(source_dir, staging)
                package_name = f"{ctx.document_id}.{ctx.output_format}"
                shutil.copyfile(artifact, staging / package_name)
                (staging / f"{package_name}.manifest.json").write_text(
                    manifest.to_json() + "\n", encoding="utf-8"
                )
                # Staging changes only the pathname. Its content hash maps to
                # the manifest artifact while the attestation remains verified
                # against the original provenance run.
                ctx.deps.package_publications.package(
                    candidate, staging, allow_staging=True, lock_held=True
                )
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        ctx.state["package_candidate"] = candidate
        return stage_success("package-release", str(candidate))

    def _stage_attested_publications(self, source_dir: Path, staging: Path) -> None:
        """Copy each previously published format whose manifest still attests it."""
        ctx = self._ctx
        for existing in sorted(source_dir.iterdir(), key=lambda path: path.name):
            if existing.is_symlink() or not existing.is_file():
                raise RuntimeError(f"package refuses unsafe source entry: {existing.name}")
            if existing.name.endswith(".manifest.json"):
                continue
            manifest_file = existing.with_name(existing.name + ".manifest.json")
            if not manifest_file.is_file() or manifest_file.is_symlink():
                continue
            try:
                previous = BuildManifest.from_dict(
                    json.loads(manifest_file.read_text(encoding="utf-8"))
                )
                previous.validate_for_publication()
                if previous.document_id != ctx.document_id or not ctx.ledger.verify_attestation(
                    previous.provenance_run, previous.attestation()
                ):
                    continue
                if sha256_file(existing) != previous.artifacts[0].sha256:
                    continue
            except (OSError, TypeError, ValueError, KeyError, IndexError):
                # A stale or malformed derived artifact must not poison
                # a new package. It is replaced only when its format is
                # rebuilt in the current invocation.
                continue
            shutil.copyfile(existing, staging / existing.name)
            shutil.copyfile(manifest_file, staging / manifest_file.name)
