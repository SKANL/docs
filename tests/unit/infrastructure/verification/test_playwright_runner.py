from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from docs.infrastructure.verification.html_browser import (
    BrowserCaptureRequest,
    BrowserViewport,
)
from docs.infrastructure.verification.playwright_runner import (
    PlaywrightBrowserRunner,
    PlaywrightUnavailableError,
)


def _request(tmp_path: Path) -> BrowserCaptureRequest:
    html = tmp_path / "report page.html"
    html.write_text("<html><body>Report</body></html>", encoding="utf-8")
    return BrowserCaptureRequest(html, BrowserViewport(768, 1024), tmp_path / "shots" / "page.png", 4321)


def _playwright_fixture(diagnostics=None):
    page = Mock()
    page.evaluate.side_effect = [None, diagnostics or {"horizontalOverflow": False, "clippedElements": []}]
    browser = Mock()
    browser.new_page.return_value = page
    browser_type = Mock()
    browser_type.launch.return_value = browser
    playwright = SimpleNamespace(chromium=browser_type)
    manager = Mock()
    manager.__enter__ = Mock(return_value=playwright)
    manager.__exit__ = Mock(return_value=None)
    sync_playwright = Mock(return_value=manager)
    return sync_playwright, browser_type, browser, page


def test_missing_playwright_dependency_has_stable_error(monkeypatch):
    def missing(_name):
        raise ModuleNotFoundError("No module named 'playwright'")

    monkeypatch.setattr("docs.infrastructure.verification.playwright_runner.import_module", missing)

    with pytest.raises(PlaywrightUnavailableError) as error:
        PlaywrightBrowserRunner().capture(
            BrowserCaptureRequest(Path("page.html"), BrowserViewport(320, 640), Path("page.png"), 1000)
        )

    assert str(error.value) == PlaywrightUnavailableError.message


def test_capture_launches_with_options_viewport_file_url_and_timeout(monkeypatch, tmp_path):
    sync_playwright, browser_type, browser, page = _playwright_fixture()
    monkeypatch.setattr(PlaywrightBrowserRunner, "_load_sync_playwright", staticmethod(lambda: sync_playwright))
    request = _request(tmp_path)
    runner = PlaywrightBrowserRunner(browser="chromium", executable_path=tmp_path / "browser", channel="chrome")

    result = runner.capture(request)

    assert result.generated
    browser_type.launch.assert_called_once_with(
        headless=True, executable_path=str(tmp_path / "browser"), channel="chrome"
    )
    browser.new_page.assert_called_once_with(viewport={"width": 768, "height": 1024})
    page.set_default_timeout.assert_called_once_with(4321)
    page.goto.assert_called_once_with(request.html_path.resolve().as_uri(), wait_until="load", timeout=4321)
    page.screenshot.assert_called_once_with(path=str(request.screenshot_path), full_page=True)
    browser.close.assert_called_once_with()


def test_capture_waits_for_assets_and_reports_diagnostics(monkeypatch, tmp_path):
    diagnostics = {"horizontalOverflow": True, "clippedElements": ["div#one", ".card"]}
    sync_playwright, _, _, page = _playwright_fixture(diagnostics)
    monkeypatch.setattr(PlaywrightBrowserRunner, "_load_sync_playwright", staticmethod(lambda: sync_playwright))

    result = PlaywrightBrowserRunner().capture(_request(tmp_path))

    assert page.evaluate.call_args_list[0].args[0] == PlaywrightBrowserRunner._WAIT_FOR_ASSETS_SCRIPT
    assert page.evaluate.call_args_list[1].args[0] == PlaywrightBrowserRunner._LAYOUT_DIAGNOSTICS_SCRIPT
    assert result.detail == "horizontal_overflow=true; clipped_elements=2; clipped=div#one, .card"


def test_diagnostics_clip_labels_to_five_and_handle_invalid_labels():
    diagnostics = {"horizontalOverflow": False, "clippedElements": list("abcdef")}

    assert PlaywrightBrowserRunner._format_diagnostics(diagnostics) == (
        "horizontal_overflow=false; clipped_elements=6; clipped=a, b, c, d, e"
    )
    assert PlaywrightBrowserRunner._format_diagnostics({"clippedElements": "not-a-list"}) == (
        "horizontal_overflow=false; clipped_elements=0"
    )


def test_unsupported_browser_is_rejected_before_launch(monkeypatch, tmp_path):
    sync_playwright, _, browser, page = _playwright_fixture()
    monkeypatch.setattr(PlaywrightBrowserRunner, "_load_sync_playwright", staticmethod(lambda: sync_playwright))

    with pytest.raises(ValueError, match="Unsupported Playwright browser: webkit"):
        PlaywrightBrowserRunner(browser="webkit").capture(_request(tmp_path))

    browser.close.assert_not_called()
    page.screenshot.assert_not_called()
