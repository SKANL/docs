"""Deterministic visual snapshot comparison for rendered document previews."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import UnidentifiedImageError

from docs.domain.visual_similarity import page_similarity


@dataclass(frozen=True)
class BaselineFinding:
    code: str
    message: str
    page: int
    severity: str = "warning"
    similarity: float | None = None


def compare_preview_baseline(
    actual_dir: Path,
    baseline_dir: Path,
    *,
    minimum_similarity: float = 0.75,
    strict: bool = False,
) -> list[BaselineFinding]:
    """Compare rendered page PNGs without mutating either directory.

    The baseline is opt-in and intentionally reports, rather than rewrites,
    snapshots.  This keeps verification reproducible and makes updating a
    baseline an explicit authored change.
    """
    if not 0.0 <= minimum_similarity <= 1.0:
        raise ValueError("minimum_similarity must be between 0 and 1")
    actual = sorted(actual_dir.glob("*.png")) if actual_dir.is_dir() else []
    baseline = sorted(baseline_dir.glob("*.png")) if baseline_dir.is_dir() else []
    by_name = {path.name: path for path in baseline}
    severity = "error" if strict else "warning"
    findings: list[BaselineFinding] = []

    for page, actual_path in enumerate(actual, start=1):
        baseline_path = by_name.pop(actual_path.name, None)
        if baseline_path is None:
            findings.append(
                BaselineFinding(
                    "visual.baseline_missing",
                    f"No visual baseline exists for {actual_path.name}",
                    page,
                    severity,
                )
            )
            continue
        try:
            similarity = page_similarity(baseline_path, actual_path)
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            findings.append(
                BaselineFinding(
                    "visual.baseline_unreadable",
                    f"Could not compare {actual_path.name}: {exc}",
                    page,
                    severity,
                )
            )
            continue
        if similarity < minimum_similarity:
            findings.append(
                BaselineFinding(
                    "visual.baseline_changed",
                    f"{actual_path.name} similarity {similarity:.4f} is below {minimum_similarity:.4f}",
                    page,
                    severity,
                    similarity,
                )
            )

    for page, extra in enumerate(sorted(by_name.values(), key=lambda path: path.name), start=len(actual) + 1):
        findings.append(
            BaselineFinding(
                "visual.baseline_extra_page",
                f"Baseline contains an unmatched page {extra.name}",
                page,
                severity,
            )
        )
    return findings

