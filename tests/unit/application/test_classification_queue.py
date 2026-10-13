"""The one place the classification queue is read and confirmed."""

import json
from pathlib import Path

import pytest

from docs.application.classification_queue import (
    ClassificationQueueError,
    ClassificationQueueUnavailable,
    review_classification_queue,
)
from docs.application.ingest_names import CLASSIFICATION_QUEUE_NAME


def _queue(tmp_path: Path, payload) -> Path:
    path = tmp_path / "inbox" / CLASSIFICATION_QUEUE_NAME
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_queue_is_unavailable(tmp_path):
    with pytest.raises(ClassificationQueueUnavailable):
        review_classification_queue(tmp_path)


@pytest.mark.parametrize("shape", ["keyed", "list", "items"])
def test_confirmation_updates_only_the_requested_entry_in_every_queue_shape(tmp_path, shape):
    a = {"relative_path": "a/x.md", "confirmed_role": None}
    b = {"relative_path": "b/x.md", "confirmed_role": None}
    payload = {
        "keyed": {"schema": 1, "entries": {"a/x.md": a, "b/x.md": b}},
        "list": [a, b],
        "items": {"items": [a, b]},
    }[shape]
    path = _queue(tmp_path, payload)

    assert [e["confirmed_role"] for e in review_classification_queue(tmp_path)] == [None, None]
    entries = review_classification_queue(tmp_path, "b/x.md", "normative")

    assert [e["confirmed_role"] for e in entries] == [None, "normative"]
    assert "normative" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("file", "role"),
    [("a/x.md", "bogus"), ("a/x.md", None), (None, "evidence"), ("gone.md", "evidence")],
)
def test_invalid_confirmation_never_touches_the_queue(tmp_path, file, role):
    path = _queue(tmp_path, [{"relative_path": "a/x.md", "confirmed_role": None}])
    before = path.read_bytes()
    with pytest.raises(ClassificationQueueError):
        review_classification_queue(tmp_path, file, role)
    assert path.read_bytes() == before
