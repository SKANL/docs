import json

from docs.api.enterprise import encode_sse_event
from docs.api.http import APIError, normalize_error


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
