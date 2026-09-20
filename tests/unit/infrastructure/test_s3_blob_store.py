from __future__ import annotations

import hashlib
import io
import json
import sys
from typing import Any

import pytest

from docs.domain.contracts import Blob
from docs.infrastructure.persistence.s3_blob_store import S3BlobStore


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}

    def put_object(self, **kwargs: Any) -> None:
        if kwargs.get("IfNoneMatch") == "*" and (kwargs["Bucket"], kwargs["Key"]) in self.objects:
            raise RuntimeError("PreconditionFailed")
        if "IfMatch" in kwargs:
            current = self.objects.get((kwargs["Bucket"], kwargs["Key"]))
            if current is None or current.get("ETag") != kwargs["IfMatch"]:
                raise RuntimeError("PreconditionFailed")
        stored = dict(kwargs)
        stored["ETag"] = json.loads(kwargs["Metadata"]["x20-blob"])["digest"]
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = stored

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        stored = self.objects[(Bucket, Key)]
        return {
            "Body": io.BytesIO(stored["Body"]),
            "ContentLength": len(stored["Body"]),
            "ContentType": stored["ContentType"],
            "Metadata": stored["Metadata"],
            "ETag": json.loads(stored["Metadata"]["x20-blob"])["digest"],
        }


def _blob(content: bytes = b"hello") -> Blob:
    return Blob(
        "reports/output.bin",
        f"sha256:{hashlib.sha256(content).hexdigest()}",
        len(content),
        "application/custom",
        {"source": "test", "nested": {"enabled": True}},
    )


def test_s3_blob_store_round_trips_blob_and_serializes_metadata_deterministically() -> None:
    client = FakeS3()
    store = S3BlobStore.from_client(client, bucket="docs", prefix="tenant-a")
    blob = _blob()

    store.put(blob, b"hello")

    assert store.get(blob.key) == (blob, b"hello")
    stored = client.objects[("docs", "tenant-a/reports/output.bin")]
    assert stored["Metadata"]["x20-blob"] == json.dumps(blob.to_dict(), sort_keys=True, separators=(",", ":"))


def test_s3_blob_store_rejects_digest_and_size_mismatches_before_upload() -> None:
    client = FakeS3()
    store = S3BlobStore.from_client(client, bucket="docs")

    with pytest.raises(ValueError, match="digest"):
        store.put(Blob("a", "sha256:wrong", 3), b"abc")
    with pytest.raises(ValueError, match="size"):
        store.put(Blob("b", f"sha256:{hashlib.sha256(b'abc').hexdigest()}", 4), b"abc")
    assert client.objects == {}


def test_s3_blob_store_rejects_mismatched_remote_payload() -> None:
    client = FakeS3()
    store = S3BlobStore.from_client(client, bucket="docs")
    blob = _blob()
    store.put(blob, b"hello")
    client.objects[("docs", blob.key)]["Body"] = b"tampered"

    with pytest.raises(ValueError, match=r"digest|size"):
        store.get(blob.key)


def test_s3_blob_store_compare_and_swap_uses_conditional_put() -> None:
    client = FakeS3()
    store = S3BlobStore.from_client(client, bucket="docs")
    first = _blob(b"first")
    second = _blob(b"second")

    assert store.put_conditional(first, b"first", expected_digest=None) is True
    assert store.put_conditional(second, b"second", expected_digest="sha256:wrong") is False
    assert store.compare_and_swap(first.key, first.digest, second, b"second") is True
    assert store.get(first.key) == (second, b"second")


def test_s3_blob_store_is_explicitly_unavailable_without_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "boto3", None)

    store = S3BlobStore.from_url("s3://docs/archive")

    assert store.available is False
    assert store.unavailable_reason
    with pytest.raises(RuntimeError, match="unavailable"):
        store.get("a")


@pytest.mark.parametrize("key", ["", "/absolute", "../escape", "a/../b", "a\\b"])
def test_s3_blob_store_rejects_unsafe_keys(key: str) -> None:
    store = S3BlobStore.from_client(FakeS3(), bucket="docs")
    blob = Blob(key or "safe", "sha256:" + hashlib.sha256(b"x").hexdigest(), 1)

    if key:
        with pytest.raises(ValueError, match="key"):
            store.put(blob, b"x")
    with pytest.raises(ValueError, match="key"):
        store.get(key)


def test_s3_blob_store_parses_s3_and_http_minio_urls() -> None:
    s3 = S3BlobStore.from_client(FakeS3(), bucket="docs")
    parsed = S3BlobStore.from_url("s3://bucket/prefix", client=FakeS3())
    minio = S3BlobStore.from_url("http://minio.local:9000/bucket/prefix", client=FakeS3())

    assert s3.bucket == "docs"
    assert parsed.bucket == "bucket" and parsed.prefix == "prefix" and parsed.endpoint_url is None
    assert minio.bucket == "bucket" and minio.prefix == "prefix" and minio.endpoint_url == "http://minio.local:9000"
