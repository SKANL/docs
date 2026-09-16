from __future__ import annotations

import json
import os

import pytest

from docs.application.evidence_passport import EvidencePassportService
from docs.domain.evidence_passport import EVIDENCE_PASSPORT_SCHEMA, EvidencePassport, canonical_json, redact
from docs.infrastructure.persistence.evidence_passport_store import FileEvidencePassportStore


def test_canonical_json_is_deterministic_and_rejects_unsupported_values():
    assert canonical_json({"b": [2, 1], "a": {"z": None}}) == b'{"a":{"z":null},"b":[2,1]}'
    with pytest.raises(TypeError, match="supported JSON"):
        canonical_json({"when": object()})


def test_redaction_removes_sensitive_values_before_they_can_be_persisted():
    secret = "do-not-persist-me"
    redacted = redact({"api_token": secret, "source_path": "C:/work/.ssh/id_rsa", "content": f"Authorization: Bearer {secret}", "normal": "safe"})
    rendered = json.dumps(redacted)
    assert secret not in rendered and "id_rsa" not in rendered
    assert redacted["api_token"] == redacted["source_path"] == redacted["content"] == "[REDACTED]"


def test_redaction_scans_secret_content_in_arbitrary_nested_string_fields():
    secret = "do-not-persist-me"
    redacted = redact({"stdout": f"Bearer {secret}", "metadata": {"lines": ["safe", {"command_output": f"api_key={secret}"}]}})
    assert secret not in json.dumps(redacted)
    assert redacted["stdout"] == redacted["metadata"]["lines"][1]["command_output"] == "[REDACTED]"


def test_redaction_catches_secret_aliases_and_paths_in_arbitrary_fields():
    assert redact({"apiKey": "do-not-persist-me", "message": "API Key: do-not-persist-me", "location": "C:/work/.ssh/id_rsa"}) == {"apiKey": "[REDACTED]", "message": "[REDACTED]", "location": "[REDACTED]"}


def test_finalization_returns_an_immutable_redacted_envelope_and_allows_exact_replay(tmp_path):
    service = EvidencePassportService(FileEvidencePassportStore(tmp_path / "passports"))
    passport = service.finalize("run-1", ({"name": "input", "password": "do-not-persist-me", "values": [2, 1]},))
    assert passport == service.finalize("run-1", ({"name": "input", "password": "do-not-persist-me", "values": [2, 1]},))
    assert passport.to_dict()["schema"] == EVIDENCE_PASSPORT_SCHEMA and passport.passport.entries[0]["password"] == "[REDACTED]"
    with pytest.raises((AttributeError, TypeError)):
        passport.passport.entries[0]["name"] = "changed"  # type: ignore[index]


def test_finalization_rejects_a_conflicting_value_for_an_existing_run(tmp_path):
    service = EvidencePassportService(FileEvidencePassportStore(tmp_path / "passports"))
    service.finalize("run-1", ({"name": "one"},))
    with pytest.raises(ValueError, match="already finalized"):
        service.finalize("run-1", ({"name": "two"},))


def test_filesystem_store_writes_deterministic_json_once_and_reads_it_back(tmp_path):
    store = FileEvidencePassportStore(tmp_path / "passports")
    value = EvidencePassport.from_passport_payload("run-1", ({"artifact": "a-1"},))
    store.put(value)
    files = list((tmp_path / "passports").glob("*.json"))
    assert len(files) == 1 and files[0].read_bytes() == canonical_json(value.to_dict()) and store.get("run-1") == value
    store.put(value)
    with pytest.raises(ValueError, match="already finalized"):
        store.put(EvidencePassport.from_passport_payload("run-1", ({"artifact": "a-2"},)))


def test_redaction_normalizes_whitespace_in_sensitive_keys():
    assert redact({"api key": "secret", " client\tsecret ": "value"}) == {"api key": "[REDACTED]", " client\tsecret ": "[REDACTED]"}


def test_redaction_recursively_redacts_sensitive_paths_in_direct_strings_and_lists():
    assert redact(["C:/work/.ssh/id_rsa", {"items": ["/home/user/.aws/credentials", "safe"]}]) == ["[REDACTED]", {"items": ["[REDACTED]", "safe"]}]


def test_store_fsyncs_parent_directory_after_atomic_publication(tmp_path, monkeypatch):
    calls = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real_fsync(fd))[1])
    FileEvidencePassportStore(tmp_path / "passports").put(EvidencePassport.from_passport_payload("run-fsync", ({"artifact": "a"},)))
    assert len(calls) >= 1

