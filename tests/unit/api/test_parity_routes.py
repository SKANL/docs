"""Route-level API proofs for the CLI/API/UI parity matrix (real sidecar composition, in-process dispatch)."""

import json
from pathlib import Path

import pytest

from docs.api.http import Request
from docs.domain.runtime_records import Passport, Run
from docs.sidecar import SidecarConfig, build_application


@pytest.fixture(autouse=True)
def _canonical_workspace_root(canonical_workspace_root: Path) -> None:
    """Opt this module into canonical temporary workspaces."""


@pytest.fixture
def studio(tmp_path):
    application = build_application(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path)).application
    wid = application.workspace_registry.list()[0]["id"]

    def call(method, path, payload=None):
        sep = "&" if "?" in path else "?"
        response = application.dispatch(Request(method, f"{path}{sep}workspace_id={wid}", body=payload))
        return response.status, json.loads(response.body or b"{}")

    status, _ = call("POST", "/v2/documents", {
        "workspace_id": wid, "document_id": "doc", "template": "documento-generico", "title": "Doc",
    })
    assert status == 201
    call.app, call.wid = application, wid
    return call


def test_context_set_persists_and_is_readable_via_context_status(studio):
    def topic(name):
        return next(t for t in studio("GET", "/v2/documents/doc/context")[1]["topics"] if t["id"] == name)

    assert topic("tema")["exists"] is False
    status, saved = studio("POST", "/v2/documents/doc/context", {"topic": "tema", "value": "contenido real"})
    assert status == 200 and (saved["document_id"], saved["topic"]) == ("doc", "tema")
    assert "contenido real" in Path(saved["path"]).read_text(encoding="utf-8")
    assert topic("tema")["exists"] is True and topic("tema")["missing"] == []

    status, field = studio("POST", "/v2/documents/doc/context", {"topic": "documento", "field": "titulo", "value": "Mi titulo"})
    assert status == 200 and field["field"] == "titulo"
    assert "Título" not in topic("documento")["missing"]
    assert studio("POST", "/v2/documents/doc/context", {"topic": "documento", "field": "nope", "value": "x"})[0] == 400


@pytest.mark.parametrize("body", [{}, {"topic": "  ", "value": "x"}, {"topic": "t"}, {"topic": "t", "value": 3}])
def test_context_set_rejects_an_invalid_body(studio, body):
    status, payload = studio("POST", "/v2/documents/doc/context", body)
    assert status == 400 and payload["error"]["code"] == "invalid_request"


def test_document_prepare_returns_its_synchronous_result(studio):
    status, report = studio("POST", "/v2/documents/doc/prepare", {"workspace_id": studio.wid})
    assert status == 200, report
    assert isinstance(report["succeeded"], bool)
    assert ("scaffolds" in report) == report["succeeded"]  # section scaffolds are written only on success
    if report["succeeded"]:
        assert report["scaffolds"] and all(Path(p).is_file() for p in report["scaffolds"])


@pytest.mark.parametrize(("action", "pipeline"), [("build", "document"), ("verify", "document-verify")])
def test_document_build_and_verify_queue_a_run_with_the_requested_payload(studio, action, pipeline):
    status, run = studio("POST", f"/v2/documents/doc/{action}", {
        "workspace_id": studio.wid, "format": "html", "policy": "strict",
    })
    assert status == 202 and run["id"] and run["status"] == "queued", run
    assert run["payload"]["document_id"] == "doc"
    assert (run["payload"]["format"], run["payload"]["policy"], run["payload"]["pipeline_id"]) == ("html", "strict", pipeline)
    assert studio("GET", f"/v2/runs/{run['id']}")[1]["id"] == run["id"]
    assert studio("POST", f"/v2/documents/ghost/{action}", {"workspace_id": studio.wid})[0] == 404


def test_workspace_list_shape_and_ordering(studio):
    created = studio("POST", "/v2/workspaces", {"name": "Second"})[1]
    status, listed = studio("GET", "/v2/workspaces")
    assert status == 200 and listed["next_cursor"] is None
    assert all(set(item) == {"id", "name", "root"} for item in listed["items"])
    ids = [item["id"] for item in listed["items"]]
    assert ids == [studio.wid, created["id"]] and "active" not in listed


def test_workspace_rename_is_persisted_and_conflicts_are_409(studio):
    other = studio("POST", "/v2/workspaces", {"name": "Other"})[1]
    status, renamed = studio("PATCH", f"/v2/workspaces/{other['id']}", {"name": "Renamed"})
    assert status == 200 and renamed == {**other, "name": "Renamed"}
    assert studio("GET", f"/v2/workspaces/{other['id']}")[1]["name"] == "Renamed"
    assert any(i["name"] == "Renamed" for i in studio("GET", "/v2/workspaces")[1]["items"])
    assert studio("PATCH", f"/v2/workspaces/{other['id']}", {"name": "Local workspace"})[0] == 409
    assert studio("PATCH", "/v2/workspaces/ghost", {"name": "x"})[0] == 404


def test_workspace_delete_removes_it_then_404s(studio):
    other = studio("POST", "/v2/workspaces", {"name": "Doomed"})[1]
    assert studio("DELETE", f"/v2/workspaces/{other['id']}") == (200, {"deleted": other["id"]})
    assert studio("GET", f"/v2/workspaces/{other['id']}")[0] == 404
    assert other["id"] not in [i["id"] for i in studio("GET", "/v2/workspaces")[1]["items"]]
    assert studio("DELETE", f"/v2/workspaces/{other['id']}")[0] == 404


def test_document_status_reports_the_status_contract_fields(studio):
    status, doc = studio("GET", "/v2/documents/doc/status")
    assert status == 200
    assert (doc["document_id"], doc["workspace_id"]) == ("doc", studio.wid)
    assert {"succeeded", "manifest", "capabilities", "execution", "provenance",
            "unsupported_stages", "publication_blockers"} <= doc.keys()
    assert doc["publication_blockers"] == [] and doc["unsupported_stages"] == []  # nothing has run yet
    assert studio("GET", "/v2/documents/ghost/status")[0] == 404


def test_document_passport_payload_equals_the_stored_passport(studio):
    app = studio.app
    app.run_store.put(Run("run-p", payload={"workspace_id": studio.wid}))
    stored = Passport("run-p", ({"stage": "prepare", "ok": True},))
    app.passport_store.put(stored)
    status, payload = studio("GET", "/v2/runs/run-p/passport")
    assert status == 200 and payload == stored.to_dict()
    app.run_store.put(Run("run-q", payload={"workspace_id": studio.wid}))
    assert studio("GET", "/v2/runs/run-q/passport")[0] == 404
