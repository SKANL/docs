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
                            local_root = path.resolve().parent.as_uri().rstrip("/") + "/"
                            if route.request.url == target_url or route.request.url.startswith(local_root):
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
                              missingFocusIndicators: (() => {
                                const focusable = [...document.querySelectorAll('a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])')]
                                  .filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                                return focusable.filter(e => {
                                  e.focus({preventScroll: true});
                                  const style = getComputedStyle(e);
                                  return (style.outlineStyle === 'none' || parseFloat(style.outlineWidth) === 0) && style.boxShadow === 'none';
                                }).length;
                              })(),
                              missingLandmarks: ['main', 'banner'].filter(role => {
                                const selector = role === 'main' ? 'main,[role="main"]' : 'header,[role="banner"]';
                                return ![...document.querySelectorAll(selector)].some(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                              }),
                              inaccessibleContent: (() => {
                                const visible = e => e.offsetWidth || e.offsetHeight || e.getClientRects().length;
                                const name = e => (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.getAttribute('title') || e.innerText || e.value || '').trim();
                                const interactive = [...document.querySelectorAll('a[href],button,input,select,textarea,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[tabindex]:not([tabindex="-1"])')];
                                return interactive.filter(e => visible(e) && (e.getAttribute('aria-hidden') === 'true' || !name(e))).length;
                              })(),
                              brokenImages: [...document.images].filter(e => (e.offsetWidth || e.offsetHeight || e.getClientRects().length) && (!e.complete || e.naturalWidth === 0)).length,
                              unloadedFonts: document.fonts ? [...document.fonts].filter(font => font.status !== 'loaded').length : 0,
                              clippedElements: (() => {
                                const visible = e => e.offsetWidth || e.offsetHeight || e.getClientRects().length;
                                const clipped = [];
                                for (const e of [...document.querySelectorAll('body *')]) {
                                  if (!visible(e)) continue;
                                  const child = e.getBoundingClientRect();
                                  for (const parent of e.parentElement ? [e.parentElement] : []) {
                                    const style = getComputedStyle(parent);
                                    const box = parent.getBoundingClientRect();
                                    if ((style.overflow === 'hidden' || style.overflow === 'clip' || style.overflowX === 'hidden' || style.overflowY === 'hidden') &&
                                      (child.left < box.left || child.right > box.right || child.top < box.top || child.bottom > box.bottom)) clipped.push(e);
                                  }
                                }
                                return clipped.length;
                              })(),
                              overlappingElements: (() => {
                                const boxes = [...document.querySelectorAll('body *')].filter(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length).map(e => ({element: e, box: e.getBoundingClientRect()}));
                                let overlaps = 0;
                                for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
                                  const a = boxes[i].box, b = boxes[j].box;
                                  if (boxes[i].element.contains(boxes[j].element) || boxes[j].element.contains(boxes[i].element)) continue;
                                  if (Math.min(a.right, b.right) > Math.max(a.left, b.left) && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top)) overlaps++;
                                }
                                return overlaps;
                              })(),
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
                            browser_metrics = (
                                ("accessibility.html.focus", metrics.get("missingFocusIndicators", 0),
                                 "Browser found visible focusable element(s) without a visible focus indicator.", "accessibility"),
                                ("accessibility.html.landmarks", len(metrics.get("missingLandmarks", [])),
                                 "Browser found required landmark(s) missing or not visible.", "accessibility"),
                                ("accessibility.html.inaccessible", metrics.get("inaccessibleContent", 0),
                                 "Browser found visible interactive content without an accessible name or with aria-hidden focusability.", "accessibility"),
                                ("render.browser.broken_image", metrics.get("brokenImages", 0),
                                 "Browser found visible image(s) that did not load.", "visual"),
                                ("render.browser.unloaded_font", metrics.get("unloadedFonts", 0),
                                 "Browser found font face(s) that did not finish loading.", "visual"),
                                ("render.browser.clipping", metrics.get("clippedElements", 0),
                                 "Browser found visible content clipped by an ancestor.", "visual"),
                                ("render.browser.overlap", metrics.get("overlappingElements", 0),
                                 "Browser found intersecting visible layout boxes; inspect for unintended overlap.", "visual"),
                            )
                            for code, count, message, dimension in browser_metrics:
                                if count:
                                    findings.append(VerificationFinding(
                                        code, f"{message} Count: {count}.", "warning",
                                        dimension=dimension, evidence={"count": count, "viewport": [width, height]},
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
