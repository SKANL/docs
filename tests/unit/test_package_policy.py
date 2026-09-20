from __future__ import annotations

from check_package_policy import forbidden_members


def test_package_policy_allows_supported_legacy_compatibility_adapter() -> None:
    assert forbidden_members(["docs/template_compiler/legacy.py"]) == []


def test_package_policy_rejects_retired_runtime_path_components() -> None:
    assert forbidden_members(
        ["docs/v2_atomic/service.py", "docs/flat_pipeline.py"]
    ) == ["docs/v2_atomic/service.py", "docs/flat_pipeline.py"]
