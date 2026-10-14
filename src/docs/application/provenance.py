"""Application-facing provenance port.

Services receive a ``LedgerFactory`` from the composition root; the concrete
filesystem ledger lives in ``infrastructure/provenance/ledger.py``.
"""

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Protocol


class ProvenanceLedgerPort(Protocol):
    """Ledger behavior the application layer relies on."""

    def record_run(
        self,
        run_id: str,
        *,
        inputs: Iterable[Path],
        outputs: Iterable[Path],
        output_identities: Mapping[Path, Path] | None = None,
    ) -> dict[str, Any]: ...

    def load_run(self, run_id: str) -> dict[str, Any] | None: ...

    def record_attestation(self, run_id: str, manifest: dict[str, Any]) -> dict[str, Any]: ...

    def load_attestation(self, run_id: str) -> dict[str, Any] | None: ...

    def verify_run(self, run_id: str, *, require_trusted_root: bool = False) -> bool: ...

    def verify_attestation(self, run_id: str, manifest: dict[str, Any]) -> bool: ...


class LedgerFactory(Protocol):
    """Open the ledger stored at ``log_path`` (the composition root binds the adapter)."""

    def __call__(self, log_path: Path, *, trusted_root: Path | None = None) -> ProvenanceLedgerPort: ...
