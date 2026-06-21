# src/docs/domain/sections.py
from __future__ import annotations

import re
from pathlib import Path

_LEADING_ORDER_RE = re.compile(r"^\d+-")


def infer_section_id_from_path(path: Path) -> str:
    return _LEADING_ORDER_RE.sub("", path.stem, count=1)
