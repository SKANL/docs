# tests/unit/test_agents_md_packaging.py
"""Build+install risk (design.md item B, ADR-B / risk table "Package data not
shipped in wheel"): a real `uv build` must ship the repo-root AGENTS.md as
package data at docs/data/AGENTS.md, byte-identical to the source (Task
10.1), and `docs guide` must print it from an installed wheel with no repo
checkout (Task 10.3). Mirrors tests/integration/test_wheel_packaging.py's
build fixture pattern (PR3 precedent)."""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not on PATH — build+install packaging check needs the project's build tool.")
    out_dir = tmp_path_factory.mktemp("wheel-dist")
    result = subprocess.run(
        [uv, "build", "--wheel", "-o", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,  # returncode is asserted below, not raised
    )
    assert result.returncode == 0, result.stderr
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_agents_md_ships_in_the_built_wheel_byte_identical_to_repo_root(built_wheel):
    names = set(zipfile.ZipFile(built_wheel).namelist())
    assert "docs/data/AGENTS.md" in names
    packaged_bytes = zipfile.ZipFile(built_wheel).read("docs/data/AGENTS.md")
    repo_root_bytes = (REPO_ROOT / "AGENTS.md").read_bytes()
    assert packaged_bytes == repo_root_bytes


def test_docs_data_package_is_importable_resource_dir(built_wheel):
    # Same namespace-package edge case PR3 hit for docs.templates.builtin:
    # importlib.resources.files("docs.data") needs a real __init__.py to
    # resolve reliably once installed.
    names = set(zipfile.ZipFile(built_wheel).namelist())
    assert "docs/data/__init__.py" in names


def test_docs_guide_prints_agents_md_from_an_installed_wheel_with_no_repo_checkout(built_wheel, tmp_path):
    uv = shutil.which("uv")
    result = subprocess.run(
        [uv, "run", "--no-project", "--with", str(built_wheel), "--", "docs", "guide"],
        cwd=tmp_path,  # not the repo -- proves no repo checkout is needed
        capture_output=True,
        text=True,
        check=False,  # returncode is asserted below, not raised
    )
    assert result.returncode == 0, result.stderr
    repo_root_text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert result.stdout.strip() == repo_root_text.strip()
