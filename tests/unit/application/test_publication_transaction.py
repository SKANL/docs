from __future__ import annotations

from pathlib import Path

from docs.application.publication_transaction import Publication, PublicationTransaction


def test_publication_transaction_publishes_all_requested_artifacts(tmp_path: Path) -> None:
    report = tmp_path / "published" / "report.txt"
    manifest = tmp_path / "published" / "manifest.json"

    result = PublicationTransaction().publish(
        (
            Publication("report.txt", report, b"document body"),
            Publication("manifest.json", manifest, b'{"ok":true}'),
        )
    )

    assert result.ok is True
    assert result.outputs == (report, manifest)
    assert report.read_bytes() == b"document body"
    assert manifest.read_bytes() == b'{"ok":true}'
