# tests/unit/infrastructure/test_content_probe_adapter.py
from __future__ import annotations

from docs.domain.ports.content_probe_port import ContentSignals
from docs.infrastructure.ingest.content_probe_adapter import FilesystemContentProbeAdapter


def test_probe_returns_lowercase_extension_without_dot(tmp_path):
    path = tmp_path / "manual.PDF"
    path.write_bytes(b"stub")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="pdf")


def test_probe_returns_empty_extension_for_extensionless_file(tmp_path):
    path = tmp_path / "README"
    path.write_bytes(b"stub")

    result = FilesystemContentProbeAdapter().probe(path)

    assert result == ContentSignals(extension="")


class _BadPath:
    """Simulates a locale/platform read failure (design.md §4 "Content probe
    reads differ by platform/locale") -- any attribute access that would
    normally read path data raises, instead of returning a string."""

    @property
    def suffix(self) -> str:
        raise OSError("simulated platform/locale failure")


def test_probe_failure_returns_empty_signals_fail_open():
    result = FilesystemContentProbeAdapter().probe(_BadPath())  # type: ignore[arg-type]

    assert result == ContentSignals()
