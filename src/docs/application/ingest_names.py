# src/docs/application/ingest_names.py
"""The names the ingest pipeline agrees on.

Artifact filenames and file-extension sets, in one place because
`IngestService`, `SourceClassifier` and `FigureIngestPipeline` all
need them. Splitting the pipeline into collaborators is worthless if
each one re-declares what counts as an image or what the queue file
is called -- that is exactly how a writer-side rename once leaked the
curated index into the evidence pipeline (see `CLAUDE.md`).
"""
from __future__ import annotations

DETECTION_REPORT_NAME = "_detection.json"

SOURCE_MANIFEST_NAME = "_source-manifest.json"

INTAKE_REPORT_NAME = "intake-report.md"

# PR3 verify follow-up (finding a): these are the harness's OWN
# `_`-prefixed bookkeeping files, always written at `inbox_dir` root --
# a rescan finding them gets a distinct `"harness_artifact"` ignored-reason,
# never conflated with a genuine user `_`-prefixed file. `intake-report.md`
# (item G, PR8) joins this set too -- it is NOT `_`-prefixed (deliberately
# discoverable via plain `ls`, design.md ADR-G/AGENTS.md item B), so it must
# be named here explicitly or a rescan would re-ingest its own prior report.
CLASSIFICATION_QUEUE_NAME = "_classification-queue.json"
PLACEMENT_QUEUE_NAME = "_placement-queue.json"

HARNESS_ARTIFACT_NAMES = frozenset(
    {
        DETECTION_REPORT_NAME,
        SOURCE_MANIFEST_NAME,
        CLASSIFICATION_QUEUE_NAME,
        PLACEMENT_QUEUE_NAME,
        INTAKE_REPORT_NAME,
    }
)

# Verbatim-asset heuristic (design.md Decision 6a): an image anywhere
# outside `inbox/assets/`, or a `.docx` whose path signals cover/portada/
# anexo-visual intent, is PROPOSED (never auto-routed) to the placement
# queue. ponytail: substring match on the lowercased relative path, no
# content probing -- same grain as source_role.py's folder lexicon.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"})

# A standalone `.svg` is a distinct routing case from `IMAGE_EXTENSIONS`
# (also used for raster-dimension reads, which python-docx/Pillow cannot do
# for SVG) -- kept as its own set so the intent at each call site stays
# legible: "heuristic candidate" checks BOTH, `build_figure_catalog_for`
# dispatches each set through a different cataloging path (raster copy vs.
# normalize+rasterize).
VECTOR_EXTENSIONS = frozenset({".svg"})

COVER_KEYWORDS = ("portada", "cover")
BACK_KEYWORDS = ("anexo-visual", "anexo_visual")


def guess_asset_kind(relative_posix: str) -> str | None:
    lower = relative_posix.lower()
    if any(keyword in lower for keyword in COVER_KEYWORDS):
        return "cover"
    if any(keyword in lower for keyword in BACK_KEYWORDS):
        return "back"
    return None
