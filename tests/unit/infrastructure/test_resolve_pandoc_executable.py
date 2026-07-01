from pathlib import Path

from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


def test_resolve_pandoc_executable_finds_real_pandoc_on_path():
    # Confirmed installed in this dev environment (pandoc 3.10).
    assert resolve_pandoc_executable({}) is not None


def test_resolve_pandoc_executable_uses_configured_bin_when_which_misses(monkeypatch, tmp_path):
    fake_pandoc = tmp_path / "pandoc.exe"
    fake_pandoc.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_pandoc_executable({"pandoc_bin": str(fake_pandoc)})
    assert result == str(fake_pandoc)


def test_resolve_pandoc_executable_falls_back_to_fallback_list(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback_pandoc.exe"
    fallback.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_pandoc_executable({"pandoc_fallbacks": [str(fallback)]})
    assert result == str(fallback)


def test_resolve_pandoc_executable_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_pandoc_executable({}) is None
