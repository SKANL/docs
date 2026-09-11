from docs.domain.provenance import ProvenanceLedger


def test_ledger_emits_a_deterministic_v1_payload_and_verifies_its_entries():
    """Breaks if entries lose their content hash or the v1 schema changes."""
    ledger = ProvenanceLedger.from_entries(
        [{"operation": "assemble", "inputs": [{"path": "sections/intro.md", "sha256": "a" * 64, "state": "ready"}], "outputs": [{"path": "output/report.docx", "sha256": "b" * 64, "state": "published"}]}]
    )

    payload = ledger.to_dict()

    assert payload["schema"] == "docs.provenance/v1"
    assert payload["entries"][0]["sha256"] == "941df99a5ec0744b07a0ae075341ab523dbec238b12db379cd8e0303cdb41615"
    assert ledger.verify() == []


def test_ledger_reads_legacy_log_entries_and_reports_tampering():
    """Breaks if legacy logs stop being readable or hashes stop detecting edits."""
    ledger = ProvenanceLedger.from_dict({"events": [{"action": "render", "input": "section.md", "output": "report.docx"}]})

    payload = ledger.to_dict()
    payload["entries"][0]["operation"] = "tampered"

    assert ledger.verify(payload) == ["entries[0].sha256 does not match entry content"]
