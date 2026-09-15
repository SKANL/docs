"""Guard the v2 runtime against deleted alternate pipeline adapters."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_current_pipeline_adapters_are_not_runtime_modules() -> None:
    forbidden = (
        ROOT / "src" / "docs" / "application" / "current_pipeline.py",
        ROOT / "src" / "docs" / "cli" / "current_pipeline_bridge.py",
        ROOT / "src" / "docs" / "application" / "current_pipeline_executor.py",
    )
    assert all(not path.exists() for path in forbidden)
