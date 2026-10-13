"""Source, asset, and context routes delegate to the canonical services."""

import base64
import json
import threading

import pytest

from docs.api.application import X20Application
from docs.api.auth import Principal
from docs.api.http import APIError, Request
from docs.api.openapi import build_capability_catalog, build_openapi_document
from docs.application.imports import ImportError
from docs.application.workspaces import WorkspaceRegistry

NEW_COMMANDS = {
    "asset add": ("POST", "documents:write"),
    "asset list": ("GET", "documents:read"),
    "asset rm": ("DELETE", "documents:write"),
    "source ingest": ("POST", "documents:write"),
    "document ingest": ("POST", "documents:write"),
    "context elicit": ("POST", "documents:write"),
    "context ingest": ("POST", "documents:write"),
    "context show": ("GET", "documents:read"),
    "context rm": ("DELETE", "documents:write"),
    "document classify": ("POST", "documents:write"),
}


def body(response):
    return json.loads(response.body)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_asset_add_list_remove_roundtrip(api):
    added = api("POST", "/v2/documents/doc/assets", {
        "filename": "cover.docx", "content_base64": b64(b"PKdocx"), "name": "portada",
    })
    assert added.status == 201, added.body
    assert body(added)["name"] == "portada"
    assert body(added)["path"] == "assets/portada.docx"
    assert (api.doc_root / "assets" / "portada.docx").read_bytes() == b"PKdocx"

    listed = api("GET", "/v2/documents/doc/assets")
    assert body(listed)["items"] == [{"name": "portada"}]
    assert not list((api.ws_root / ".docs" / "staging").glob("*/*")), "staging must be cleaned"

    removed = api("DELETE", "/v2/documents/doc/assets/portada")
    assert removed.status == 200 and body(removed) == {"document_id": "doc", "removed": "portada"}
    assert body(api("GET", "/v2/documents/doc/assets"))["items"] == []
    assert api("DELETE", "/v2/documents/doc/assets/portada").status == 404


@pytest.mark.parametrize("filename", ["../evil.docx", "a/b.docx", "..\\evil.docx", "", ".."])
def test_asset_add_rejects_traversal_filenames(api, filename):
    response = api("POST", "/v2/documents/doc/assets", {"filename": filename, "content_base64": b64(b"x")})
    assert response.status == 400
    assert body(response)["error"]["code"] == "invalid_filename"
    assert not (api.doc_root / "assets").exists() or not list((api.doc_root / "assets").iterdir())


def test_asset_add_rejects_disallowed_type_bad_base64_and_unknown_fields(api):
    bad_type = api("POST", "/v2/documents/doc/assets", {"filename": "run.exe", "content_base64": b64(b"x")})
    assert bad_type.status == 400 and body(bad_type)["error"]["code"] == "invalid_asset"
    bad_b64 = api("POST", "/v2/documents/doc/assets", {"filename": "a.docx", "content_base64": "***"})
    assert bad_b64.status == 400 and body(bad_b64)["error"]["code"] == "invalid_base64"
    extra = api("POST", "/v2/documents/doc/assets", {
        "filename": "a.docx", "content_base64": b64(b"x"), "path": "/etc",
    })
    assert extra.status == 400 and body(extra)["error"]["code"] == "invalid_request"


def test_unknown_document_is_404_and_workspace_is_required(api):
    assert api("GET", "/v2/documents/ghost/assets").status == 404
    assert api("GET", "/v2/documents/ghost/context/tema").status == 404
    missing_ws = api.app.dispatch(Request("GET", "/v2/documents/doc/assets"))
    assert missing_ws.status == 400 and body(missing_ws)["error"]["code"] == "workspace_required"


def test_source_ingest_uploads_and_ingests_markdown(api):
    response = api("POST", "/v2/documents/doc/ingest", {"files": [
        {"filename": "notes.md", "content_base64": b64(b"# Notas\n\nContenido de prueba.\n")},
    ]})
    assert response.status == 200, response.body
    result = body(response)
    assert result["document_id"] == "doc"
    assert result["succeeded"] is True
    assert result["stages"][0]["name"] == "ingest-sources"
    assert result["uploaded"] and result["uploaded"][0]["filename"] == "notes.md"
    assert list((api.doc_root / "inbox").glob("*-notes.md"))


def test_source_ingest_degrades_on_corrupt_source_without_500(api):
    response = api("POST", "/v2/documents/doc/ingest", {"files": [
        {"filename": "broken.docx", "content_base64": b64(b"this is not a zip")},
    ]})
    assert response.status == 200, response.body
    result = body(response)
    stage = result["stages"][0]
    # The service owns the verdict; the route must surface the per-file status
    # (here "unsupported") instead of hiding it or failing with a 500.
    assert [f["status"] for f in stage["files"]] == ["unsupported"]
    assert result["uploaded"][0]["filename"] == "broken.docx"


def test_source_ingest_without_files_reports_current_inbox(api):
    response = api("POST", "/v2/documents/doc/ingest")
    assert response.status == 200
    assert body(response)["document_id"] == "doc"


def test_source_ingest_rejects_traversal_upload_name(api):
    response = api("POST", "/v2/documents/doc/ingest", {
        "files": [{"filename": "../x.md", "content_base64": b64(b"x")}],
    })
    assert response.status == 400 and body(response)["error"]["code"] == "invalid_filename"


def test_classification_lists_pending_and_confirms_through_the_shared_service(api):
    inbox = api.doc_root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    queue = inbox / "_classification-queue.json"
    entry = {"relative_path": "a/x.md", "confirmed_role": None}
    queue.write_text(json.dumps({"schema": 1, "entries": {"a/x.md": entry}}), encoding="utf-8")

    listed = api("GET", "/v2/documents/doc/classification")
    assert body(listed)["items"] == [entry]
    confirmed = api("POST", "/v2/documents/doc/classification", {
        "relative_path": "a/x.md", "confirmed_role": "normative",
    })
    assert confirmed.status == 200
    assert body(confirmed)["items"][0]["confirmed_role"] == "normative"
    assert json.loads(queue.read_text(encoding="utf-8"))["entries"]["a/x.md"]["confirmed_role"] == "normative"

    bad = api("POST", "/v2/documents/doc/classification", {"relative_path": "a/x.md", "confirmed_role": "bogus"})
    assert bad.status == 400
    unknown = api("POST", "/v2/documents/doc/classification", {"relative_path": "zz.md", "confirmed_role": "evidence"})
    assert unknown.status == 400


def test_classification_without_queue_is_404(api):
    response = api("GET", "/v2/documents/doc/classification")
    assert response.status == 404 and body(response)["error"]["code"] == "classification_unavailable"


def test_context_elicit_ingest_show_and_remove(api):
    elicited = api("POST", "/v2/documents/doc/context/requests", {"topic": "tema"})
    assert elicited.status == 200, elicited.body
    requests_path = api.doc_root / "context" / "_requests.md"
    assert requests_path.is_file()
    assert "tema" in body(elicited)["markdown"]

    assert api("GET", "/v2/documents/doc/context/tema").status == 404
    answered = body(elicited)["markdown"]
    empty, filled = "<<<\n\n>>>", "<<<\nUn informe sobre calidad.\n>>>"
    assert empty in answered
    requests_path.write_text(answered.replace(empty, filled), encoding="utf-8")

    ingested = api("POST", "/v2/documents/doc/context/ingest")
    assert ingested.status == 200, ingested.body
    assert body(ingested)["topics"] == ["tema"]

    shown = api("GET", "/v2/documents/doc/context/tema")
    assert shown.status == 200
    assert "Un informe sobre calidad." in body(shown)["content"]

    removed = api("DELETE", "/v2/documents/doc/context/tema")
    assert body(removed) == {"document_id": "doc", "removed": "tema"}
    assert api("GET", "/v2/documents/doc/context/tema").status == 404
    assert api("GET", "/v2/documents/doc/context/unknown-topic").status == 404


def test_context_ingest_without_requests_file_is_404(api):
    response = api("POST", "/v2/documents/doc/context/ingest")
    assert response.status == 404 and body(response)["error"]["code"] == "context_requests_missing"


@pytest.mark.parametrize(("method", "path", "payload", "needed"), [
    ("GET", "/v2/documents/doc/assets", None, "documents:read"),
    ("POST", "/v2/documents/doc/assets", {"filename": "a.docx", "content_base64": "eA=="}, "documents:write"),
    ("DELETE", "/v2/documents/doc/assets/a", None, "documents:write"),
    ("POST", "/v2/documents/doc/ingest", None, "documents:write"),
    ("POST", "/v2/documents/doc/context/requests", None, "documents:write"),
    ("POST", "/v2/documents/doc/context/ingest", None, "documents:write"),
    ("GET", "/v2/documents/doc/context/tema", None, "documents:read"),
    ("DELETE", "/v2/documents/doc/context/tema", None, "documents:write"),
])
def test_authoring_routes_deny_insufficient_scope(api, method, path, payload, needed):
    wrong = "documents:write" if needed == "documents:read" else "documents:read"
    api.app.auth = lambda token: Principal("ada", frozenset({wrong})) if token == "ok" else None
    response = api(method, path, payload, headers={"Authorization": "Bearer ok"})
    assert response.status == 403
    assert body(response)["error"]["code"] == "insufficient_scope"
    api.app.auth = lambda token: Principal("ada", frozenset({needed})) if token == "ok" else None
    assert api(method, path, payload, headers={"Authorization": "Bearer ok"}).status != 403


def test_openapi_declares_every_authoring_route_with_scopes():
    paths = build_openapi_document()["paths"]
    catalog = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, scope) in NEW_COMMANDS.items():
        capability = catalog[command]
        assert capability["status"] == "available", command
        route_method, route_path = capability["route"].split(" ", 1)
        assert route_method == method, command
        operation = paths[route_path][method.lower()]
        assert operation["x-rbac-scopes"] == [scope], command
        assert capability["scopes"] == [scope]
    document = build_openapi_document()
    ref = paths["/v2/documents/{document_id}/assets"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    add = document["components"]["schemas"][ref["$ref"].rsplit("/", 1)[1]]
    assert {"filename", "content_base64"} <= set(add["required"]) and add["additionalProperties"] is False
    item = paths["/v2/documents/{document_id}/context/{topic_id}"]
    assert {"document_id", "topic_id", "workspace_id"} <= {p["name"] for p in item["parameters"]}


def test_routes_report_unavailable_when_services_factory_missing(tmp_path, stores):
    registry = WorkspaceRegistry(tmp_path / "r.json")
    ws = registry.create("W", tmp_path / "w")
    app = X20Application(
        **stores, workspace_registry=registry,
    )
    response = app.dispatch(Request("GET", f"/v2/documents/doc/assets?workspace_id={ws['id']}"))
    assert response.status == 501  # 5xx codes are masked by the error normalizer


# -- S2.1 advisory findings ---------------------------------------------------
@pytest.mark.parametrize("content", [
    "{not json", "5", '"text"', "null", "[1, 2]", '{"entries": {"a/x.md": 3}}', '{"items": [1]}',
])
def test_corrupt_classification_queue_is_a_structured_4xx(api, content):
    inbox = api.doc_root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "_classification-queue.json").write_text(content, encoding="utf-8")
    for response in (
        api("GET", "/v2/documents/doc/classification"),
        api("POST", "/v2/documents/doc/classification", {"relative_path": "a/x.md", "confirmed_role": "evidence"}),
    ):
        assert response.status == 400, (content, response.body)
        assert body(response)["error"]["code"] == "invalid_classification"


def test_ingest_resolves_context_before_writing_any_upload(api, monkeypatch):
    def unresolvable(deps, document_id):
        raise APIError("document_unresolvable", "broken", 400)

    monkeypatch.setattr(api.app._authoring, "_resolve", unresolvable)
    response = api("POST", "/v2/documents/doc/ingest", {"files": [{"filename": "a.md", "content_base64": b64(b"# A\n")}]})
    assert response.status == 400
    assert not list((api.doc_root / "inbox").glob("*a.md")) if (api.doc_root / "inbox").exists() else True


def test_ingest_removes_this_requests_uploads_when_a_later_upload_fails(api, monkeypatch):
    service = api.app._authoring._import
    real, calls = service.import_bytes, []

    def flaky(*args, **kwargs):
        calls.append(args[1])
        if len(calls) == 2:
            raise ImportError("source_too_large")
        return real(*args, **kwargs)

    monkeypatch.setattr(service, "import_bytes", flaky)
    response = api("POST", "/v2/documents/doc/ingest", {"files": [
        {"filename": "a.md", "content_base64": b64(b"# A\n")},
        {"filename": "b.md", "content_base64": b64(b"# B\n")},
    ]})
    assert response.status == 400 and body(response)["error"]["code"] == "source_too_large"
    assert not list((api.doc_root / "inbox").glob("*-a.md"))


def test_ingest_pipeline_failure_is_a_structured_error(api):
    deps = api.app._workspace_services_for(str(api.ws_root.resolve()))

    def boom():
        raise ValueError("pipeline exploded")

    deps.create_source_pipeline = boom
    response = api("POST", "/v2/documents/doc/ingest")
    assert response.status == 400 and body(response)["error"]["code"] == "ingest_failed"


def test_remove_context_topic_without_saved_content_is_idempotent_like_the_cli(api):
    api("POST", "/v2/documents/doc/context/requests", {"topic": "tema"})
    response = api("DELETE", "/v2/documents/doc/context/tema")
    assert response.status == 200 and body(response)["removed"] == "tema"
    assert api("DELETE", "/v2/documents/doc/context/unknown-topic").status == 404


def test_remove_asset_honours_the_kind_parameter(api):
    api("POST", "/v2/documents/doc/assets", {"filename": "cover.docx", "content_base64": b64(b"PKdocx")})
    bad = api("DELETE", "/v2/documents/doc/assets/cover?kind=bogus")
    assert bad.status == 400 and body(bad)["error"]["code"] == "invalid_asset_kind"
    assert (api.doc_root / "assets" / "cover.docx").exists()
    assert api("DELETE", "/v2/documents/doc/assets/cover?kind=docx").status == 200


def test_unexpected_factory_failure_is_a_503_structured_error(tmp_path, stores):
    registry = WorkspaceRegistry(tmp_path / "r.json")
    ws = registry.create("W", tmp_path / "w")

    def broken(root):
        raise RuntimeError("compose failed")

    app = X20Application(**stores, workspace_registry=registry, workspace_services_factory=broken)
    response = app.dispatch(Request("GET", f"/v2/documents/doc/assets?workspace_id={ws['id']}"))
    assert response.status == 503


def test_a_slow_factory_for_one_root_does_not_block_another(tmp_path, stores):
    registry = WorkspaceRegistry(tmp_path / "r.json")
    started, release = threading.Event(), threading.Event()

    def factory(root):
        if root.endswith("slow"):
            started.set()
            assert release.wait(10)
        return object()

    app = X20Application(**stores, workspace_registry=registry, workspace_services_factory=factory)
    slow = threading.Thread(target=app._workspace_services_for, args=(str(tmp_path / "slow"),))
    slow.start()
    try:
        assert started.wait(5)
        done = threading.Event()
        threading.Thread(target=lambda: (app._workspace_services_for(str(tmp_path / "fast")), done.set())).start()
        assert done.wait(3), "fast root must not wait for the slow factory"
    finally:
        release.set()
        slow.join(5)
