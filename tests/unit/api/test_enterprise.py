import json
from pathlib import Path

import pytest

from docs.api.enterprise import (
    TokenBucketRateLimiter,
    WorkspacePathError,
    encode_sse_event,
    normalize_error,
    safe_workspace_path,
)
from docs.api.http import APIError


def test_token_bucket_rate_limiter_refills_and_returns_retry_metadata():
    now = [100.0]
    limiter = TokenBucketRateLimiter(rate=1.0, capacity=2, clock=lambda: now[0])

    assert limiter.allow("tenant-a").allowed
    assert limiter.allow("tenant-a").allowed
    blocked = limiter.allow("tenant-a")

    assert not blocked.allowed
    assert blocked.remaining == 0
    assert blocked.retry_after == 1.0

    now[0] += 1.0
    assert limiter.allow("tenant-a").allowed


def test_token_bucket_rate_limiter_keeps_buckets_isolated_by_key():
    limiter = TokenBucketRateLimiter(rate=1.0, capacity=1, clock=lambda: 0.0)

    assert limiter.allow("tenant-a").allowed
    assert not limiter.allow("tenant-a").allowed
    assert limiter.allow("tenant-b").allowed


def test_safe_workspace_path_rejects_traversal_and_absolute_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    assert safe_workspace_path(workspace, "reports/run.json") == workspace / "reports" / "run.json"
    with pytest.raises(WorkspacePathError):
        safe_workspace_path(workspace, "../outside.txt")
    with pytest.raises(WorkspacePathError):
        safe_workspace_path(workspace, str(tmp_path / "outside.txt"))


def test_safe_workspace_path_rejects_symlink_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")

    with pytest.raises(WorkspacePathError):
        safe_workspace_path(workspace, "linked/secret.txt")


def test_normalize_error_preserves_safe_details_and_hides_unexpected_message():
    assert normalize_error(APIError("invalid_request", "Bad request", details={"field": "name"})) == {
        "error": {
            "code": "invalid_request",
            "message": "Bad request",
            "details": {"field": "name"},
        }
    }
    assert normalize_error(RuntimeError("database password=secret")) == {
        "error": {
            "code": "internal_error",
            "message": "Internal server error",
            "details": {},
        }
    }


def test_encode_sse_event_is_deterministic_and_frames_multiline_data():
    encoded = encode_sse_event("update", {"id": 1, "ok": True}, event_id="evt-7", retry=5000)

    assert encoded == (
        'id: evt-7\n'
        'event: update\n'
        'retry: 5000\n'
        f'data: {json.dumps({"id": 1, "ok": True}, separators=(",", ":"), sort_keys=True)}\n\n'
    )
    assert encode_sse_event(None, "first\nsecond") == "data: first\ndata: second\n\n"
