"""Optional Playwright-backed implementation of the HTML browser boundary.

The Playwright dependency is deliberately imported only when a capture is
requested, so the core document harness stays usable without it installed.
"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from docs.infrastructure.verification.html_browser import BrowserCaptureRequest, BrowserCaptureResult


class PlaywrightUnavailableError(RuntimeError):
    """Raised when optional real-browser verification cannot import Playwright."""

    message = "Playwright is unavailable. Install the 'playwright' package and browser binaries to enable real-browser HTML verification."

    def __init__(self) -> None:
        super().__init__(self.message)


class PlaywrightBrowserRunner:
    """Render local HTML with Playwright while keeping browser diagnostics bounded."""

    _MAX_CLIPPED_ELEMENTS = 5

    def __init__(
        self,
        *,
        browser: str = "chromium",
        executable_path: Path | str | None = None,
        channel: str | None = None,
    ) -> None:
        self._browser = browser
        self._executable_path = str(executable_path) if executable_path is not None else None
        self._channel = channel

    def capture(self, request: BrowserCaptureRequest) -> BrowserCaptureResult:
        """Render a local file URI, save its screenshot, and report layout diagnostics."""
        sync_playwright = self._load_sync_playwright()
        request.screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            browser_type = getattr(playwright, self._browser, None)
            if browser_type is None:
                raise ValueError(f"Unsupported Playwright browser: {self._browser}")

            browser = browser_type.launch(**self._launch_options())
            try:
                page = browser.new_page(
                    viewport={"width": request.viewport.width, "height": request.viewport.height}
                )
                page.set_default_timeout(request.timeout_ms)
                page.goto(request.html_path.resolve().as_uri(), wait_until="load", timeout=request.timeout_ms)
                page.evaluate(self._WAIT_FOR_ASSETS_SCRIPT)
                diagnostics = page.evaluate(self._LAYOUT_DIAGNOSTICS_SCRIPT)
                page.screenshot(path=str(request.screenshot_path), full_page=True)
            finally:
                browser.close()

        return BrowserCaptureResult(generated=True, detail=self._format_diagnostics(diagnostics))

    @staticmethod
    def _load_sync_playwright() -> Any:
        try:
            sync_api = import_module("playwright.sync_api")
        except ModuleNotFoundError as exc:
            raise PlaywrightUnavailableError() from exc
        return sync_api.sync_playwright

    def _launch_options(self) -> dict[str, str | bool]:
        options: dict[str, str | bool] = {"headless": True}
        if self._executable_path is not None:
            options["executable_path"] = self._executable_path
        if self._channel is not None:
            options["channel"] = self._channel
        return options

    @classmethod
    def _format_diagnostics(cls, diagnostics: dict[str, object]) -> str:
        overflow = bool(diagnostics.get("horizontalOverflow", False))
        clipped = diagnostics.get("clippedElements", [])
        if not isinstance(clipped, list):
            clipped = []
        labels = [str(label) for label in clipped[: cls._MAX_CLIPPED_ELEMENTS]]
        parts = [f"horizontal_overflow={str(overflow).lower()}", f"clipped_elements={len(clipped)}"]
        if labels:
            parts.append(f"clipped={', '.join(labels)}")
        return "; ".join(parts)

    _WAIT_FOR_ASSETS_SCRIPT = """
        async () => {
            if (document.fonts) {
                await document.fonts.ready;
            }
            await Promise.all([...document.images].map((image) => {
                if (image.complete) return undefined;
                return new Promise((resolve) => {
                    image.addEventListener("load", resolve, { once: true });
                    image.addEventListener("error", resolve, { once: true });
                });
            }));
        }
    """

    _LAYOUT_DIAGNOSTICS_SCRIPT = """
        () => {
            const clippedElements = [];
            for (const element of document.body.querySelectorAll("*")) {
                const rect = element.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                if (rect.left >= 0 && rect.right <= window.innerWidth) continue;
                const id = element.id ? `#${element.id}` : "";
                const className = typeof element.className === "string" && element.className
                    ? `.${element.className.trim().split(/\\s+/)[0]}`
                    : "";
                clippedElements.push(`${element.tagName.toLowerCase()}${id || className}`);
                if (clippedElements.length >= 5) break;
            }
            return {
                horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
                clippedElements,
            };
        }
    """
