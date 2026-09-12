"""Application-facing provenance v2 compatibility port."""

from typing import Any

from docs.infrastructure.provenance.v2_ledger import ProvenanceLedgerV2 as _Ledger


class ProvenanceLedgerV2(_Ledger):
    """Keep legacy raw-manifest callers compatible with v2 attestations."""

    def verify_attestation(self, run_id: str, manifest: dict[str, Any]) -> bool:
        recorded = self.load_attestation(run_id)
        if recorded is None or not self.verify_run(run_id):
            return False
        left = recorded.get("manifest", recorded)
        right = manifest.get("manifest", manifest)
        return left == right

__all__ = ["ProvenanceLedgerV2"]
