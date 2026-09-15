"""Application-facing provenance v2 compatibility port."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from docs.domain.identity import sha256_content


@lru_cache(maxsize=1)
def _provenance_class() -> type[Any]:
    from importlib import import_module

    ledger_type = import_module("docs.infrastructure.provenance.ledger").ProvenanceLedger

    class ProvenanceLedger(ledger_type):  # type: ignore[misc, valid-type]
        """Keep legacy raw-manifest callers compatible with v2 attestations."""

        def verify_attestation(self, run_id: str, manifest: dict[str, Any]) -> bool:
            recorded = self.load_attestation(run_id)
            if recorded is None or not self.verify_run(run_id):
                return False
            left = recorded.get("manifest", recorded)
            right = manifest.get("manifest", manifest)
            if left == right:
                return True
            if not isinstance(recorded, dict) or not isinstance(left, dict) or not isinstance(right, dict):
                return False
            recorded_hash = recorded.get("sha256")
            if recorded_hash is not None and recorded_hash != sha256_content(left):
                return False
            left = _without_optional_artifact_metadata(left)
            right = _without_optional_artifact_metadata(right)
            return left == right

    return ProvenanceLedger


def _without_optional_artifact_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize only fields added after the initial v2 attestation schema."""
    normalized = dict(payload)
    # v2.1 manifests keep the run id as metadata but exclude it from the
    # content-addressed attestation. Accept older attestations that included
    # it when comparing against a current manifest.
    normalized.pop("provenance_run", None)
    artifacts = normalized.get("artifacts")
    if isinstance(artifacts, list):
        normalized["artifacts"] = [
            {
                key: value
                for key, value in item.items()
                if key not in {"media_type", "size_bytes"}
            }
            if isinstance(item, dict)
            else item
            for item in artifacts
        ]
        for item in normalized["artifacts"]:
            if isinstance(item, dict) and isinstance(item.get("path"), str):
                # Early v2 manifests stored absolute workspace paths.  Path
                # identity is now content-addressed by artifact name, so
                # normalize only this legacy comparison field; publication
                # still validates the live source path and digest separately.
                item["path"] = Path(item["path"]).name
    return normalized


def __getattr__(name: str) -> Any:
    if name != "ProvenanceLedger":
        raise AttributeError(name)
    return _provenance_class()

__all__ = ["ProvenanceLedger"]  # noqa: F822

