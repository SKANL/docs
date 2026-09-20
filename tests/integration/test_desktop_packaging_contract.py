from __future__ import annotations

import json
from pathlib import Path


def test_tauri_sidecar_packaging_contract_is_linux_checkable_without_installer() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "desktop/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    resources = config["bundle"]["resources"]
    assert "../sidecar/*" in resources

    rust = (root / "desktop/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    assert "resource_dir()" in rust
    assert 'resource_dir.join("sidecar").join(name)' in rust
    assert 'resource_dir.join(name)' in rust
    assert "/health" in rust
    assert '"docs-sidecar/v1"' in rust

    check_script = root / "desktop/scripts/check-sidecar-packaging.py"
    assert check_script.is_file()
    script = check_script.read_text(encoding="utf-8")
    assert "resource_dir" in script
    assert "docs-sidecar/v1" in script

    build_script = root / "desktop/scripts/build-windows.ps1"
    assert build_script.is_file()
    assert "check:sidecar" in build_script.read_text(encoding="utf-8")

    package = json.loads((root / "desktop/package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["check:sidecar"] == "python scripts/check-sidecar-packaging.py"
    assert package["scripts"]["build:sidecar"].endswith("scripts/build-sidecar.ps1")
    assert "beforeDevCommand" in config["build"]
    assert "review-studio" in config["build"]["beforeDevCommand"]

    sidecar = (root / "desktop/scripts/build-sidecar.ps1").read_text(encoding="utf-8")
    assert "pyinstaller" in sidecar
    assert "docs-sidecar.exe" in sidecar
