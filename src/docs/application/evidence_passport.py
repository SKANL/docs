from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from threading import Lock
from typing import Any

from docs.domain.evidence_passport import DEFAULT_REDACTION_POLICY, EvidencePassport, RedactionPolicy
from docs.domain.ports.evidence_passport import EvidencePassportStore
from docs.observability import NoOpObservability, ObservabilityPort


class EvidencePassportService:
    # Keep the read/conditional-write sequence atomic for stores that expose
    # only the compatibility get/put API. Filesystem stores add their own
    # cross-process write-once protection in put().
    _finalization_lock = Lock()

    def __init__(
        self,
        store: EvidencePassportStore,
        policy: RedactionPolicy = DEFAULT_REDACTION_POLICY,
        observability: ObservabilityPort | None = None,
    ) -> None:
        self._store = store
        self._policy = policy
        self._observability = observability or NoOpObservability()
        self._finalized_metrics: set[str] = set()
        self._metrics_lock = Lock()

    def _record_metrics_once(self, run_id: str, passport: EvidencePassport) -> None:
        with self._metrics_lock:
            if run_id in self._finalized_metrics:
                return
            self._finalized_metrics.add(run_id)
        with suppress(Exception):
            self._observability.record_passport(passport.passport)

    def finalize(self, run_id: str, entries: tuple[Mapping[str, Any], ...]) -> EvidencePassport:
        candidate = EvidencePassport.from_passport_payload(run_id, entries, self._policy)
        with self._finalization_lock:
            existing = self._store.get(run_id)
            if existing is None:
                self._store.put(candidate)
                self._record_metrics_once(run_id, candidate)
                return candidate
            if existing == candidate:
                return existing
            raise ValueError(f"evidence passport for {run_id} is already finalized")
