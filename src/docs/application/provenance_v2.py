"""Application-facing provenance v2 compatibility port."""

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _provenance_class() -> type[Any]:
    from importlib import import_module

    ledger_type = import_module("docs.infrastructure.provenance.v2_ledger").ProvenanceLedgerV2

    class ProvenanceLedgerV2(ledger_type):  # type: ignore[misc, valid-type]
        """Keep legacy raw-manifest callers compatible with v2 attestations."""

        def verify_attestation(self, run_id: str, manifest: dict[str, Any]) -> bool:
            recorded = self.load_attestation(run_id)
            if recorded is None or not self.verify_run(run_id):
                return False
            left = recorded.get("manifest", recorded)
            right = manifest.get("manifest", manifest)
            return left == right

    return ProvenanceLedgerV2


def __getattr__(name: str) -> Any:
    if name != "ProvenanceLedgerV2":
        raise AttributeError(name)
    return _provenance_class()

__all__ = ["ProvenanceLedgerV2"]  # noqa: F822
