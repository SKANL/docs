# tests/integration/test_wheel_packaging.py
"""Build+install risk (design.md item C, ADR-C / risk table "Package data not
shipped in wheel"): a real `uv build` — the project's declared build backend
(`pyproject.toml` `[build-system] requires = ["hatchling"]`) — must ship the
built-in template JSONs, not just the source-tree checkout. Guards against
regressing `[tool.hatch.build.targets.wheel]` packaging config."""
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
    )
    assert result.returncode == 0, result.stderr
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def test_builtin_templates_ship_in_the_built_wheel(built_wheel):
    names = set(zipfile.ZipFile(built_wheel).namelist())
    assert "docs/templates/builtin/reporte-estadia-tic.json" in names
    assert "docs/templates/builtin/documento-generico.json" in names


def test_builtin_template_package_is_importable_resource_dir(built_wheel):
    # `docs.templates.builtin` must be a real package (has __init__.py) so
    # `importlib.resources.files(...)` resolves it once installed, not a
    # namespace-package edge case.
    names = set(zipfile.ZipFile(built_wheel).namelist())
    assert "docs/templates/__init__.py" in names
    assert "docs/templates/builtin/__init__.py" in names
