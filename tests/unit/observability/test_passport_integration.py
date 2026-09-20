from __future__ import annotations

from docs.application.evidence_passport import EvidencePassportService
from docs.observability import Observability


class Store:
    def __init__(self) -> None:
        self.value = None

    def get(self, run_id):
        return self.value

    def put(self, passport):
        self.value = passport


def test_evidence_passport_finalization_emits_derived_metrics():
    events: list[tuple[str, float, dict[str, str]]] = []
    telemetry = Observability(
        increment_hook=lambda name, value, attrs: events.append((name, value, attrs)),
    )
    store = Store()

    EvidencePassportService(store, observability=telemetry).finalize(
        "run-1", ({"status": "accepted"}, {"status": "failed"})
    )

    assert ("docs.passport.entries", 2, {}) in events
    assert ("docs.passport.entries.accepted", 1, {}) in events
    assert ("docs.passport.entries.failed", 1, {}) in events


def test_passport_telemetry_failure_does_not_fail_after_durable_write():
    class FailingObservability:
        def record_passport(self, _passport):
            raise RuntimeError("telemetry unavailable")

    store = Store()
    result = EvidencePassportService(store, observability=FailingObservability()).finalize(
        "run-1", ({"status": "accepted"},)
    )

    assert store.value == result


def test_passport_finalization_metrics_are_emitted_once_for_idempotent_retry():
    events = []
    telemetry = Observability(increment_hook=lambda name, value, attrs: events.append(name))
    service = EvidencePassportService(Store(), observability=telemetry)
    service.finalize("run-1", ({"status": "accepted"},))
    service.finalize("run-1", ({"status": "accepted"},))
    assert events.count("docs.passport.entries") == 1
