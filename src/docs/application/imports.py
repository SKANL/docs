"""Safe source import service for API and desktop clients."""

from __future__ import annotations

import base64
import hashlib
import io
import mimetypes
import re
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from docs.domain.workspace_format import validate_workspace_marker


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
        return self.import_bytes(workspace_root, safe_name, content, document_id=document_id)

    def import_bytes(
        self,
        workspace_root: str | Path,
        filename: str,
        content: bytes,
        *,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        safe_name = self._filename(filename)
        if len(content) > self.max_bytes:
            raise ImportError("source_too_large")
        root = Path(workspace_root).expanduser().resolve()
        validate_workspace_marker(root)
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
        mime = self._detect_mime(content, safe_name)
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
        # Workspace document manifests accept only lowercase letters, digits,
        # and hyphens. Underscores are common in real filenames, so normalize
        # them instead of returning an id that prepare/build later rejects.
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
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

    @classmethod
    def _detect_mime(cls, content: bytes, filename: str) -> str:
        """Prefer content signatures over a caller-controlled extension.

        The filename is retained for display and routing, but import metadata
        must describe the bytes that were actually stored.  ZIP-based Office
        documents are distinguished from arbitrary ZIP files by their OOXML
        marker; unknown formats retain the extension fallback so existing
        adapters can report a useful unsupported-input finding.
        """
        if content.startswith(b"%PDF-"):
            return "application/pdf"
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
            return "image/gif"
        if content.startswith(b"\x89PNG"):
            return "image/png"
        if content.startswith(b"PK\x03\x04"):
            # DOCX/XLSX/PPTX are ZIP containers.  The ingest adapter owns
            # detailed archive validation, but reading
            # the central directory here gives accurate metadata even when
            # the package names are compressed or appear after the first MB.
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as archive:
                    names = set(archive.namelist())
            except zipfile.BadZipFile:
                names = set()
            if "word/document.xml" in names:
                return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            if "xl/workbook.xml" in names:
                return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if "ppt/presentation.xml" in names:
                return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        return cls._mime_type(filename)
