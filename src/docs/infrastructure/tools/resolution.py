# src/docs/infrastructure/tools/resolution.py
"""One way to find an external toolchain, shared by all five of them.

`pandoc`, `libreoffice`, `java`, `mmdc` and `resvg` each carried the same
ladder -- PATH, then a `<tool>_bin` override, then `<tool>_fallbacks` --
copied five times. Five copies is five places to fix anything, and it showed:
LibreOffice's Windows installer does NOT put itself on PATH, so a perfectly
ordinary install resolved to nothing. The harness reported `NO DISPONIBLE`,
refused `--format pdf`, skipped visual QA, and skipped seven tests, while the
program sat in its default directory.

So the ladder gains one rung, once: WELL-KNOWN install locations, consulted
LAST. Being last makes it purely additive -- it can only find what the
existing steps already failed to find, so no environment that resolved before
resolves differently now.

Only locations backed by evidence are listed. `pandoc` and `java` are not
here because their installers do put themselves on PATH and nothing observed
says otherwise; inventing paths for them would be superstition wearing the
costume of thoroughness.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any


def _program_files_dirs() -> list[Path]:
    """Windows' program directories, as the running system reports them.

    Read from the environment rather than hardcoded: a machine can have them
    on another drive, and a localized Windows still sets these variables.
    """
    found = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            found.append(Path(value))
    return found


def libreoffice_locations() -> tuple[Path, ...]:
    """Where LibreOffice lands when installed normally, per platform.

    The Windows installer writes to `%ProgramFiles%\\LibreOffice\\program`
    and leaves PATH untouched -- which is the whole reason this module
    exists. The macOS bundle and the usual Linux package paths are included
    for the same reason: a normal install must not read as a missing one.
    """
    candidates = [base / "LibreOffice" / "program" / "soffice.exe" for base in _program_files_dirs()]
    candidates += [
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
        Path("/usr/bin/soffice"),
        Path("/usr/bin/libreoffice"),
        Path("/usr/lib/libreoffice/program/soffice"),
        Path("/snap/bin/libreoffice"),
    ]
    return tuple(candidates)


def resolve_executable(
    paths: dict[str, Any],
    *,
    names: tuple[str, ...],
    config_prefix: str,
    well_known: tuple[Path, ...] = (),
) -> str | None:
    """Find one external tool, or return None.

    In order: every `names` entry on PATH, then `<config_prefix>_bin`, then
    each `<config_prefix>_fallbacks` entry, then `well_known`. Explicit
    configuration outranks a guess, and a guess only ever runs when nothing
    explicit answered.
    """
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            return resolved

    configured = paths.get(f"{config_prefix}_bin")
    if configured and Path(configured).is_file():
        return str(configured)

    for candidate in paths.get(f"{config_prefix}_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.is_file():
            return str(candidate_path)

    for candidate_path in well_known:
        if candidate_path.is_file():
            return str(candidate_path)

    return None
