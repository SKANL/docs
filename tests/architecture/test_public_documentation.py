from __future__ import annotations

import json
import re
from pathlib import Path

from docs.application.pipeline_service import FULL_STAGE_IDS
from docs.cli.commands.document_app import _BATCH_OUTPUT_PATHS, _record_batch_outputs, _write_batch_journal


REPOSITORY_ROOT = Path(__file__).parents[2]
CURRENT_PUBLIC_DOCS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "AGENTS.md",
    REPOSITORY_ROOT / "docs" / "architecture.md",
    REPOSITORY_ROOT / "docs" / "pipeline.md",
    REPOSITORY_ROOT / "docs" / "runtime-guide.md",
)


def _read_current_public_docs() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in CURRENT_PUBLIC_DOCS}


def _extract_declared_stage_list(document: str) -> tuple[str, ...]:
    patterns = (
        r"Its 23-stage `FULL_STAGE_IDS` inventory is: (?P<stages>.+?)\. "
        r"The shared composition",
        r"`FULL_STAGE_IDS` is the authoritative 23-stage order: (?P<stages>.+?)\. "
        r"Stages not wired",
    )
    for pattern in patterns:
        match = re.search(pattern, document, re.DOTALL)
        if match is not None:
            return tuple(re.findall(r"`([^`]+)`", match.group("stages")))
    raise AssertionError("current documentation must declare the FULL_STAGE_IDS inventory")


def test_public_stage_order_matches_full_stage_ids() -> None:
    documents = _read_current_public_docs()
    declared_orders = {
        path: _extract_declared_stage_list(document)
        for path, document in documents.items()
        if "FULL_STAGE_IDS" in document and "23-stage" in document
    }

    assert declared_orders
    assert all(order == FULL_STAGE_IDS for order in declared_orders.values())


def _runtime_output_contract(tmp_path: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    root = tmp_path / "document"
    root.mkdir()
    journal = root / "runs" / "x20-batch-transaction.json"
    backup = root / "backup"
    _write_batch_journal(journal, root, backup, _BATCH_OUTPUT_PATHS)
    before = json.loads(journal.read_text(encoding="utf-8"))["expected"]
    assert before == {path.as_posix(): {} for path in _BATCH_OUTPUT_PATHS}

    current, release = (root / path for path in _BATCH_OUTPUT_PATHS)
    current.mkdir(parents=True)
    release.mkdir(parents=True)
    (current / "document-id.pdf").write_bytes(b"artifact")
    (current / "document-id.pdf.manifest.json").write_text("{}", encoding="utf-8")
    (release / "document-id.zip").write_bytes(b"package")
    _record_batch_outputs(journal, "document-id", "pdf")
    expected = json.loads(journal.read_text(encoding="utf-8"))["expected"]
    assert expected != before
    return tuple(
        (path.as_posix() + "/", tuple(sorted(expected[path.as_posix()])))
        for path in _BATCH_OUTPUT_PATHS
    )


def _extract_documented_destination_contract(document: str) -> tuple[tuple[str, str], ...]:
    match = re.search(
        r"## Runtime output destinations\n\n\| Destination \| Runtime-owned contents \|\n"
        r"\|---\|---\|\n(?P<rows>(?:\|.*\|\n)+)",
        document,
    )
    assert match is not None, "architecture must declare the runtime output destinations"
    return tuple(
        (destination, contents)
        for destination, contents in re.findall(r"\| `([^`]+)` \| ([^|]+) \|", match.group("rows"))
    )


def test_current_docs_use_current_and_release_output_contract(tmp_path: Path) -> None:
    documents = _read_current_public_docs()
    current_guidance = "\n".join(documents.values())

    assert "output/work/" not in current_guidance
    assert "output/published/" not in current_guidance
    assert "output/current/" in current_guidance
    assert "output/release/" in current_guidance
    assert "document publish" in current_guidance

    architecture = documents[REPOSITORY_ROOT / "docs" / "architecture.md"]
    assert "only when the selected policy and pipeline permit publication" in architecture
    assert "`document-build` and `document verify` do not publish artifacts" in architecture
    assert "`document release` runs the full pipeline under the release policy" in architecture
    assert "takes an explicit output path" in architecture
    assert "takes an explicit destination" in architecture

    runtime_contract = _runtime_output_contract(tmp_path)
    assert runtime_contract == (
        ("output/current/", ("document-id.pdf", "document-id.pdf.manifest.json")),
        ("output/release/", ("document-id.zip",)),
    )
    assert _extract_documented_destination_contract(architecture) == (
        (runtime_contract[0][0], "`<document-id>.<format>` plus its manifest sidecar after a publish-permitted full build."),
        (runtime_contract[1][0], "`<document-id>.zip` after the managed release pipeline packages successfully."),
    )


def test_current_docs_do_not_advertise_ghost_pipeline_commands() -> None:
    current_guidance = "\n".join(_read_current_public_docs().values())

    for command in (
        "pipeline ingest",
        "pipeline prep",
        "pipeline prepare",
        "pipeline assemble",
        "pipeline all",
    ):
        assert command not in current_guidance
