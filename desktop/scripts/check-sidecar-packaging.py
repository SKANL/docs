"""Validate the portable Tauri sidecar contract without building an installer."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    desktop = Path(__file__).resolve().parents[1]
    config = json.loads((desktop / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    resources = config.get("bundle", {}).get("resources", [])
    if "../sidecar/*" not in resources:
        raise SystemExit("Tauri resources must include ../sidecar/*")

    rust = (desktop / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
    required_fragments = (
        "resource_dir()",
        'resource_dir.join("sidecar").join(name)',
        'resource_dir.join(name)',
        "/health",
        '"docs-sidecar/v1"',
    )
    missing = [fragment for fragment in required_fragments if fragment not in rust]
    if missing:
        raise SystemExit(f"sidecar supervisor contract is incomplete: {missing}")

    configured = os.environ.get("DOCS_SIDECAR_EXECUTABLE", "").strip()
    if configured and not Path(configured).is_file():
        raise SystemExit("DOCS_SIDECAR_EXECUTABLE must point to an existing file when set")

    print("sidecar packaging contract passed (installer build not required)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
