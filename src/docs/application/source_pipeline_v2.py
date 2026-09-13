"""Deterministic v2 source preparation stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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

    def ingest(self, document_id: str, document_root: Path, config: dict[str, Any]) -> dict[str, Any]:
        root = Path(document_root)
        paths = self._paths(root, config)
        try:
            result = self.ingest_service.ingest_inbox(
                paths["inbox"], paths["sections"], assets_dir=paths["assets"]
            )
        except Exception as exc:
            result = {"status": "failed", "processed": 0, "files": [], "errors": [str(exc)]}
        report = self._report(document_id, "ingest-sources", result, paths, ())
        return self._persist_report(root, "ingest", report)

    def normalize(self, document_id: str, document_root: Path, config: dict[str, Any]) -> dict[str, Any]:
        root = Path(document_root)
        paths = self._paths(root, config)
        normalized: list[str] = []
        try:
            for source in sorted((paths["sections"] / "ingested").glob("*.md"), key=lambda p: p.name):
                original = source.read_text(encoding="utf-8")
                content = self.normalizer.normalize(original)
                if content != original:
                    with self.file_writer.scratch_dir(source.parent) as scratch:
                        candidate = scratch / source.name
                        candidate.write_text(content, encoding="utf-8")
                        self.file_writer.atomic_finalize(candidate, source)
                normalized.append(source.relative_to(root).as_posix())
            result = {"normalized": normalized, "count": len(normalized)}
        except Exception as exc:
            result = {"normalized": normalized, "count": len(normalized), "status": "failed", "errors": [str(exc)]}
        report = self._report(document_id, "normalize-sources", result, paths, tuple(normalized))
        return self._persist_report(root, "prepare", report)

    def compile_structure(
        self, document_id: str, document_root: Path, config: dict[str, Any]
    ) -> dict[str, Any]:
        root = Path(document_root)
        paths = self._paths(root, config)
        ingested = sorted(
            (path.relative_to(root).as_posix() for path in (paths["sections"] / "ingested").glob("*.md")),
        )
        structure = {
            "schema": "docs.structure/v2",
            "document_id": document_id,
            "parts": structure_parts(config),
            "sources": ingested,
        }
        destination = paths["sections"] / "v2-structure.json"
        self._atomic_json(destination, structure)
        report = self._report(document_id, "compile-structure", structure, paths, tuple(ingested))
        return self._persist_report(root, "prepare", report)

    def prepare(self, document_id: str, document_root: Path, config: dict[str, Any]) -> dict[str, Any]:
        stages = [
            self.ingest(document_id, document_root, config),
            self.normalize(document_id, document_root, config),
            self.compile_structure(document_id, document_root, config),
        ]
        report = {
            "schema": "docs.sources/v2",
            "document_id": document_id,
            "succeeded": all(stage["succeeded"] for stage in stages),
            "stages": [stage["stages"][0] for stage in stages],
            "artifacts": sorted({artifact for stage in stages for artifact in stage["artifacts"]}),
        }
        return self._persist_report(Path(document_root), "prepare", report)

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
        return {
            "inbox": Path(configured.get("inbox_dir", root / "inbox")),
            "sections": Path(configured.get("sections_dir", root / "sections")),
            "assets": Path(configured.get("assets_dir", root / "assets")),
            "runs": Path(configured.get("runs_dir", root / "runs")),
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
        explicit = result.get("succeeded")
        if isinstance(explicit, bool):
            return explicit
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

    def _persist_report(self, root: Path, name: str, report: dict[str, Any]) -> dict[str, Any]:
        destination = root / "runs" / f"v2-{name}.json"
        self._atomic_json(destination, report)
        return report

    def _atomic_json(self, destination: Path, payload: dict[str, Any]) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.file_writer.scratch_dir(destination.parent) as scratch:
            candidate = scratch / destination.name
            candidate.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.file_writer.atomic_finalize(candidate, destination)
