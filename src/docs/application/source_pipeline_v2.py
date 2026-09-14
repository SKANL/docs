"""Deterministic v2 source preparation stages."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from docs.application.flat_pipeline_compatibility import strict_policy_error
from docs.domain.docx_structure import structure_parts
from docs.domain.ports.atomic_file_port import AtomicFilePort
from docs.domain.ports.markdown_normalizer_port import MarkdownNormalizerPort


class SourcePipelineV2:
    """Coordinate source stages without changing the legacy pipeline."""

    def __init__(
        self,
        ingest_service: Any,
        normalizer: MarkdownNormalizerPort,
        file_writer: AtomicFilePort,
    ) -> None:
        self.ingest_service = ingest_service
        self.normalizer = normalizer
        self.file_writer = file_writer

    def ingest(
        self, document_id: str, document_root: Path, config: dict[str, Any], strict: bool = False
    ) -> dict[str, Any]:
        root = Path(document_root)
        try:
            paths = self._paths(root, config)
            ingest_operation: Any = getattr(self.ingest_service, "ingest_inbox", None)
            ingest_args: tuple[Path, ...] = (paths["inbox"], paths["sections"])
            ingest_kwargs: dict[str, Any] = {"assets_dir": paths["assets"]}
            strict_supported = self._supports_strict(ingest_operation)
            if self._parameter_is_positional_only(ingest_operation, "assets_dir"):
                ingest_args += (paths["assets"],)
                ingest_kwargs.pop("assets_dir")
            if strict_supported:
                ingest_kwargs["strict"] = strict
            result = ingest_operation(*ingest_args, **ingest_kwargs)
        except Exception as exc:
            result = {"status": "failed", "processed": 0, "files": [], "errors": [str(exc)]}
            paths = self._fallback_paths(root)
        if not isinstance(result, Mapping):
            result = {
                "status": "failed",
                "processed": 0,
                "files": [],
                "errors": ["v2 ingest result must be a mapping"],
            }
        adapter_policy = result.get("strict_policy")
        if adapter_policy is None:
            report_policy = {
                "requested": strict,
                "applied": False,
                "mode": "advisory",
            }
            policy_error = None
        elif isinstance(adapter_policy, Mapping):
            report_policy = dict(adapter_policy)
            policy_error = strict_policy_error(report_policy, strict)
        else:
            report_policy = {
                "requested": strict,
                "applied": False,
                "mode": "advisory",
            }
            policy_error = strict_policy_error(adapter_policy, strict)
        if policy_error is not None:
            result = dict(result)
            result.update({"status": "failed", "errors": [policy_error]})
        elif strict and report_policy.get("applied") is not True:
            report_policy.update({
                "requested": True,
                "applied": False,
                "mode": "advisory",
                "warning": "v2 ingest does not expose strict enforcement",
            })
        result = dict(result)
        report = self._report(
            document_id,
            "ingest-sources",
            result,
            paths,
            self._ingest_artifacts(result, root, paths),
        )
        report["strict_policy"] = report_policy
        if policy_error is not None:
            report["errors"] = [{
                "code": "pipeline.malformed_strict_policy",
                "message": f"The v2 ingest strict_policy is contradictory: {policy_error}",
            }]
        return self._persist_report_safely(root, config, "ingest", report)

    def normalize(self, document_id: str, document_root: Path, config: dict[str, Any]) -> dict[str, Any]:
        root = Path(document_root)
        normalized: list[str] = []
        try:
            paths = self._paths(root, config)
            for source in sorted((paths["sections"] / "ingested").glob("*.md"), key=lambda p: p.name):
                original = source.read_text(encoding="utf-8")
                content = self.normalizer.normalize(original)
                if content != original:
                    with self.file_writer.scratch_dir(source.parent) as scratch:
                        candidate = scratch / source.name
                        candidate.write_text(content, encoding="utf-8")
                        self.file_writer.atomic_finalize(candidate, source)
                normalized.append(self._artifact_path(source, root))
            result = {"normalized": normalized, "count": len(normalized)}
        except Exception as exc:
            result = {"normalized": normalized, "count": len(normalized), "status": "failed", "errors": [str(exc)]}
            paths = self._fallback_paths(root)
        report = self._report(document_id, "normalize-sources", result, paths, tuple(normalized))
        return self._persist_report_safely(root, config, "prepare", report)

    def compile_structure(
        self, document_id: str, document_root: Path, config: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(document_root)
        try:
            paths = self._paths(root, config)
            ingested = sorted(
                (self._artifact_path(path, root) for path in (paths["sections"] / "ingested").glob("*.md")),
            )
            structure = {
                "schema": "docs.structure/v2",
                "document_id": document_id,
                "parts": structure_parts(config),
                "sources": ingested,
            }
            destination = paths["sections"] / "v2-structure.json"
            self._atomic_json(destination, structure)
            result = structure
            artifacts = tuple(ingested)
        except Exception as exc:
            result = {"status": "failed", "errors": [str(exc)]}
            artifacts = ()
            paths = self._fallback_paths(root)
        report = self._report(document_id, "compile-structure", result, paths, artifacts)
        return self._persist_report_safely(root, config, "prepare", report)

    def prepare(self, document_id: str, document_root: Path, config: dict[str, Any]) -> dict[str, Any]:
        ingest = self.ingest(document_id, document_root, config)
        if not ingest["succeeded"]:
            stages = [
                ingest,
                self._skipped_stage("normalize-sources", "ingest-sources"),
                self._skipped_stage("compile-structure", "normalize-sources"),
            ]
        else:
            normalize = self.normalize(document_id, document_root, config)
            stages = [
                ingest,
                normalize,
                self.compile_structure(document_id, document_root, config)
                if normalize["succeeded"]
                else self._skipped_stage("compile-structure", "normalize-sources"),
            ]
        report = {
            "schema": "docs.sources/v2",
            "document_id": document_id,
            "succeeded": all(stage["succeeded"] for stage in stages),
            "stages": [stage["stages"][0] for stage in stages],
            "artifacts": sorted({artifact for stage in stages for artifact in stage["artifacts"]}),
        }
        return self._persist_report_safely(Path(document_root), config, "prepare", report)

    @staticmethod
    def _skipped_stage(stage: str, dependency: str) -> dict[str, Any]:
        return {
            "schema": "docs.sources/v2",
            "succeeded": False,
            "stages": [{
                "name": stage,
                "succeeded": False,
                "skipped": True,
                "result": {
                    "status": "skipped",
                    "reason": "dependency_failed",
                    "depends_on": dependency,
                },
            }],
            "artifacts": [],
        }

    def run_stage(
        self, stage: str, document_id: str, document_root: Path, config: dict[str, Any]
    ) -> tuple[bool, str]:
        operation = {
            "ingest-sources": self.ingest,
            "normalize-sources": self.normalize,
            "compile-structure": self.compile_structure,
        }[stage]
        report = operation(document_id, document_root, config)
        return report["succeeded"], json.dumps(report, sort_keys=True)

    @staticmethod
    def _paths(root: Path, config: dict[str, Any]) -> dict[str, Path]:
        configured = config.get("paths", {})
        runs_dir = Path(configured.get("runs_dir", root / "runs"))
        if not runs_dir.is_absolute():
            runs_dir = root / runs_dir
        def resolve_configured(name: str, default: str) -> Path:
            path = Path(configured.get(name, root / default))
            return path if path.is_absolute() else root / path

        return {
            "inbox": resolve_configured("inbox_dir", "inbox"),
            "sections": resolve_configured("sections_dir", "sections"),
            "assets": resolve_configured("assets_dir", "assets"),
            "runs": runs_dir,
        }

    @staticmethod
    def _fallback_paths(root: Path) -> dict[str, Path]:
        return {
            "inbox": root / "inbox",
            "sections": root / "sections",
            "assets": root / "assets",
            "runs": root / "runs",
        }

    @staticmethod
    def _report(
        document_id: str,
        stage: str,
        result: dict[str, Any],
        paths: dict[str, Path],
        artifacts: tuple[str, ...],
    ) -> dict[str, Any]:
        succeeded = SourcePipelineV2._result_succeeded(result)
        report = {
            "schema": "docs.sources/v2",
            "document_id": document_id,
            "succeeded": True,
            "stages": [{"name": stage, "succeeded": succeeded, "result": result}],
            "artifacts": sorted(artifacts),
        }
        report["succeeded"] = succeeded
        return report

    @staticmethod
    def _result_succeeded(result: dict[str, Any]) -> bool:
        if "succeeded" in result:
            return result["succeeded"] if isinstance(result["succeeded"], bool) else False
        status = result.get("status")
        if isinstance(status, str) and status.casefold() in {"failed", "degraded", "error"}:
            return False
        if result.get("errors"):
            return False
        files = result.get("files", ())
        return not (isinstance(files, list) and any(
            isinstance(item, dict)
            and str(item.get("status", "")).casefold() in {"failed", "degraded", "error"}
            for item in files
        ))

    def _persist_report(self, runs_dir: Path, name: str, report: dict[str, Any]) -> dict[str, Any]:
        destination = runs_dir / f"v2-{name}.json"
        self._atomic_json(destination, report)
        return report

    def _persist_report_safely(
        self, root: Path, config: dict[str, Any], name: str, report: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            runs_dir = self._paths(root, config)["runs"]
            return self._persist_report(runs_dir, name, report)
        except Exception as exc:
            failed = dict(report)
            failed["succeeded"] = False
            stages = failed.get("stages")
            if isinstance(stages, list) and len(stages) == 1 and isinstance(stages[0], Mapping):
                stage = dict(stages[0])
                stage["succeeded"] = False
                failed["stages"] = [stage]
            failed["errors"] = [{
                "code": "pipeline.v2_report_persistence_failed",
                "message": f"The required v2 {name} report could not be persisted: {exc}",
            }]
            return failed

    @classmethod
    def _ingest_artifacts(
        cls, result: Mapping[str, Any], root: Path, paths: Mapping[str, Path] | None = None
    ) -> tuple[str, ...]:
        files = result.get("files")
        if not isinstance(files, list):
            return ()
        artifacts: set[str] = set()
        for entry in files:
            if not isinstance(entry, Mapping):
                continue
            status = str(entry.get("status", "")).casefold()
            if status in {"failed", "degraded", "error", "unsupported", "ignored", "empty_dir"}:
                continue
            raw_path = entry.get("output", entry.get("path"))
            if not isinstance(raw_path, (str, Path)) or not str(raw_path):
                continue
            raw = Path(raw_path)
            if not raw.is_absolute() and ".." in raw.parts:
                continue
            candidates = [raw] if raw.is_absolute() else [root / raw]
            if not raw.is_absolute() and paths is not None:
                candidates.extend(output_root / raw for output_root in cls._output_roots(paths))
            for path in candidates:
                if cls._is_allowed_artifact(path, root, paths):
                    artifacts.add(cls._artifact_path(path.resolve(), root))
                    break
        return tuple(sorted(artifacts))

    @staticmethod
    def _output_roots(paths: Mapping[str, Path] | None) -> tuple[Path, ...]:
        if paths is None:
            return ()
        return tuple(paths[name] for name in ("sections", "assets", "runs") if name in paths)

    @classmethod
    def _is_allowed_artifact(
        cls, path: Path, root: Path, paths: Mapping[str, Path] | None
    ) -> bool:
        if not path.is_file():
            return False
        try:
            resolved_path = path.resolve(strict=True)
        except OSError:
            return False
        try:
            resolved_path.relative_to(root.resolve(strict=False))
        except ValueError:
            return False
        allowed_roots = cls._output_roots(paths) or (
            root / "sections",
            root / "assets",
            root / "runs",
        )
        for allowed_root in allowed_roots:
            try:
                resolved_path.relative_to(allowed_root.resolve(strict=False))
            except ValueError:
                continue
            return True
        return False

    def _atomic_json(self, destination: Path, payload: dict[str, Any]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.file_writer.scratch_dir(destination.parent) as scratch:
            candidate = scratch / destination.name
            candidate.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.file_writer.atomic_finalize(candidate, destination)

    @staticmethod
    def _artifact_path(path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _supports_strict(operation: Any) -> bool:
        try:
            parameters = inspect.signature(operation).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            (
                parameter.name == "strict"
                and parameter.kind
                in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            )
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    @staticmethod
    def _parameter_is_positional_only(operation: Any, name: str) -> bool:
        try:
            parameter = inspect.signature(operation).parameters.get(name)
        except (TypeError, ValueError):
            return False
        return parameter is not None and parameter.kind is inspect.Parameter.POSITIONAL_ONLY
