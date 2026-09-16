from __future__ import annotations

import sys
import types

from docs.domain.artifacts import RenderProfile
from docs.infrastructure.verification.html_browser_qa import PlaywrightHtmlBrowserQa


def test_browser_qa_disables_scripts_blocks_external_resources_and_bounds_navigation(tmp_path, monkeypatch):
    html = tmp_path / "report.html"
    html.write_text("<html><body><h1>Title</h1></body></html>")
    state = {}

    class Route:
        def __init__(self, url):
            self.request = types.SimpleNamespace(url=url)
            self.action = None

        def continue_(self):
            self.action = "continue"

        def abort(self):
            self.action = "abort"

    class Page:
        def set_default_timeout(self, timeout):
            state["default_timeout"] = timeout

        def route(self, pattern, handler):
            state["route_pattern"] = pattern
            state["route_handler"] = handler

        def goto(self, url, **kwargs):
            state["goto"] = (url, kwargs)

        def set_viewport_size(self, _size):
            pass

        def evaluate(self, _script):
            return {"viewportWidth": 800, "viewportHeight": 600, "scrollWidth": 800,
                    "scrollHeight": 600, "visibleText": True, "visibleH1": True, "missingAlt": 0}

        def screenshot(self, path, **_kwargs):
            path.write_bytes(b"screenshot")

        def close(self):
            pass

    class Context:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class Browser:
        def new_context(self, **kwargs):
            state["context"] = kwargs
            return Context()

        def close(self):
            pass

    class Playwright:
        chromium = types.SimpleNamespace(launch=lambda **kwargs: Browser())

    class SyncPlaywright:
        def __enter__(self):
            return Playwright()

        def __exit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    api = types.ModuleType("playwright.sync_api")
    def sync_playwright():
        return SyncPlaywright()

    api.sync_playwright = sync_playwright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)

    findings = PlaywrightHtmlBrowserQa().verify(
        html, RenderProfile(format="html", browser_viewports=((800, 600),)), tmp_path / "previews"
    )

    assert state["context"] == {"java_script_enabled": False, "service_workers": "block", "accept_downloads": False}
    assert state["goto"][1] == {"wait_until": "domcontentloaded", "timeout": 10_000}
    assert state["default_timeout"] == 10_000
    external = Route("https://example.test/track.js")
    state["route_handler"](external)
    assert external.action == "abort"
    local = Route((tmp_path / "style.css").resolve().as_uri())
    state["route_handler"](local)
    assert local.action == "continue"
    assert any(f.code == "render.browser.checked" for f in findings)


def test_browser_qa_reports_browser_only_accessibility_and_layout_failures(tmp_path, monkeypatch):
    html = tmp_path / "report.html"
    html.write_text("<html><body><h1>Title</h1></body></html>")

    class Page:
        def set_default_timeout(self, _timeout):
            pass

        def route(self, _pattern, _handler):
            pass

        def goto(self, _url, **_kwargs):
            pass

        def set_viewport_size(self, _size):
            pass

        def evaluate(self, _script):
            return {
                "viewportWidth": 800, "viewportHeight": 600, "scrollWidth": 800,
                "scrollHeight": 600, "visibleText": True, "visibleH1": True,
                "missingAlt": 0, "missingFocusIndicators": 1,
                "missingLandmarks": ["main"], "inaccessibleContent": 1,
                "brokenImages": 1, "unloadedFonts": 1, "clippedElements": 1,
                "overlappingElements": 1,
            }

        def close(self):
            pass

    class Context:
        def new_page(self):
            return Page()

        def close(self):
            pass

    class Browser:
        def new_context(self, **_kwargs):
            return Context()

        def close(self):
            pass

    class SyncPlaywright:
        chromium = types.SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    api = types.ModuleType("playwright.sync_api")
    def sync_playwright():
        return SyncPlaywright()

    api.sync_playwright = sync_playwright
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)

    findings = PlaywrightHtmlBrowserQa().verify(
        html, RenderProfile(format="html", browser_viewports=((800, 600),)), None
    )

    assert {
        "accessibility.html.focus",
        "accessibility.html.landmarks",
        "accessibility.html.inaccessible",
        "render.browser.broken_image",
        "render.browser.unloaded_font",
        "render.browser.clipping",
        "render.browser.overlap",
    } <= {finding.code for finding in findings}
