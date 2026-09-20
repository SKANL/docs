import hashlib
import json

import pytest

from docs.infrastructure.verification.html_browser import (
    STANDARD_VIEWPORTS,
    BrowserCaptureResult,
    BrowserVerificationStatus,
    HtmlBrowserVerifier,
)


class RecordingRunner:
    def __init__(self, result=None, *, error=None, write_output=True):
        self.result = result or BrowserCaptureResult(generated=True)
        self.error = error
        self.write_output = write_output
        self.requests = []

    def capture(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.result.generated and self.write_output:
            request.screenshot_path.write_bytes(f"png-{request.viewport.label}".encode())
        return self.result


def test_unavailable_without_runner(tmp_path):
    result = HtmlBrowserVerifier().verify(tmp_path / "page.html", tmp_path / "screenshots")

    assert result.status is BrowserVerificationStatus.UNAVAILABLE
    assert not result.generated
    assert result.screenshots == ()


@pytest.mark.parametrize(
    ("case", "runner", "expected_detail"),
    [
        (
            "missing html",
            RecordingRunner(),
            "HTML input does not exist:",
        ),
        (
            "runner reports failure",
            RecordingRunner(BrowserCaptureResult(False, "browser refused page")),
            "browser refused page",
        ),
        (
            "runner omits output",
            RecordingRunner(BrowserCaptureResult(True), write_output=False),
            "did not create the requested screenshot",
        ),
        (
            "runner raises",
            RecordingRunner(error=TimeoutError("capture timed out")),
            "capture timed out",
        ),
    ],
)
def test_failed_outcomes(case, runner, expected_detail, tmp_path):
    html = tmp_path / "page.html"
    html.write_text("<html lang='en'>content</html>")

    result = HtmlBrowserVerifier(runner).verify(html if case != "missing html" else tmp_path / "missing.html", tmp_path / "out")

    assert result.status is BrowserVerificationStatus.FAILED
    assert expected_detail in result.detail


def test_generated_for_all_standard_viewports_with_deterministic_names_and_metadata(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("<html lang='en'><body>Report</body></html>")
    output = tmp_path / "out"
    runner = RecordingRunner()

    result = HtmlBrowserVerifier(runner, timeout_ms=4321).verify(html, output)

    assert result.status is BrowserVerificationStatus.GENERATED
    assert [request.viewport for request in runner.requests] == list(STANDARD_VIEWPORTS)
    assert [request.screenshot_path.name for request in runner.requests] == [
        "report-browser-320x640.png",
        "report-browser-768x1024.png",
        "report-browser-1280x720.png",
    ]
    assert all(request.timeout_ms == 4321 for request in runner.requests)
    assert result.metadata_path == output / "report-browser-metadata.json"

    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["html_path"] == html.resolve().as_posix()
    assert metadata["version"] == 1
    assert len(metadata["screenshots"]) == len(STANDARD_VIEWPORTS)
    for screenshot in result.screenshots:
        content = screenshot.path.read_bytes()
        assert screenshot.sha256 == hashlib.sha256(content).hexdigest()
        assert screenshot.size_bytes == len(content)
        assert screenshot.path.as_posix() == next(
            item["path"] for item in metadata["screenshots"] if item["sha256"] == screenshot.sha256
        )


def test_empty_viewports_is_failed(tmp_path):
    html = tmp_path / "page.html"
    html.write_text("<html lang='en'></html>")

    result = HtmlBrowserVerifier(RecordingRunner()).verify(html, tmp_path / "out", viewports=())

    assert result.status is BrowserVerificationStatus.FAILED
    assert "At least one browser viewport" in result.detail


@pytest.mark.parametrize("timeout_ms", [0, -1])
def test_timeout_must_be_positive(timeout_ms):
    with pytest.raises(ValueError, match="timeout_ms must be positive"):
        HtmlBrowserVerifier(timeout_ms=timeout_ms)
