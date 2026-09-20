import json
import shutil
from pathlib import Path

from docs.cli.commands.document_app import (
    _batch_journal_path,
    _record_batch_outputs,
    _recover_batch_transaction,
    _write_batch_journal,
)


def test_batch_transaction_recovery_uses_the_paths_written_to_its_journal(tmp_path: Path) -> None:
    document_root = tmp_path / "document"
    paths = (Path("output") / "current", Path("output") / "release")
    (document_root / paths[0]).mkdir(parents=True)
    (document_root / paths[1]).mkdir(parents=True)
    (document_root / paths[0] / "report.pdf").write_bytes(b"pdf")
    (document_root / paths[0] / "report.pdf.manifest.json").write_text("{}", encoding="utf-8")
    (document_root / paths[1] / "report.zip").write_bytes(b"zip")

    journal = _batch_journal_path(document_root)

    def write_journal() -> None:
        backup = document_root / ".x20-batch-backup"
        for relative in paths:
            source = document_root / relative
            destination = backup / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                shutil.copytree(source, destination)
        _write_batch_journal(journal, document_root, backup, paths)

    write_journal()
    _recover_batch_transaction(journal)

    write_journal()
    _record_batch_outputs(journal, "report", "pdf")

    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert payload["paths"] == ["output/current", "output/release"]
    assert "report.pdf" in payload["expected"]["output/current"]
