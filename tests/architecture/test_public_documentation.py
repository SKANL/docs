from __future__ import annotations

import re
from pathlib import Path

from docs.application.pipeline_service import FULL_STAGE_IDS


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


def test_current_docs_use_current_and_release_output_contract() -> None:
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
