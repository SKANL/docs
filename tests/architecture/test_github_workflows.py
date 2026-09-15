import re
from pathlib import Path

WORKFLOW_DIR = Path(__file__).parents[2] / ".github" / "workflows"
WORKFLOWS = tuple(WORKFLOW_DIR.glob("*.yml"))


def test_workflows_have_least_privilege_and_timeouts() -> None:
    assert WORKFLOWS
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions:\s*$", text), path
        assert re.search(r"(?m)^\s+contents:\s+read\s*$", text), path
        if "uses: ./.github/workflows/" not in text:
            assert re.search(r"(?m)^\s+timeout-minutes:\s+\d+\s*$", text), path


def test_workflows_pin_actions_and_reject_unsafe_triggers() -> None:
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"(?m)^\s*pull_request_target\s*:", text) is None, path
        assert re.search(r"doctor\s*\|\|\s*true", text) is None, path
        for line in text.splitlines():
            if "uses:" in line and "grep" not in line and "./.github/workflows/" not in line:
                assert re.search(r"@[0-9a-f]{40}\b", line), f"un-pinned action in {path}: {line}"


def test_toolchain_downloads_have_checksums_and_release_does_not_publish() -> None:
    toolchains = (WORKFLOW_DIR / "toolchains.yml").read_text(encoding="utf-8")
    assert "sha256sum --check" in toolchains
    release = (WORKFLOW_DIR / "release-prepare.yml").read_text(encoding="utf-8")
    assert "pypi" not in release.lower()
    assert "twine upload" not in release.lower()
    assert "upload-artifact" in release


def test_security_and_reusable_workflows_exist() -> None:
    assert (WORKFLOW_DIR / "security.yml").exists()
    assert (WORKFLOW_DIR / "reusable-python.yml").exists()
