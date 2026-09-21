"""Safe source import service for API and desktop clients."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


class ImportError(ValueError):
    pass


class SourceImportService:
    def __init__(self, max_bytes: int = 100 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes

    def import_base64(
        self,
        workspace_root: str | Path,
        filename: str,
        content_base64: str,
        *,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        safe_name = self._filename(filename)
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ImportError("invalid_base64") from exc
        if not content:
            raise ImportError("empty_source")
        if len(content) > self.max_bytes:
            raise ImportError("source_too_large")
        root = Path(workspace_root).expanduser().resolve()
        doc = self._document_id(document_id or Path(safe_name).stem)
        inbox = root / "documents" / doc / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(content).hexdigest()
        destination = inbox / f"{digest[:12]}-{safe_name}"
        deduplicated = False
        if destination.is_file() and destination.stat().st_size == len(content):
            try:
                deduplicated = hashlib.sha256(destination.read_bytes()).hexdigest() == digest
            except OSError:
                deduplicated = False
        if not deduplicated:
            temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
            temporary.write_bytes(content)
            temporary.replace(destination)
        mime = self._mime_type(safe_name)
        return {
            "id": f"import-{digest[:16]}",
            "document_id": doc,
            "filename": safe_name,
            "path": str(destination),
            "mime_type": mime,
            "size": len(content),
            "sha256": digest,
            "deduplicated": deduplicated,
        }

    @staticmethod
    def _filename(value: str) -> str:
        if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
            raise ImportError("invalid_filename")
        if re.search(r"[\x00-\x1f]", value):
            raise ImportError("invalid_filename")
        return value

    @staticmethod
    def _document_id(value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-_").lower()
        if not normalized:
            raise ImportError("invalid_document_id")
        return normalized[:80]

    @staticmethod
    def _mime_type(filename: str) -> str:
        # Python's Windows MIME registry does not consistently classify
        # Markdown files. Keep import metadata useful for downstream ingest.
        known = {
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".txt": "text/plain",
        }
        return known.get(Path(filename).suffix.lower()) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
