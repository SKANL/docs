# tests/unit/infrastructure/test_tool_resolver_resvg.py
"""`resolve_resvg_executable` mirrors `resolve_mmdc_executable`'s PATH-then-
config-fallback shape (tasks.md 4.1)."""
from docs.infrastructure.tools.resvg_resolution import resolve_resvg_executable


def test_resolve_resvg_executable_uses_path_when_which_finds_it(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/resvg" if name == "resvg" else None)
    assert resolve_resvg_executable({}) == "/usr/local/bin/resvg"


def test_resolve_resvg_executable_uses_configured_bin_when_which_misses(monkeypatch, tmp_path):
    fake_resvg = tmp_path / "resvg.exe"
    fake_resvg.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_resvg_executable({"resvg_bin": str(fake_resvg)})
    assert result == str(fake_resvg)


def test_resolve_resvg_executable_falls_back_to_fallback_list(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback_resvg.exe"
    fallback.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_resvg_executable({"resvg_fallbacks": [str(fallback)]})
    assert result == str(fallback)


def test_resolve_resvg_executable_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_resvg_executable({}) is None
