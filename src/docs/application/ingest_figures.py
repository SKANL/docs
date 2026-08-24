# src/docs/application/ingest_figures.py
"""Turning ingested sources into routed assets and a figure catalog.

Extracted from `IngestService` for a reason stronger than line count:
this cluster OWNS three of the seven ports that class was injected
with -- `ImageMetadataPort`, `PdfRenderPort`, `SvgRasterizerPort` --
and nothing else in ingest touches any of them. They were optional
constructor arguments on a class that mostly ignored them.

All three degrade to WARN+skip when their toolchain is absent; a
missing rasterizer costs you a figure, never the ingest run.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace as _dataclass_replace
from pathlib import Path
from typing import Any

from docs.application.ingest_classification import SourceClassifier
from docs.application.ingest_names import (
    IMAGE_EXTENSIONS,
    PLACEMENT_QUEUE_NAME,
    VECTOR_EXTENSIONS,
    guess_asset_kind,
)
from docs.domain.figure_catalog import FigureEntry
from docs.domain.figure_catalog import build as build_figure_catalog
from docs.domain.figure_filter import should_catalog_figure
from docs.domain.ingest_naming import sha256_hex
from docs.domain.ports.image_metadata_port import ImageMetadataPort
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.ports.pdf_render_port import PdfRenderPort
from docs.domain.ports.svg_rasterizer_port import SvgRasterizerPort
from docs.domain.source_role import classify
from docs.domain.svg_normalize import normalize_svg


def _structure_part_for_kind(kind: str, asset_name: str) -> dict[str, str]:
    part_type = "cover_from_asset" if kind == "cover" else "embed_docx"
    return {"type": part_type, "asset": asset_name}



class FigureIngestPipeline:
    """Asset routing, figure cataloguing and vector rasterization."""

    def __init__(
        self,
        writer: IngestArtifactWriter,
        classifier: SourceClassifier,
        image_metadata: ImageMetadataPort | None = None,
        pdf_render: PdfRenderPort | None = None,
        svg_rasterizer: SvgRasterizerPort | None = None,
    ) -> None:
        self.writer = writer
        # Role resolution stays with the classifier: the figure
        # pipeline needs prior confirmed roles, it does not own them.
        self.classifier = classifier
        self.image_metadata = image_metadata
        self.pdf_render = pdf_render
        self.svg_rasterizer = svg_rasterizer

    # --- Front F: verbatim assets + placement queue (design.md Decision 6a)

    def route_and_queue_assets(
        self,
        inbox_dir: Path,
        declared_assets: list[tuple[Path, str]],
        heuristic_candidates: list[tuple[Path, str]],
        assets_dir: Path | None,
    ) -> list[dict[str, Any]]:
        # Pipeline order (design.md Decision 6a): asset-routing -> recursive
        # walk -> ingest -> near-dup -> classification queue. Declared
        # assets (inbox/assets/) are routed UNCONDITIONALLY -- their
        # presence there IS the declaration. Heuristic candidates elsewhere
        # (image files, or a cover/portada/anexo-visual-signaled .docx) are
        # only PROPOSED, never auto-routed -- and excluded from `sources` by
        # `_walk_inbox` so they are never flattened to markdown before a
        # human confirms a placement either way.
        prior_confirmed = self._read_prior_confirmed_placements(inbox_dir)
        candidates: dict[str, str] = {}  # relative_path -> proposed_kind ("" if none)
        for _path, rel in declared_assets:
            candidates[rel] = guess_asset_kind(rel) or ""
        for _path, rel in heuristic_candidates:
            candidates[rel] = guess_asset_kind(rel) or ""

        declared_by_rel = {rel: path for path, rel in declared_assets}
        source_by_rel = {rel: path for path, rel in heuristic_candidates}

        queue_entries: dict[str, dict[str, Any]] = {}
        placements: list[dict[str, Any]] = []
        for rel in sorted(candidates):
            proposed_kind = candidates[rel] or None
            confirmed_placement = prior_confirmed.get(rel)
            # A heuristic candidate with no proposed kind has nothing to
            # confirm: it is a figure (it lands in the figure catalog), not a
            # document-structure asset. Queueing it floods the confirmation
            # queue with unanswerable entries -- the first real drop produced
            # 59 such nulls against 1 real cover. A DECLARED asset always
            # queues even without a guessable kind: putting it in
            # inbox/assets/ is itself the request to place it.
            if rel not in declared_by_rel and proposed_kind is None:
                continue
            queue_entries[rel] = {
                "proposed_kind": proposed_kind,
                "confirmed_placement": confirmed_placement,
            }

            src_path = declared_by_rel.get(rel) or source_by_rel.get(rel)
            asset_name = Path(rel).name
            routed = rel in declared_by_rel  # unconditionally routed
            if confirmed_placement and assets_dir is not None and src_path is not None:
                # A CONFIRMED heuristic asset is routed now too (declared
                # ones were already routed below, copy is idempotent).
                self._copy_asset(src_path, assets_dir, asset_name)
                routed = True
            structure_part = (
                _structure_part_for_kind(confirmed_placement, asset_name)
                if confirmed_placement
                else None
            )
            placements.append(
                {
                    "relative_path": rel,
                    "proposed_kind": proposed_kind,
                    "confirmed_placement": confirmed_placement,
                    "routed": routed,
                    "structure_part": structure_part,
                }
            )

        if assets_dir is not None:
            for path, rel in declared_assets:
                self._copy_asset(path, assets_dir, Path(rel).name)

        self.writer.write_json(
            inbox_dir / PLACEMENT_QUEUE_NAME, {"schema": 1, "entries": queue_entries}
        )
        return placements

    def _copy_asset(self, src: Path, assets_dir: Path, name: str) -> None:
        # Temp-then-atomic-rename (ADR-3; matches the established
        # `atomic_ingest_write.py` convention already used by ingest
        # adapters) -- a failure mid-copy never leaves a partial file at the
        # deterministic `name` path a later idempotency check could accept.
        assets_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=assets_dir, prefix=".asset-tmp-")
        try:
            os.close(fd)
            shutil.copyfile(src, tmp_name)
            os.replace(tmp_name, assets_dir / name)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def _read_prior_confirmed_placements(self, inbox_dir: Path) -> dict[str, str]:
        queue_path = inbox_dir / PLACEMENT_QUEUE_NAME
        if not queue_path.exists():
            return {}
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        confirmed: dict[str, str] = {}
        for relative_path, entry in data.get("entries", {}).items():
            placement = entry.get("confirmed_placement")
            if placement:
                confirmed[relative_path] = placement
        return confirmed

    # --- Front F: figure catalog (design.md Decision 6b) -----------------
    #
    # S0.2 (smart-figure-embedding): today's `inbox/` intake only ever
    # presents a figure candidate as (a) a standalone loose image file
    # (`image_candidates` below) or (b) a page inside a vector PDF
    # (`_render_vector_pdf_figures`) -- the two branches this method
    # handles. Embedded-raster-inside-a-PDF/DOCX extraction is deferred
    # (design.md "Approved LEAN scope"); no third arrival mode reaches this
    # method today, so no fixture/branch for it is added here.

    def _effective_role(self, rel: str, confirmed_roles: dict[str, str]) -> str:
        # ADR-1 role resolution: a validated confirmed role (already
        # filtered against `_VALID_ROLES` by `read_prior_confirmed_roles`)
        # wins over raw `classify()` -- a human/agent confirmation beats
        # the folder/filename heuristic.
        role = confirmed_roles.get(rel)
        if role is not None:
            return role
        return classify(rel)[0]

    def _copy_standalone_figure(self, src: Path, entry: FigureEntry, assets_dir: Path) -> FigureEntry:
        # ADR-3 stable-path copy: deterministic `fig-<sha8><ext>` name so a
        # later `assemble` stage (inbox gone) can resolve every catalog row
        # uniformly, regardless of `origin_kind`.
        sha8 = entry.sha256[:8]
        ext = Path(entry.origin_relative_path).suffix.lower()
        name = f"fig-{sha8}{ext}"
        self._copy_asset(src, assets_dir / "figures", name)
        return _dataclass_replace(entry, origin_relative_path=f"assets/figures/{name}")

    def build_figure_catalog_for(
        self,
        inbox_dir: Path,
        sections_dir: Path,
        declared_assets: list[tuple[Path, str]],
        heuristic_candidates: list[tuple[Path, str]],
        entries: list[dict[str, Any]] | None = None,
        assets_dir: Path | None = None,
    ) -> None:
        # S0.1: `assets_dir` here is the SAME value `stage_ingest`
        # (`application/pipeline.py`) resolves from
        # `config["paths"]["assets_dir"]` (`cli/_shared.py:_computed_paths`,
        # `doc_root / "assets"`) -- confirmed at the composition root, no
        # new accessor needed.
        confirmed_roles = self.classifier.read_prior_confirmed_roles(inbox_dir)
        image_candidates = [
            (path, rel)
            for path, rel in (*declared_assets, *heuristic_candidates)
            if Path(rel).suffix.lower() in IMAGE_EXTENSIONS
        ]
        figures: list[FigureEntry] = []
        for path, rel in sorted(image_candidates, key=lambda item: item[1]):
            data = path.read_bytes()
            dimensions = self._read_image_dimensions(path, rel)
            width, height = dimensions if dimensions is not None else (None, None)
            # ADR-1: standalone images are `heuristic_candidates`, excluded
            # from `sources`, so they are never in the classification queue
            # today -- the lookup falls through to raw `classify(rel)`.
            source_role = self._effective_role(rel, confirmed_roles)
            # ADR-2 mechanical filter: applied AFTER role/dims are computed,
            # BEFORE the entry is appended / before the stable-path copy --
            # a dropped candidate never enters the catalog and is never
            # copied.
            if not should_catalog_figure(source_role, width, height):
                continue
            entry = FigureEntry(
                sha256=sha256_hex(data),
                width_px=width,
                height_px=height,
                origin_relative_path=rel,
                source_role=source_role,
                origin_kind="standalone",
            )
            if assets_dir is not None:
                entry = self._copy_standalone_figure(path, entry, assets_dir)
            figures.append(entry)

        # HIGH silent-failure fix: a standalone `.svg` has no intrinsic pixel
        # size python-docx/Pillow can read, so (unlike the raster loop above)
        # it is normalized + rasterized to a sibling PNG first -- same
        # `<stem>.svg`/`<stem>.png` pair `generate_visuals._render_one`
        # already produces, which `html_render._prefer_sibling_svg` and
        # `docx_assembly` already know how to consume.
        vector_candidates = [
            (path, rel)
            for path, rel in (*declared_assets, *heuristic_candidates)
            if Path(rel).suffix.lower() in VECTOR_EXTENSIONS
        ]
        for path, rel in sorted(vector_candidates, key=lambda item: item[1]):
            source_role = self._effective_role(rel, confirmed_roles)
            if not should_catalog_figure(source_role, None, None):
                continue  # role-dropped (ADR-2) -- never even rasterized
            # Distinct name from the raster loop's non-optional `entry`
            # above: `_ingest_svg_figure` returns `FigureEntry | None`
            # (a vector it could not read is skipped, not catalogued).
            svg_entry = self._ingest_svg_figure(path, rel, source_role, assets_dir)
            if svg_entry is not None:
                figures.append(svg_entry)

        figures.extend(
            self._render_vector_pdf_figures(inbox_dir, entries or [], assets_dir, confirmed_roles)
        )
        catalog_path = sections_dir / "figure-catalog.json"
        self.writer.write_json(catalog_path, build_figure_catalog(figures))

    def _read_image_dimensions(self, path: Path, relative_path: str) -> tuple[int, int] | None:
        # Graceful degradation (HIGH robustness fix): `image_metadata.read_dimensions`
        # already fails open (returns None) for the KNOWN-unparseable cases it
        # explicitly catches (`UnrecognizedImageError`/`InvalidImageStreamError`/
        # `OSError` in `PythonDocxImageMetadataAdapter`) -- but a malformed-yet
        # Pillow-openable image (e.g. a PNG whose declared chunk length disagrees
        # with its actual data) can still make python-docx's minimal PNG chunk
        # walker raise an UNRELATED, uncaught exception (observed:
        # `docx.image.exceptions.UnexpectedEndOfFileError`, which even renders
        # with an EMPTY message). Left unguarded here, that exception used to
        # escape `ingest_inbox` entirely and abort the whole ingest batch --
        # this call site is where every image dimension read funnels through,
        # so it is the single place to guard (same WARN+continue shape as
        # `_render_vector_pdf_figures` below): the image still lands in the
        # figure catalog with null dimensions, same as a known-unparseable
        # file, but the WARN always carries the exception TYPE plus its
        # message so an empty `str(exc)` never renders as a silent no-op.
        if self.image_metadata is None:
            return None
        try:
            return self.image_metadata.read_dimensions(path)
        except Exception as exc:
            print(
                f"WARN: no se pudieron leer las dimensiones de la imagen {relative_path} "
                f"({type(exc).__name__}: {exc}); se cataloga sin dimensiones.",
                file=sys.stderr,
            )
            return None

    def _ingest_svg_figure(
        self, path: Path, relative_path: str, source_role: str, assets_dir: Path | None
    ) -> FigureEntry | None:
        # No `assets_dir` -> nowhere to write the rasterized sibling pair --
        # silent skip, mirrors `_render_vector_pdf_figures`'s own
        # `if assets_dir is None: continue` (not an error condition, some
        # callers legitimately omit `assets_dir`).
        if assets_dir is None:
            return None
        if self.svg_rasterizer is None:
            print(
                f"WARN: {relative_path} es un SVG independiente, pero el rasterizador SVG "
                "(resvg) no está disponible; se omite su incorporación al catálogo de figuras.",
                file=sys.stderr,
            )
            return None

        raw = path.read_bytes()
        sha256 = sha256_hex(raw)
        stem = f"fig-{sha256[:8]}"  # ADR-3 naming (`_copy_standalone_figure`), shared by both siblings
        svg_path = assets_dir / "figures" / f"{stem}.svg"
        png_path = assets_dir / "figures" / f"{stem}.png"
        try:
            normalized = normalize_svg(raw.decode("utf-8", errors="replace"))
            self._write_atomic_text(svg_path, normalized)
            self.svg_rasterizer.rasterize(svg_path, png_path)
        except Exception as exc:
            print(
                f"WARN: no se pudo rasterizar el SVG independiente {relative_path} a PNG "
                f"({exc}); se omite su incorporación al catálogo de figuras.",
                file=sys.stderr,
            )
            svg_path.unlink(missing_ok=True)
            png_path.unlink(missing_ok=True)
            return None

        dimensions = self._read_image_dimensions(png_path, relative_path)
        width, height = dimensions if dimensions is not None else (None, None)
        if not should_catalog_figure(source_role, width, height):
            # ADR-2 invariant: a dropped candidate is never copied/kept on
            # disk -- the pair was already written before dims were known
            # (same as `_render_vector_pdf_figures`'s post-render filter).
            svg_path.unlink(missing_ok=True)
            png_path.unlink(missing_ok=True)
            return None

        return FigureEntry(
            sha256=sha256,
            width_px=width,
            height_px=height,
            origin_relative_path=f"assets/figures/{stem}.png",
            source_role=source_role,
            origin_kind="standalone",
        )

    def _render_vector_pdf_figures(
        self,
        inbox_dir: Path,
        entries: list[dict[str, Any]],
        assets_dir: Path | None,
        confirmed_roles: dict[str, str],
    ) -> list[FigureEntry]:
        # Item F (design.md ADR-F): a PDF that yielded zero extracted raster
        # media (its paired `_media/` dir absent/empty -- opendataloader-pdf
        # extracts none today) may still hold vector diagrams; render its
        # pages so they land in the figure catalog too. Gated on the SAME
        # `_media/` shape `_clean_orphan_media` already checks, so DOCX/ODT
        # sources (pandoc-extracted) and any PDF with real extracted raster
        # never get double-counted.
        figures: list[FigureEntry] = []
        pdf_entries = sorted(
            (entry for entry in entries if entry.get("kind") == "pdf" and entry.get("output")),
            key=lambda entry: entry["relative_path"],
        )
        for entry in pdf_entries:
            output = Path(entry["output"])
            media_dir = output.with_name(f"{output.stem}_media")
            if media_dir.is_dir() and any(media_dir.iterdir()):
                continue  # raster already extracted -- never double-count
            # ADR-1 divergence case: the PDF itself is a real
            # classification-queue source (unlike a standalone image), so
            # its human-CONFIRMED role wins over raw `classify()` -- every
            # page-render this PDF yields inherits it. Role-based drops
            # (ADR-2) short-circuit BEFORE rendering even runs -- a
            # normative/example-role PDF is never rendered, never copied.
            source_role = self._effective_role(entry["relative_path"], confirmed_roles)
            if not should_catalog_figure(source_role, None, None):
                continue
            if self.pdf_render is None:
                print(
                    f"WARN: {entry['relative_path']} podría contener figuras vectoriales, pero "
                    "la herramienta de renderizado (pypdfium2/pillow) no está disponible; se "
                    "omite la extracción de figuras por renderizado de página.",
                    file=sys.stderr,
                )
                continue
            if assets_dir is None:
                continue
            src_pdf = inbox_dir / entry["relative_path"]
            render_dir = assets_dir / "figures"
            try:
                rendered_pages = self.pdf_render.render_pages(src_pdf, render_dir)
            except Exception as exc:
                print(
                    f"WARN: no se pudo renderizar {entry['relative_path']} ({exc}); se omite "
                    "la extracción de figuras por renderizado de página.",
                    file=sys.stderr,
                )
                continue
            for page_path in rendered_pages:
                data = page_path.read_bytes()
                dimensions = (
                    self.image_metadata.read_dimensions(page_path) if self.image_metadata else None
                )
                width, height = dimensions if dimensions is not None else (None, None)
                # ADR-2 filter, re-applied per page (dims are only known
                # after rendering; the role-only pre-check above already
                # skipped rendering entirely for a dropped role).
                if not should_catalog_figure(source_role, width, height):
                    # render_pages already wrote this PNG under assets_dir/figures/
                    # before dims were known -- unlike the standalone branch
                    # (which filters before copying), so a sub-threshold render
                    # must be removed here or it becomes an orphan file no
                    # cleanup pass covers (ADR-2: dropped candidates are never
                    # copied/kept on disk).
                    page_path.unlink(missing_ok=True)
                    continue
                figures.append(
                    FigureEntry(
                        sha256=sha256_hex(data),
                        width_px=width,
                        height_px=height,
                        origin_relative_path=f"assets/figures/{page_path.name}",
                        source_role=source_role,
                        origin_kind="pdf_render",
                    )
                )
        return figures

    def _write_atomic_text(self, path: Path, text: str) -> None:
        # Temp-then-atomic-rename, same convention as `_copy_asset` above --
        # a failing/interrupted write never leaves a partial `.svg` at `path`.
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".asset-tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
