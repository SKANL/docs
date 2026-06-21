# src/docs/infrastructure/persistence/json_evidence_repository.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_TRACEABILITY_SUFFIXES = {".md", ".json"}


def _strip_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_generated_at(item) for key, item in value.items() if key != "generated_at"}
    if isinstance(value, list):
        return [_strip_generated_at(item) for item in value]
    return value


class JsonEvidenceRepository:
    def hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def hash_json(self, value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def list_manual_files(self, manual_dir: Path) -> list[Path]:
        return sorted(manual_dir.glob("*.md"))

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def file_exists(self, path: Path) -> bool:
        return path.exists()

    def file_size(self, path: Path) -> int:
        return path.stat().st_size

    def list_traceability_files(self, extracted_dir: Path) -> list[Path]:
        return sorted(
            path
            for path in extracted_dir.glob("*")
            if path.is_file() and path.suffix.lower() in _TRACEABILITY_SUFFIXES
        )

    def read_manifest(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def write_manifest(self, path: Path, payload: dict[str, Any]) -> None:
        next_payload = dict(payload)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            if _strip_generated_at(existing) == _strip_generated_at(next_payload):
                return
        next_payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(next_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
