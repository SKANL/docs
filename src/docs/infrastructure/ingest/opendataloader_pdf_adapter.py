# src/docs/infrastructure/ingest/opendataloader_pdf_adapter.py
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import opendataloader_pdf

from docs.domain.ingest_naming import ingested_output_path, sha256_hex
from docs.domain.ports.tool_resolver_port import ToolResolverPort
from docs.infrastructure.ingest.atomic_ingest_write import atomic_finalize, scratch_dir

_KIND = "pdf"


def resolve_java_executable(paths: dict[str, Any]) -> str | None:
    """Mirrors `resolve_pandoc_executable`'s PATH-then-config-fallback shape
    (5.1 spike condition: resolve Java via the existing `ToolResolverPort`
    pattern). `opendataloader_pdf`'s bundled runner always invokes the bare
    `"java"` command, so a configured `java_bin`/`java_fallbacks` entry only
    takes effect when its directory is temporarily prepended to `PATH`
    (see `_java_on_path` below) for the duration of the conversion call."""
    resolved = shutil.which("java")
    if resolved:
        return resolved
    configured = paths.get("java_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("java_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None


@contextmanager
def _java_on_path(java_executable: str) -> Iterator[None]:
    java_dir = str(Path(java_executable).parent)
    original = os.environ.get("PATH", "")
    if java_dir and java_dir not in original.split(os.pathsep):
        os.environ["PATH"] = java_dir + os.pathsep + original
    try:
        yield
    finally:
        os.environ["PATH"] = original


class OpendataloaderPdfAdapter:
    """`SourceIngestPort` implementation for PDF sources via
    `opendataloader-pdf` (document-ingest spec: `Type-Based Ingest Routing`
    scenario "PDF routed to opendataloader-pdf").

    Binding conditions from the 5.1 spike / PR5 fresh-review round 2:
    each `opendataloader_pdf.convert()` call spawns its own JVM, so every
    call to `ingest()` looks ahead at sibling `.pdf` files still pending
    conversion in the same source directory (the inbox) and converts ALL of
    them in ONE `convert()` call, caching results so subsequent `ingest()`
    calls for those siblings within the same scan are free. Hybrid AI/OCR
    backends stay off (`hybrid="off"`) for local-only, deterministic output.
    """

    def __init__(self, tool_resolver: ToolResolverPort, paths: dict[str, Any] | None = None) -> None:
        self.tool_resolver = tool_resolver
        self.paths = paths or {}
        self._results: dict[Path, Path | Exception] = {}

    def ingest(self, src: Path, out_dir: Path) -> Path:
        src = Path(src).resolve()
        out_dir = Path(out_dir)
        if src not in self._results:
            self._convert_batch(src, out_dir)
        result = self._results[src]
        if isinstance(result, Exception):
            raise result
        return result

    def _discover_candidates(self, seed_src: Path, out_dir: Path) -> list[Path]:
        inbox_dir = seed_src.parent
        candidates = [
            path
            for path in sorted(inbox_dir.iterdir())
            if path.is_file()
            and not path.name.startswith("_")
            and path.suffix.lower() == ".pdf"
            and not self._already_ingested(path, out_dir)
        ]
        if seed_src not in candidates:
            candidates.insert(0, seed_src)
        return candidates

    def _already_ingested(self, path: Path, out_dir: Path) -> bool:
        sha8 = sha256_hex(path.read_bytes())[:8]
        return ingested_output_path(out_dir, path.stem, _KIND, sha8).exists()

    def _convert_batch(self, seed_src: Path, out_dir: Path) -> None:
        java = self.tool_resolver.resolve_java(self.paths)
        if not java:
            error = RuntimeError(
                "Java (JRE 11+) no está disponible en PATH. opendataloader-pdf lo "
                "requiere para ingerir archivos PDF; instálalo y vuelve a intentar."
            )
            self._results[seed_src] = error
            return

        candidates = self._discover_candidates(seed_src, out_dir)

        # Temp-then-atomic-rename (binding constraint carried from PR5
        # fresh-review round 2): conversion runs entirely inside a scratch
        # directory under `out_dir`; only files that actually produced
        # Markdown output are moved into their final, deterministic path.
        # A file that failed conversion never touches `out_dir`.
        with scratch_dir(out_dir) as tmp_dir:
            batch_error: subprocess.CalledProcessError | None = None
            try:
                with _java_on_path(java):
                    opendataloader_pdf.convert(
                        input_path=[str(c) for c in candidates],
                        output_dir=str(tmp_dir),
                        format="markdown",
                        image_output="off",
                        hybrid="off",
                        quiet=True,
                    )
            except subprocess.CalledProcessError as exc:
                batch_error = exc

            for candidate in candidates:
                tmp_output = tmp_dir / f"{candidate.stem}.md"
                if tmp_output.exists():
                    sha8 = sha256_hex(candidate.read_bytes())[:8]
                    final = ingested_output_path(out_dir, candidate.stem, _KIND, sha8)
                    self._results[candidate] = atomic_finalize(tmp_output, final)
                else:
                    cause = (batch_error.stdout or str(batch_error)) if batch_error else (
                        "opendataloader-pdf no generó salida para este archivo."
                    )
                    self._results[candidate] = RuntimeError(
                        f"No se pudo convertir {candidate.name} con opendataloader-pdf: {cause}"
                    )
