"""Optional Playwright-backed HTML QA.

This module deliberately treats browser checks as evidence, not WCAG
conformance. Playwright is optional; callers retain static HTML findings when
the package or browser executable is unavailable.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.artifacts import RenderProfile, VerificationFinding

BROWSER_TIMEOUT_MS = 10_000


class PlaywrightHtmlBrowserQa:
    def verify(
        self, path: Path, profile: RenderProfile, preview_dir: Path | None
    ) -> list[VerificationFinding]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        findings: list[VerificationFinding] = []
        target_url = path.resolve().as_uri()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    java_script_enabled=False,
                    service_workers="block",
                    accept_downloads=False,
                )
                try:
                    page = context.new_page()
                    try:
                        page.set_default_timeout(BROWSER_TIMEOUT_MS)

                        def restrict_resources(route: Any) -> None:
                            if route.request.url == target_url:
                                route.continue_()
                            else:
                                route.abort()

                        page.route("**/*", restrict_resources)
                        page.goto(target_url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT_MS)
                        if preview_dir is not None:
                            preview_dir.mkdir(parents=True, exist_ok=True)
                        for width, height in profile.browser_viewports:
                            page.set_viewport_size({"width": width, "height": height})
                            metrics = page.evaluate(
                                """() => ({
                              viewportWidth: window.innerWidth,
                              viewportHeight: window.innerHeight,
                              scrollWidth: document.documentElement.scrollWidth,
                              scrollHeight: document.documentElement.scrollHeight,
                              visibleText: document.body?.innerText?.trim().length > 0,
                              visibleH1: [...document.querySelectorAll('h1')].some(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && e.textContent.trim()),
                              missingAlt: [...document.images].filter(e => (e.offsetWidth || e.offsetHeight || e.getClientRects().length) && !e.hasAttribute('alt')).length,
                            })"""
                            )
                            if metrics["scrollWidth"] > metrics["viewportWidth"]:
                                findings.append(VerificationFinding(
                                    code="render.browser.horizontal_overflow",
                                    message=f"Browser viewport {width}×{height} has horizontal overflow.",
                                    severity="warning", dimension="visual", evidence=metrics,
                                ))
                            if metrics["scrollHeight"] > metrics["viewportHeight"] * 8:
                                findings.append(VerificationFinding(
                                    code="render.browser.excessive_height",
                                    message=f"Browser viewport {width}×{height} produces unusually tall content.",
                                    severity="warning", dimension="visual", evidence=metrics,
                                ))
                            if not metrics["visibleText"]:
                                findings.append(VerificationFinding(
                                    code="render.browser.blank",
                                    message=f"Browser viewport {width}×{height} has no visible text.",
                                    severity="warning" if profile.allow_blank_pages else "error", dimension="visual",
                                ))
                            if metrics["missingAlt"]:
                                findings.append(VerificationFinding(
                                    "accessibility.html.alt",
                                    f"Browser found {metrics['missingAlt']} visible image(s) without alt text.",
                                    dimension="accessibility",
                                ))
                            screenshot = None
                            if preview_dir is not None:
                                screenshot = preview_dir / f"{profile.preview_stem or path.stem}-browser-{width}x{height}.png"
                                page.screenshot(path=screenshot, full_page=True, timeout=BROWSER_TIMEOUT_MS)
                            evidence = {"viewport": [width, height], **metrics}
                            if screenshot is not None:
                                import hashlib
                                evidence.update({
                                    "screenshot_path": screenshot.resolve().as_posix(),
                                    "screenshot_sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                                    "screenshot_size_bytes": screenshot.stat().st_size,
                                })
                            findings.append(VerificationFinding(
                                code="render.browser.checked",
                                message=f"Browser viewport {width}×{height} checked; computed layout evidence collected.",
                                severity="info", dimension="visual", evidence=evidence,
                            ))
                    finally:
                        page.close()
                finally:
                    context.close()
            finally:
                browser.close()
        return findings
