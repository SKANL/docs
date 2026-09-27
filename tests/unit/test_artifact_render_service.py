from __future__ import annotations

from pathlib import Path

from docs.application.artifact_render_service import ArtifactRenderService


class Renderer:
    def __init__(self, payload: bytes = b"artifact", missing: bool = False) -> None:
        self.payload = payload
        self.missing = missing
        self.calls: list[tuple[str, dict, Path]] = []

    def build(self, document_id: str, config: dict, *, output: Path) -> Path | None:
        self.calls.append((document_id, config, output))
        if self.missing:
            return None
        output.write_bytes(self.payload)
        return output


def _service() -> ArtifactRenderService:
    return ArtifactRenderService(
        scratch_factory=lambda prefix, parent: parent / f"{prefix}scratch",
        validator=lambda path: (path.is_file(), "valid"),
    )


def test_build_format_selects_renderer_and_overrides_config_without_mutating_it(tmp_path: Path) -> None:
    renderer = Renderer()
    config = {"output": {"format": "docx", "quality": "high"}}

    outcome = _service().build_format(
        renderers={"html": renderer},
        format_name="html",
        document_id="guide",
        config=config,
        scratch_parent=tmp_path,
    )

    assert outcome.succeeded
    assert outcome.artifact == tmp_path / ".x20-html-scratch" / "guide.html"
    assert renderer.calls[0][1]["output"] == {"format": "html", "quality": "high"}
    assert config["output"]["format"] == "docx"


def test_build_format_reports_missing_renderer_and_missing_output(tmp_path: Path) -> None:
    service = _service()
    missing_renderer = service.build_format(
        renderers={}, format_name="pdf", document_id="guide", config={}, scratch_parent=tmp_path
    )
    omitted_output = service.build_format(
        renderers={"pdf": Renderer(missing=True)},
        format_name="pdf",
        document_id="guide",
        config={},
        scratch_parent=tmp_path,
    )

    assert not missing_renderer.succeeded
    assert missing_renderer.detail == "renderer does not provide pdf output"
    assert omitted_output.succeeded
    assert omitted_output.detail == "omitted: pdf renderer produced no artifact"


def test_render_and_retain_preserves_build_failure_and_retains_success(tmp_path: Path) -> None:
    service = _service()
    runs = tmp_path / "runs"
    retained = runs / "v2-artifacts"

    failure = service.render_and_retain(
        renderer=Renderer(missing=True), format_name="docx", document_id="guide", config={},
        runs_dir=runs, retained_dir=retained, build_token="token",
        directory_guard=lambda _path: __import__("contextlib").nullcontext(),
        directory_identity=lambda _path: "same",
        assert_directory_identity=lambda *_args, **_kwargs: None,
    )
    success = service.render_and_retain(
        renderer=Renderer(), format_name="docx", document_id="guide", config={},
        runs_dir=runs, retained_dir=retained, build_token="token",
        directory_guard=lambda _path: __import__("contextlib").nullcontext(),
        directory_identity=lambda _path: "same",
        assert_directory_identity=lambda *_args, **_kwargs: None,
    )

    assert not failure.succeeded
    assert failure.detail == "docx renderer produced no artifact"
    assert success.succeeded
    assert success.artifact == retained / "token.guide.docx"
    assert success.artifact.read_bytes() == b"artifact"
