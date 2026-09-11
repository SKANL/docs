from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TransformSpec:
    output_dir: Path
    expected_outputs: tuple[str, ...]
    name: str = "transform"


@dataclass(frozen=True)
class TransformResult:
    output_dir: Path
    outputs: tuple[Path, ...]
