"""Optional real-browser HTML visual-verification boundary.

The module has no browser dependency.  A caller may inject a runner backed by
Playwright, a subprocess, or another browser integration; without one it
returns explicit ``unavailable`` evidence rather than claiming visual QA ran.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class BrowserViewport:
    """A stable viewport used for responsive visual evidence."""

    width: int
    height: int

    @property
    def label(self) -> str:
        return f"{self.width}x{self.height}"


STANDARD_VIEWPORTS: tuple[BrowserViewport, ...] = (
    BrowserViewport(320, 640),
    BrowserViewport(768, 1024),
    BrowserViewport(1280, 720),
)
"""The required mobile, tablet, and desktop visual-verification viewports."""


class BrowserVerificationStatus(StrEnum):
    """Outcome of an optional real-browser verification attempt."""

    UNAVAILABLE = "unavailable"
    FAILED = "failed"
    GENERATED = "generated"


@dataclass(frozen=True, slots=True)
class BrowserCaptureRequest:
    """One deterministic screenshot request passed across the runner boundary."""

    html_path: Path
    viewport: BrowserViewport
    screenshot_path: Path
    timeout_ms: int


@dataclass(frozen=True, slots=True)
class BrowserCaptureResult:
    """The runner's outcome for one requested screenshot."""

    generated: bool
    detail: str = ""


@runtime_checkable
class BrowserRunner(Protocol):
    """Injectable browser boundary; implementations may use Playwright or subprocesses."""

    def capture(self, request: BrowserCaptureRequest) -> BrowserCaptureResult:
        """Render ``request.html_path`` and write a PNG at ``request.screenshot_path``."""


@dataclass(frozen=True, slots=True)
class BrowserScreenshot:
    """Deterministic metadata for a runner-generated screenshot."""

    viewport: BrowserViewport
    path: Path
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path.as_posix(),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "viewport": {"height": self.viewport.height, "width": self.viewport.width},
        }


@dataclass(frozen=True, slots=True)
class BrowserVerificationResult:
    """Evidence that visual verification was generated, unavailable, or failed."""

    status: BrowserVerificationStatus
    detail: str
    screenshots: tuple[BrowserScreenshot, ...] = ()
    metadata_path: Path | None = None

    @property
    def generated(self) -> bool:
        return self.status is BrowserVerificationStatus.GENERATED


class HtmlBrowserVerifier:
    """Capture responsive HTML screenshots through an optional injected runner."""

    def __init__(self, runner: BrowserRunner | None = None, *, timeout_ms: int = 10_000) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._runner = runner
        self._timeout_ms = timeout_ms

    def verify(
        self,
        html_path: Path,
        output_dir: Path,
        *,
        viewports: tuple[BrowserViewport, ...] = STANDARD_VIEWPORTS,
    ) -> BrowserVerificationResult:
        """Generate one PNG per viewport, or report why real-browser QA did not run."""
        resolved_html = html_path.resolve()
        if self._runner is None:
            return BrowserVerificationResult(
                BrowserVerificationStatus.UNAVAILABLE,
                "Real-browser HTML verification is unavailable because no browser runner was configured.",
            )
        if not resolved_html.is_file():
            return BrowserVerificationResult(
                BrowserVerificationStatus.FAILED,
                f"HTML input does not exist: {resolved_html.as_posix()}",
            )
        if not viewports:
            return BrowserVerificationResult(
                BrowserVerificationStatus.FAILED,
                "At least one browser viewport is required for visual verification.",
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        screenshots: list[BrowserScreenshot] = []
        for viewport in viewports:
            screenshot_path = output_dir / self.screenshot_name(resolved_html, viewport)
            try:
                captured = self._runner.capture(
                    BrowserCaptureRequest(resolved_html, viewport, screenshot_path, self._timeout_ms)
                )
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                return BrowserVerificationResult(
                    BrowserVerificationStatus.FAILED,
                    f"Browser capture failed at {viewport.label}: {exc}",
                    tuple(screenshots),
                )
            if not captured.generated or not screenshot_path.is_file():
                detail = captured.detail or "The runner did not create the requested screenshot."
                return BrowserVerificationResult(
                    BrowserVerificationStatus.FAILED,
                    f"Browser capture failed at {viewport.label}: {detail}",
                    tuple(screenshots),
                )
            screenshots.append(self._screenshot_metadata(screenshot_path, viewport))

        metadata_path = output_dir / f"{resolved_html.stem}-browser-metadata.json"
        self._write_metadata(metadata_path, resolved_html, screenshots)
        return BrowserVerificationResult(
            BrowserVerificationStatus.GENERATED,
            "Real-browser HTML screenshots and deterministic metadata were generated.",
            tuple(screenshots),
            metadata_path,
        )

    @staticmethod
    def screenshot_name(html_path: Path, viewport: BrowserViewport) -> str:
        """Return the stable filename shared by every runner implementation."""
        return f"{html_path.stem}-browser-{viewport.label}.png"

    @staticmethod
    def _screenshot_metadata(path: Path, viewport: BrowserViewport) -> BrowserScreenshot:
        with path.open("rb") as screenshot:
            digest = hashlib.file_digest(screenshot, "sha256").hexdigest()
        return BrowserScreenshot(viewport, path.resolve(), digest, path.stat().st_size)

    @staticmethod
    def _write_metadata(
        metadata_path: Path, html_path: Path, screenshots: list[BrowserScreenshot]
    ) -> None:
        payload = {
            "html_path": html_path.as_posix(),
            "screenshots": [screenshot.to_dict() for screenshot in screenshots],
            "version": 1,
        }
        metadata_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
