# tests/unit/infrastructure/test_tool_resolution.py
"""One resolution strategy, shared by every external toolchain.

Five resolvers (`pandoc`, `libreoffice`, `java`, `mmdc`, `resvg`) each held
the same PATH-then-`_bin`-then-`_fallbacks` ladder, copied. That is five
places to fix anything, and it showed: LibreOffice's Windows installer does
NOT add itself to PATH, so a perfectly normal install at
`C:/Program Files/LibreOffice/program/soffice.exe` resolved to nothing.
The user had it installed; the harness reported `NO DISPONIBLE`, refused to
render PDF, skipped visual QA, and skipped seven tests.

The shared ladder gains one rung -- well-known install locations, consulted
LAST so it can only find what was previously unfound.
"""
from __future__ import annotations

from docs.infrastructure.tools.resolution import resolve_executable


def test_path_still_wins(tmp_path, monkeypatch):
    on_path = tmp_path / "en-path.exe"
    on_path.write_text("", encoding="utf-8")
    well_known = tmp_path / "conocido.exe"
    well_known.write_text("", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: str(on_path))

    resolved = resolve_executable(
        {}, names=("soffice",), config_prefix="libreoffice", well_known=(well_known,)
    )

    assert resolved == str(on_path)


def test_a_configured_binary_is_used_when_path_has_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    configured = tmp_path / "config.exe"
    configured.write_text("", encoding="utf-8")

    resolved = resolve_executable(
        {"libreoffice_bin": str(configured)}, names=("soffice",), config_prefix="libreoffice"
    )

    assert resolved == str(configured)


def test_a_well_known_location_is_found_when_nothing_else_is(tmp_path, monkeypatch):
    # THE bug. LibreOffice's Windows installer leaves PATH alone, so a normal
    # install was invisible and the harness told the user to install software
    # they already had.
    monkeypatch.setattr("shutil.which", lambda name: None)
    installed = tmp_path / "Program Files" / "LibreOffice" / "program" / "soffice.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("", encoding="utf-8")

    resolved = resolve_executable(
        {}, names=("soffice",), config_prefix="libreoffice", well_known=(installed,)
    )

    assert resolved == str(installed)


def test_well_known_is_consulted_last(tmp_path, monkeypatch):
    # Purely additive: a location list can only find what the existing ladder
    # missed, so no environment that resolved before can resolve differently.
    monkeypatch.setattr("shutil.which", lambda name: None)
    configured = tmp_path / "elegido.exe"
    configured.write_text("", encoding="utf-8")
    well_known = tmp_path / "conocido.exe"
    well_known.write_text("", encoding="utf-8")

    resolved = resolve_executable(
        {"libreoffice_bin": str(configured)},
        names=("soffice",),
        config_prefix="libreoffice",
        well_known=(well_known,),
    )

    assert resolved == str(configured)


def test_a_well_known_path_that_does_not_exist_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert resolve_executable(
        {}, names=("soffice",), config_prefix="libreoffice",
        well_known=(tmp_path / "no-existe.exe",),
    ) is None


def test_every_name_is_tried_on_path(tmp_path, monkeypatch):
    # LibreOffice answers to `soffice` on Windows and `libreoffice` on many
    # Linux packages; the ladder must try both rather than only the first.
    seen = []

    def fake_which(name):
        seen.append(name)
        return "/usr/bin/libreoffice" if name == "libreoffice" else None

    monkeypatch.setattr("shutil.which", fake_which)

    resolved = resolve_executable({}, names=("soffice", "libreoffice"), config_prefix="libreoffice")

    assert resolved == "/usr/bin/libreoffice"
    assert seen == ["soffice", "libreoffice"]
