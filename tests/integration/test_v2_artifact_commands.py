from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

import docs.cli.commands.v2_app as v2_app_module
from docs.application.provenance_v2 import ProvenanceLedgerV2
from docs.cli.commands.v2_app import _current_input_identities, _manifest_for
from docs.cli.main import app
from docs.domain.artifacts import ArtifactRef, ArtifactState, BuildManifest
from docs.domain.identity import sha256_content


class _IdentityRenderer:
    output_format = "docx"
    def __init__(self, version: str = "one") -> None:
        self.version = version
def test_document_inspect_reports_stable_artifact_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "report.html"
    artifact.write_text("<p>ok</p>", encoding="utf-8")
    result = CliRunner().invoke(app, ["document", "inspect", str(artifact), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["media_type"] == "text/html"
    assert payload["size_bytes"] == artifact.stat().st_size
    assert len(payload["sha256"]) == 64


def _create_verified_v2_artifact(source_dir: Path, name: str, content: bytes) -> Path:
    document_root = source_dir.parent.parent
    artifact = source_dir / name
    artifact.write_bytes(content)
    manifest = BuildManifest(
        document_id=document_root.name,
        source_hash="a" * 64,
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "e" * 64},
        artifacts=(ArtifactRef(str(artifact.resolve()), hashlib.sha256(content).hexdigest(), ArtifactState.READY),),
        verification={"passed": True},
        provenance_run=f"build-{name}",
    )
    artifact.with_suffix(artifact.suffix + ".manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(document_root / "runs" / "v2-provenance.json")
    ledger.record_run(manifest.provenance_run, inputs=(artifact,), outputs=())
    ledger.record_attestation(manifest.provenance_run, manifest.to_dict())
    return artifact


def test_document_diff_and_package_are_atomic_user_facing_operations(tmp_path: Path) -> None:
    source_dir = tmp_path / "artifacts"
    source_dir.mkdir()
    left = source_dir / "a.txt"
    right = source_dir / "b.txt"
    left.write_text("one\n", encoding="utf-8")
    right.write_text("two\n", encoding="utf-8")

    diff = CliRunner().invoke(app, ["document", "diff", str(left), str(right), "--json"])

    assert diff.exit_code == 0, diff.stdout
    assert json.loads(diff.stdout)["same"] is False

    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    _create_verified_v2_artifact(source_dir, "draft.docx", b"docx")
    package_path = tmp_path / "release.zip"
    packaged = CliRunner().invoke(app, ["document", "package", str(source_dir), str(package_path), "--json"])

    assert packaged.exit_code == 0, packaged.stdout
    assert package_path.is_file()


def test_document_package_rejects_unverified_or_mismatched_v2_artifacts_without_replacing_output(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    artifact = _create_verified_v2_artifact(source_dir, "draft.docx", b"original")
    package_path = tmp_path / "release.zip"
    package_path.write_bytes(b"previous package")

    artifact.write_bytes(b"tampered")
    result = CliRunner().invoke(app, ["document", "package", str(source_dir), str(package_path)])

    assert result.exit_code != 0
    assert package_path.read_bytes() == b"previous package"


def test_document_package_uses_validated_artifact_snapshot_when_source_changes_during_write(
    monkeypatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    artifact = _create_verified_v2_artifact(source_dir, "draft.docx", b"original")
    package_path = tmp_path / "release.zip"
    module = __import__("docs.cli.commands.v2_app", fromlist=["_write_deterministic_zip"])
    original_writer = module._write_deterministic_zip

    def mutate_before_write(archive_path, root, files):
        artifact.write_bytes(b"tampered")
        return original_writer(archive_path, root, files)

    monkeypatch.setattr(module, "_write_deterministic_zip", mutate_before_write)
    result = CliRunner().invoke(app, ["document", "package", str(source_dir), str(package_path)])

    assert result.exit_code == 0, result.stdout
    with zipfile.ZipFile(package_path) as archive:
        assert archive.read("draft.docx") == b"original"


def test_document_package_rejects_symlinked_files(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"outside")
    link = source_dir / "draft.docx"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    result = CliRunner().invoke(app, ["document", "package", str(source_dir), str(tmp_path / "release.zip")])

    assert result.exit_code != 0
    assert "symlink" in result.output.lower()


def test_document_package_rejects_file_replaced_by_symlink_after_enumeration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    artifact = _create_verified_v2_artifact(source_dir, "draft.docx", b"inside")
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"inside")
    real_open = v2_app_module.os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if Path(path) == artifact and not replaced:
            replaced = True
            artifact.unlink()
            artifact.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(v2_app_module.os, "open", replace_before_open)

    with pytest.raises(typer.BadParameter, match=r"symlink|regular|unsafe"):
        v2_app_module._package_files(source_dir)


def test_document_package_rejects_missing_manifest_failed_verification_and_attestation(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    artifact = source_dir / "draft.docx"
    artifact.write_bytes(b"docx")

    missing_manifest = CliRunner().invoke(app, ["document", "package", str(source_dir), str(tmp_path / "missing.zip")])

    assert missing_manifest.exit_code != 0

    manifest = BuildManifest(
        document_id="active",
        source_hash=sha256_content({}),
        template_hash="b" * 64,
        config_hash="c" * 64,
        context_hash="d" * 64,
        renderer_versions={"renderer": "e" * 64},
        artifacts=(ArtifactRef(str(artifact.resolve()), hashlib.sha256(artifact.read_bytes()).hexdigest(), ArtifactState.READY),),
        verification={"passed": False},
        provenance_run="build-001",
    )
    artifact.with_suffix(artifact.suffix + ".manifest.json").write_text(manifest.to_json(), encoding="utf-8")

    failed_verification = CliRunner().invoke(app, ["document", "package", str(source_dir), str(tmp_path / "failed.zip")])

    assert failed_verification.exit_code != 0

    manifest = BuildManifest.from_dict({**manifest.to_dict(), "verification": {"passed": True}})
    artifact.with_suffix(artifact.suffix + ".manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    missing_attestation = CliRunner().invoke(app, ["document", "package", str(source_dir), str(tmp_path / "attestation.zip")])

    assert missing_attestation.exit_code != 0


def test_document_package_is_deterministic_for_multiple_verified_v2_artifacts(tmp_path: Path) -> None:
    source_dir = tmp_path / "documents" / "active" / "output" / "v2"
    source_dir.mkdir(parents=True)
    _create_verified_v2_artifact(source_dir, "z-report.pdf", b"pdf")
    _create_verified_v2_artifact(source_dir, "a-report.html", b"html")

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    runner = CliRunner()

    assert runner.invoke(app, ["document", "package", str(source_dir), str(first)]).exit_code == 0
    assert runner.invoke(app, ["document", "package", str(source_dir), str(second)]).exit_code == 0
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(member.date_time == (1980, 1, 1, 0, 0, 0) for member in archive.infolist())


def test_document_publish_requires_verified_matching_attestation_and_release_policy(monkeypatch, tmp_path: Path) -> None:
    doc_root, resolved, config, renderer = _identity_fixture(tmp_path)
    source = doc_root / "output" / "v2" / "draft.docx"
    destination = doc_root / "published" / "report.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"docx")

    blocked = CliRunner().invoke(app, ["document", "publish", str(source), str(destination), "--policy", "draft"])

    assert blocked.exit_code != 0
    assert not destination.exists()

    monkeypatch.setattr(
        "docs.cli.commands.v2_app._resolve_publish_inputs",
        lambda ctx, root, output_format: (resolved, config, renderer),
    )
    manifest = _manifest_for(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=doc_root,
        artifact=source,
        destination=source,
        output_format="docx",
        run_id="build-001",
    )
    source.with_suffix(".docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(doc_root / "runs" / "v2-provenance.json")
    ledger.record_run("build-001", inputs=(source,), outputs=())
    ledger.record_attestation("build-001", manifest.to_dict())

    published = CliRunner().invoke(app, ["document", "publish", str(source), str(destination), "--json"])

    assert published.exit_code == 0, published.stdout
    assert destination.read_bytes() == b"docx"
    published_manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    assert published_manifest.read_bytes() == source.with_suffix(source.suffix + ".manifest.json").read_bytes()


def test_document_publish_rejects_symlinked_source(tmp_path: Path) -> None:
    doc_root = tmp_path / "documents" / "active"
    source_dir = doc_root / "output" / "v2"
    source_dir.mkdir(parents=True)
    outside = tmp_path / "outside.docx"
    outside.write_bytes(b"docx")
    source = source_dir / "draft.docx"
    try:
        source.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    result = CliRunner().invoke(app, ["document", "publish", str(source), str(doc_root / "published" / "report.docx")])

    assert result.exit_code != 0
    assert "symlink" in result.output.lower()


def test_document_publish_rejects_destination_path_escape(monkeypatch, tmp_path: Path) -> None:
    doc_root, resolved, config, renderer = _identity_fixture(tmp_path)
    source = doc_root / "output" / "v2" / "draft.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"docx")
    monkeypatch.setattr("docs.cli.commands.v2_app._resolve_publish_inputs", lambda *args: (resolved, config, renderer))
    manifest = _manifest_for(resolved=resolved, config=config, renderer=renderer, root=doc_root, artifact=source, destination=source, output_format="docx", run_id="escape")
    source.with_suffix(".docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(doc_root / "runs" / "v2-provenance.json")
    ledger.record_run("escape", inputs=(source,), outputs=())
    ledger.record_attestation("escape", manifest.to_dict())

    result = CliRunner().invoke(app, ["document", "publish", str(source), str(tmp_path / "outside.docx")])

    assert result.exit_code != 0
    assert "path" in result.output.lower()


def test_document_publish_uses_verified_source_snapshot_when_source_changes_during_copy(
    monkeypatch, tmp_path: Path
) -> None:
    doc_root, resolved, config, renderer = _identity_fixture(tmp_path)
    source = doc_root / "output" / "v2" / "draft.docx"
    destination = doc_root / "published" / "report.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"docx")
    monkeypatch.setattr(
        "docs.cli.commands.v2_app._resolve_publish_inputs",
        lambda ctx, root, output_format: (resolved, config, renderer),
    )
    manifest = _manifest_for(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=doc_root,
        artifact=source,
        destination=source,
        output_format="docx",
        run_id="build-snapshot",
    )
    source.with_suffix(".docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(doc_root / "runs" / "v2-provenance.json")
    ledger.record_run("build-snapshot", inputs=(source,), outputs=())
    ledger.record_attestation("build-snapshot", manifest.to_dict())

    original_copyfile = __import__("docs.cli.commands.v2_app", fromlist=["shutil"]).shutil.copyfile

    def mutate_before_copy(src, dst):
        Path(src).write_bytes(b"tampered")
        return original_copyfile(src, dst)

    monkeypatch.setattr("docs.cli.commands.v2_app.shutil.copyfile", mutate_before_copy)
    published = CliRunner().invoke(app, ["document", "publish", str(source), str(destination), "--json"])

    assert published.exit_code == 0, published.stdout
    assert destination.read_bytes() == b"docx"


def test_document_publish_rejects_an_arbitrary_file_even_with_release_policy(tmp_path: Path) -> None:
    source = tmp_path / "draft.docx"
    source.write_bytes(b"docx")

    result = CliRunner().invoke(app, ["document", "publish", str(source), str(tmp_path / "final.docx")])

    assert result.exit_code != 0


def _identity_fixture(tmp_path: Path):
    root = tmp_path / "documents" / "active"
    (root / "assets").mkdir(parents=True)
    (root / "template.json").write_text('{"name":"academic"}', encoding="utf-8")
    (root / "config.json").write_text('{"output":{"format":"docx"}}', encoding="utf-8")
    (root / "context.json").write_text('{"author":"Ada"}', encoding="utf-8")
    (root / "assets" / "logo.bin").write_bytes(b"logo-one")
    resolved = SimpleNamespace(
        doc_id="active",
        template=SimpleNamespace(name="academic"),
        context={"author": "Ada"},
    )
    config = {"output": {"format": "docx"}}
    renderer = _IdentityRenderer()
    return root, resolved, config, renderer


@pytest.mark.parametrize("component", ("template", "config", "context", "asset", "renderer"))
def test_current_input_identities_change_for_each_publish_input_drift(tmp_path: Path, component: str) -> None:
    root, resolved, config, renderer = _identity_fixture(tmp_path)
    before = _current_input_identities(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=root,
        output_format="docx",
    )

    if component == "template":
        (root / "template.json").write_text('{"name":"technical"}', encoding="utf-8")
        resolved.template.name = "technical"
    elif component == "config":
        config["output"]["format"] = "html"
    elif component == "context":
        resolved.context["author"] = "Grace"
    elif component == "asset":
        (root / "assets" / "logo.bin").write_bytes(b"logo-two")
    else:
        renderer.version = "two"

    after = _current_input_identities(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=root,
        output_format="docx",
    )

    key = {
        "template": "template_hash",
        "config": "config_hash",
        "context": "context_hash",
        "asset": "asset_hashes",
        "renderer": "renderer_versions",
    }[component]
    assert before[key] != after[key]


@pytest.mark.parametrize("component", ("template", "config", "context", "asset", "renderer"))
def test_document_publish_rejects_every_input_identity_drift(monkeypatch, tmp_path: Path, component: str) -> None:
    root, resolved, config, renderer = _identity_fixture(tmp_path)
    source = root / "output" / "v2" / "draft.docx"
    destination = root / "published" / "report.docx"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"docx")

    monkeypatch.setattr(
        "docs.cli.commands.v2_app._resolve_publish_inputs",
        lambda ctx, document_root, output_format: (resolved, config, renderer),
    )
    manifest = _manifest_for(
        resolved=resolved,
        config=config,
        renderer=renderer,
        root=root,
        artifact=source,
        destination=source,
        output_format="docx",
        run_id="build-drift",
    )
    source.with_suffix(".docx.manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    ledger = ProvenanceLedgerV2(root / "runs" / "v2-provenance.json")
    ledger.record_run("build-drift", inputs=(source,), outputs=())
    ledger.record_attestation("build-drift", manifest.to_dict())

    if component == "template":
        resolved.template.name = "technical"
    elif component == "config":
        config["build_revision"] = 2
    elif component == "context":
        resolved.context["author"] = "Grace"
    elif component == "asset":
        (root / "assets" / "logo.bin").write_bytes(b"logo-two")
    else:
        renderer.version = "two"

    result = CliRunner().invoke(app, ["document", "publish", str(source), str(destination)])

    assert result.exit_code != 0
    assert component in result.output.lower()
    assert not destination.exists()
