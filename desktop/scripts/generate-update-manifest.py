"""Generate the signed Tauri updater manifest for a Windows release."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--msi", type=Path, required=True)
    parser.add_argument("--nsis", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    platforms = {}
    for target, bundle in (("windows-x86_64", args.msi), ("windows-x86_64-nsis", args.nsis)):
        signature = Path(str(bundle) + ".sig").read_text(encoding="utf-8").strip()
        platforms[target] = {
            "url": f"{args.base_url}/{bundle.name}",
            "signature": signature,
        }
    manifest = {
        "version": args.version,
        "notes": f"Review Studio {args.version}",
        "pub_date": datetime.now(UTC).isoformat(),
        "platforms": platforms,
    }
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
