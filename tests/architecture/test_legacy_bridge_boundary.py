"""Keep incidental CLI helpers independent from the legacy pipeline aggregate."""

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "docs" / "cli" / "commands"


def test_command_helpers_do_not_read_legacy_pipeline_manifest_state() -> None:
    commands = ("section_app.py", "doc_app.py", "collection_app.py")
    violations = []
    for name in commands:
        source = (SRC / name).read_text(encoding="utf-8")
        if "deps.pipeline.rules_manifest_state" in source:
            violations.append(name)
    assert not violations, "incidental manifest-state reads must use the named composition-root service: " + ", ".join(violations)
