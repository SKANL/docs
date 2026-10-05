"""Rewrite the parity-matrix rows from the live capability catalogue, keeping existing UI cells.

Run from the repository root: `uv run python tools/regen_parity_matrix.py "<command>=<UI cell>" ...`;
an override sets the UI cell of a command, `excluded` rows default to their catalogue reason.
"""

import pathlib
import re
import sys

from docs.api.openapi import build_capability_catalog

path = pathlib.Path("docs/review-studio/cli-api-ui-parity.md")
text = path.read_text(encoding="utf-8")
ui = {}
for line in text.splitlines():
    m = re.match(r"^\| `docs ([^`]+)` \|", line)
    if m:
        ui[m.group(1)] = [c.strip() for c in line.strip("|").split("|")][3]
overrides = dict(a.split("=", 1) for a in sys.argv[1:])
rows = []
for g in build_capability_catalog()["groups"]:
    for c in g["capabilities"]:
        cmd = c["cli_command"]
        route = f'`{c["route"]}`' if c["route"] else "—"
        scopes = ", ".join(f"`{s}`" for s in c["scopes"]) or "—"
        excluded = f"Excluded (CLI only): {c['reason']}" if c["status"] == "excluded" else None
        cell = overrides.get(cmd) or excluded or ui.get(cmd) or "Not exposed (planned)"
        rows.append(f'| `docs {cmd}` | {route} | {c["status"]} | {cell} | {c["slice"]} | {scopes} |')
lines = text.splitlines()
indexes = [i for i, row in enumerate(lines) if row.startswith("| `docs ")]
lines[indexes[0] : indexes[-1] + 1] = rows
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(len(rows), "rows")
