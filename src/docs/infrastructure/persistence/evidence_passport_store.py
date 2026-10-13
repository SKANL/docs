from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from docs.domain.evidence_passport import EvidencePassport, canonical_json
from docs.domain.identity import sha256_bytes
from docs.infrastructure.atomic_write import fsync_directory


class FileEvidencePassportStore:
    """Filesystem-backed evidence passports with atomic write-once semantics."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, passport: EvidencePassport) -> None:
        target = self._path_for(passport.passport.run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json(passport.to_dict())
        temporary = self._write_temporary(payload)
        try:
            try:
                os.link(temporary, target)
            except FileExistsError:
                existing = self.get(passport.passport.run_id)
                if existing == passport:
                    return
                raise ValueError(f"evidence passport for {passport.passport.run_id} is already finalized") from None
            fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, run_id: str) -> EvidencePassport | None:
        path = self._path_for(run_id)
        if not path.is_file():
            return None
        passport = EvidencePassport.from_dict(json.loads(path.read_bytes()))
        if passport.passport.run_id != run_id:
            raise ValueError("evidence passport storage key does not match run id")
        return passport

    def _path_for(self, run_id: str) -> Path:
        if type(run_id) is not str or not run_id:
            raise TypeError("run_id must be a non-empty string")
        return self._root / f"{sha256_bytes(run_id.encode('utf-8'))}.json"

    def _write_temporary(self, payload: bytes) -> Path:
        descriptor, name = tempfile.mkstemp(dir=self._root, prefix=".evidence-passport-", suffix=".tmp")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(name)
