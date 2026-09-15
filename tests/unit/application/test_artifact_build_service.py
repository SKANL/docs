from __future__ import annotations

from pathlib import Path

import pytest

from docs.application.artifact_build_service import (
    ArtifactBuildError,
    ArtifactBuildService,
)


def test_builds_only_in_injected_scratch_and_returns_a_typed_result(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    calls: list[Path] = []

    def build(document_id: str, config: dict[str, object], output: Path) -> Path:
        assert document_id == "active"
        assert config == {"output": {"format": "html"}}
        output.write_bytes(b"<html><body>Rendered</body></html>")
        return output

    def validate(artifact: Path) -> tuple[bool, str]:
        calls.append(artifact)
        return True, "reopened"

    service = ArtifactBuildService(
        build=build,
        scratch_factory=lambda _prefix, _parent: scratch,
        validator=validate,
    )

    result = service.build(
        document_id="active",
        config={"output": {"format": "html"}},
        output_format="html",
        scratch_parent=tmp_path,
    )

    assert result.artifact == scratch / "active.html"
    assert result.scratch_dir == scratch
    assert result.validation_detail == "reopened"
    assert calls == [result.artifact]
    assert not (tmp_path / "output").exists()


def test_creates_missing_scratch_parent_before_invoking_factory(tmp_path: Path) -> None:
    scratch_parent = tmp_path / "runs"
    scratch = scratch_parent / "scratch"
    factory_parents: list[Path] = []

    def scratch_factory(_prefix: str, parent: Path) -> Path:
        assert parent.is_dir()
        factory_parents.append(parent)
        return scratch

    def build(_document_id: str, _config: dict[str, object], output: Path) -> Path:
        output.write_bytes(b"rendered")
        return output

    service = ArtifactBuildService(
        build=build,
        scratch_factory=scratch_factory,
        validator=lambda _artifact: (True, "valid"),
    )

    service.build(
        document_id="active",
        config={},
        output_format="html",
        scratch_parent=scratch_parent,
    )

    assert scratch_parent.is_dir()
    assert factory_parents == [scratch_parent.resolve()]


@pytest.mark.parametrize(
    "build",
    (
        lambda _document_id, _config, _output: None,
        lambda _document_id, _config, output: output,
        lambda _document_id, _config, output: output.parent.parent / "outside.html",
    ),
)
def test_rejects_missing_empty_or_outside_scratch_outputs(tmp_path: Path, build) -> None:
    scratch = tmp_path / "scratch"

    service = ArtifactBuildService(
        build=build,
        scratch_factory=lambda _prefix, _parent: scratch,
        validator=lambda _artifact: (True, "valid"),
    )

    with pytest.raises(ArtifactBuildError):
        service.build(
            document_id="active",
            config={},
            output_format="html",
            scratch_parent=tmp_path,
        )


def test_rejects_an_unreadable_output_from_the_injected_validator(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"

    def build(_document_id: str, _config: dict[str, object], output: Path) -> Path:
        output.write_bytes(b"rendered")
        return output

    service = ArtifactBuildService(
        build=build,
        scratch_factory=lambda _prefix, _parent: scratch,
        validator=lambda _artifact: (False, "cannot reopen"),
    )

    with pytest.raises(ArtifactBuildError, match="cannot reopen"):
        service.build(
            document_id="active",
            config={},
            output_format="html",
            scratch_parent=tmp_path,
        )


def test_rejects_a_document_id_that_resolves_outside_scratch(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"

    def build(_document_id: str, _config: dict[str, object], output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"rendered")
        return output

    service = ArtifactBuildService(
        build=build,
        scratch_factory=lambda _prefix, _parent: scratch,
        validator=lambda _artifact: (True, "valid"),
    )

    with pytest.raises(ArtifactBuildError, match="outside the v2 render scratch directory"):
        service.build(
            document_id="../escaped",
            config={},
            output_format="html",
            scratch_parent=tmp_path,
        )


def test_rejects_lexically_escaping_scratch_before_creating_it(tmp_path: Path) -> None:
    outside_scratch = tmp_path.parent / f"{tmp_path.name}-outside-scratch"
    scratch_path_with_parent_escape = tmp_path / ".." / outside_scratch.name

    service = ArtifactBuildService(
        build=lambda _document_id, _config, _output: pytest.fail("build must not run"),
        scratch_factory=lambda _prefix, _parent: scratch_path_with_parent_escape,
        validator=lambda _artifact: (True, "valid"),
    )

    with pytest.raises(ArtifactBuildError, match="outside the configured scratch parent"):
        service.build(
            document_id="active",
            config={},
            output_format="html",
            scratch_parent=tmp_path,
        )

    assert not outside_scratch.exists()


