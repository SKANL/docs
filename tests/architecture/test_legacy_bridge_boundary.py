"""Guard the v2 runtime against deleted legacy pipeline adapters."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_pipeline_adapters_are_not_runtime_modules() -> None:
    forbidden = (
        ROOT / "src" / "docs" / "application" / "legacy_pipeline.py",
        ROOT / "src" / "docs" / "cli" / "legacy_pipeline_bridge.py",
        ROOT / "src" / "docs" / "application" / "legacy_pipeline_executor.py",
    )
    assert all(not path.exists() for path in forbidden)
