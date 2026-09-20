from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from docs.domain.contracts import Blob

_MANIFEST_METADATA_KEY = "x20-blob"


class S3BlobStore:
    """S3-compatible BlobStore adapter with contract verification at both edges."""

    def __init__(
        self,
        client: Any | None,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        if not bucket or "/" in bucket:
            raise ValueError("bucket must be a non-empty name")
        self._client = client
        self.bucket = bucket
        self.prefix = self._validate_prefix(prefix)
        self.endpoint_url = endpoint_url
        self.unavailable_reason = unavailable_reason

    @property
    def available(self) -> bool:
        return self._client is not None and self.unavailable_reason is None

    @classmethod
    def from_client(
        cls,
        client: Any,
        *,
        bucket: str,
        prefix: str = "",
    ) -> S3BlobStore:
        if not callable(getattr(client, "put_object", None)) or not callable(getattr(client, "get_object", None)):
            raise TypeError("client must provide put_object and get_object")
        return cls(client, bucket=bucket, prefix=prefix)

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        client: Any | None = None,
        region_name: str | None = None,
        **client_kwargs: Any,
    ) -> S3BlobStore:
        parsed = urlparse(url)
        if parsed.scheme not in {"s3", "http", "https"} or not parsed.netloc:
            raise ValueError("S3 URL must use s3://, http://, or https:// and include a bucket")
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.scheme == "s3":
            bucket = parsed.netloc
            endpoint_url = None
            prefix = "/".join(parts)
        else:
            if not parts:
                raise ValueError("S3-compatible URL must include a bucket in its path")
            bucket = parts[0]
            endpoint_url = f"{parsed.scheme}://{parsed.netloc}"
            prefix = "/".join(parts[1:])
        if client is not None:
            return cls(client, bucket=bucket, prefix=prefix, endpoint_url=endpoint_url)

        try:
            boto3 = importlib.import_module("boto3")
        except ModuleNotFoundError:
            return cls(
                None,
                bucket=bucket,
                prefix=prefix,
                endpoint_url=endpoint_url,
                unavailable_reason="boto3 is not installed",
            )
        options = dict(client_kwargs)
        if region_name is not None:
            options["region_name"] = region_name
        if endpoint_url is not None:
            options["endpoint_url"] = endpoint_url
        try:
            s3_client = boto3.client("s3", **options)
        except Exception as exc:
            return cls(
                None,
                bucket=bucket,
                prefix=prefix,
                endpoint_url=endpoint_url,
                unavailable_reason=f"unable to create S3 client: {type(exc).__name__}",
            )
        return cls(s3_client, bucket=bucket, prefix=prefix, endpoint_url=endpoint_url)

    def put(self, blob: Blob, content: bytes) -> None:
        self._require_available()
        self._validate_key(blob.key)
        self._verify_content(blob, content)
        self._client.put_object(
            Bucket=self.bucket,
            Key=self._object_key(blob.key),
            Body=content,
            ContentType=blob.media_type,
            Metadata={_MANIFEST_METADATA_KEY: self._serialize(blob.to_dict())},
        )
        stored = self.get(blob.key)
        if stored != (blob, content):
            raise ValueError("remote blob did not verify after upload")

    def get(self, key: str) -> tuple[Blob, bytes] | None:
        self._require_available()
        self._validate_key(key)
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=self._object_key(key))
        except Exception as exc:
            if self._is_missing_object(exc):
                return None
            raise
        metadata = response.get("Metadata") or {}
        manifest = metadata.get(_MANIFEST_METADATA_KEY) or metadata.get(_MANIFEST_METADATA_KEY.lower())
        if not isinstance(manifest, str):
            raise ValueError("remote blob metadata is missing the x20 manifest")
        try:
            blob = Blob.from_dict(json.loads(manifest))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("remote blob metadata is malformed") from exc
        if blob.key != key:
            raise ValueError("remote blob key does not match requested key")
        content = response.get("Body")
        content = content.read() if callable(getattr(content, "read", None)) else content
        if not isinstance(content, bytes):
            raise ValueError("remote blob body is not bytes")
        if response.get("ContentLength") != len(content):
            raise ValueError("remote blob size does not match ContentLength")
        if response.get("ContentType") != blob.media_type:
            raise ValueError("remote blob media type does not match metadata")
        self._verify_content(blob, content)
        return blob, content

    def _require_available(self) -> None:
        if not self.available:
            raise RuntimeError(f"S3 BlobStore unavailable: {self.unavailable_reason or 'no client'}")

    def _object_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key or key.startswith(("/", "\\")):
            raise ValueError("blob key must be a non-empty relative key")
        parts = key.replace("\\", "/").split("/")
        if any(part in {"", ".", ".."} for part in parts) or "\\" in key:
            raise ValueError("blob key must not contain traversal or empty path segments")

    @classmethod
    def _validate_prefix(cls, prefix: str) -> str:
        if not prefix:
            return ""
        cls._validate_key(prefix.strip("/"))
        return prefix.strip("/")

    @staticmethod
    def _serialize(value: Mapping[str, Any] | dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _verify_content(blob: Blob, content: bytes) -> None:
        if len(content) != blob.size_bytes:
            raise ValueError("blob size does not match content")
        try:
            algorithm, expected = blob.digest.split(":", 1)
            digest = hashlib.new(algorithm, content).hexdigest()
        except (ValueError, TypeError) as exc:
            raise ValueError("blob digest is malformed") from exc
        if not algorithm or not expected or digest != expected:
            raise ValueError("blob digest does not match content")

    @staticmethod
    def _is_missing_object(exc: Exception) -> bool:
        response = getattr(exc, "response", None)
        code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
        return code in {"404", "NoSuchKey", "NoSuchBucket"} or type(exc).__name__ == "NoSuchKey"


__all__ = ["S3BlobStore"]
