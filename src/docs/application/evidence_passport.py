from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from docs.domain.evidence_passport import DEFAULT_REDACTION_POLICY, EvidencePassport, RedactionPolicy
from docs.domain.ports.evidence_passport import EvidencePassportStore


class EvidencePassportService:
    def __init__(self, store: EvidencePassportStore, policy: RedactionPolicy = DEFAULT_REDACTION_POLICY) -> None:
        self._store = store
        self._policy = policy

    def finalize(self, run_id: str, entries: tuple[Mapping[str, Any], ...]) -> EvidencePassport:
        candidate = EvidencePassport.from_passport_payload(run_id, entries, self._policy)
        existing = self._store.get(run_id)
        if existing is None:
            self._store.put(candidate)
            return candidate
        if existing == candidate:
            return existing
        raise ValueError(f"evidence passport for {run_id} is already finalized")
