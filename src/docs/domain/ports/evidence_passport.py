from __future__ import annotations

from typing import Protocol

from docs.domain.evidence_passport import EvidencePassport


class EvidencePassportStore(Protocol):
    """Write-once storage for finalized evidence passports."""

    def put(self, passport: EvidencePassport) -> None: ...
    def get(self, run_id: str) -> EvidencePassport | None: ...
