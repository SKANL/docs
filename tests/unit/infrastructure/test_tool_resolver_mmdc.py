# tests/unit/infrastructure/test_tool_resolver_mmdc.py
"""`resolve_mmdc_executable` mirrors `resolve_pandoc_executable`'s PATH-then-
config-fallback shape (tasks.md 3.1)."""
from docs.infrastructure.tools.mmdc_resolution import resolve_mmdc_executable


def test_resolve_mmdc_executable_uses_path_when_which_finds_it(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/mmdc" if name == "mmdc" else None)
    assert resolve_mmdc_executable({}) == "/usr/local/bin/mmdc"


def test_resolve_mmdc_executable_uses_configured_bin_when_which_misses(monkeypatch, tmp_path):
    fake_mmdc = tmp_path / "mmdc.exe"
    fake_mmdc.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_mmdc_executable({"mmdc_bin": str(fake_mmdc)})
    assert result == str(fake_mmdc)


def test_resolve_mmdc_executable_falls_back_to_fallback_list(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback_mmdc.exe"
    fallback.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_mmdc_executable({"mmdc_fallbacks": [str(fallback)]})
    assert result == str(fallback)


def test_resolve_mmdc_executable_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_mmdc_executable({}) is None
