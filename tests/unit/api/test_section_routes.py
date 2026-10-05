"""Section authoring routes (build/pack/review/stamp/revise) call the canonical services."""

import json

import pytest

from docs.api.auth import Principal
from docs.api.http import Request
from docs.api.openapi import build_capability_catalog, build_openapi_document

SECTION = "introduccion"
NEW_COMMANDS = {
    "build-section": ("POST", "documents:write"),
    "pack-context": ("POST", "documents:write"),
    "review-section": ("POST", "documents:write"),
    "review-document": ("POST", "documents:write"),
    "stamp-section": ("POST", "documents:write"),
    "doc revise": ("POST", "documents:write"),
}


def body(response):
    return json.loads(response.body)


def build(api, section=SECTION):
    return api("POST", f"/v2/documents/doc/sections/{section}/build")


def test_build_section_writes_scaffold_and_returns_relative_path(api):
    response = build(api)
    assert response.status == 200, response.body
    data = body(response)
    assert data["document_id"] == "doc" and data["section_id"] == SECTION
    assert data["proposal"] is False and not data["path"].startswith(("/", "C:"))
    assert (api.doc_root / data["path"]).is_file()


def test_build_section_preserves_authored_content_and_proposes_instead(api):
    path = api.doc_root / body(build(api))["path"]
    authored = path.read_text(encoding="utf-8").replace("PENDIENTE", "Texto autoral intocable.")
    path.write_text(authored, encoding="utf-8")
    again = body(build(api))
    assert again["proposal"] is True and "_proposals" in again["path"]
    assert path.read_text(encoding="utf-8") == authored


def test_build_unknown_section_is_404(api):
    response = build(api, "nope")
    assert response.status == 404 and body(response)["error"]["code"] == "section_not_found"


def test_pack_context_single_all_and_document(api):
    single = body(api("POST", "/v2/documents/doc/context-pack", {"target": SECTION}))
    assert single["target"] == SECTION and len(single["paths"]) == 1
    assert (api.doc_root / single["paths"][0]).is_file()
    everything = body(api("POST", "/v2/documents/doc/context-pack", {"target": "all"}))
    assert len(everything["paths"]) == 6  # five sections + the document pack
    only_doc = body(api("POST", "/v2/documents/doc/context-pack", {"target": "document"}))
    assert len(only_doc["paths"]) == 1
    missing = api("POST", "/v2/documents/doc/context-pack", {"target": "nope"})
    assert missing.status == 404 and body(missing)["error"]["code"] == "section_not_found"
    assert api("POST", "/v2/documents/doc/context-pack", {}).status == 400


def test_review_section_returns_structured_findings(api):
    build(api)
    response = api("POST", f"/v2/documents/doc/sections/{SECTION}/review", {"strict": True})
    assert response.status == 200, response.body
    data = body(response)
    assert data["section_id"] == SECTION and isinstance(data["passed"], bool)
    assert data["findings"], "scaffold still has pending content"
    finding = data["findings"][0]
    assert {"severity", "message", "code", "dimension"} <= set(finding)
    assert data["passed"] == (not any(f["severity"] == "error" for f in data["findings"]))


def test_review_section_missing_is_404(api):
    response = api("POST", f"/v2/documents/doc/sections/{SECTION}/review")
    assert response.status == 404  # never built
    assert api("POST", "/v2/documents/doc/sections/nope/review").status == 404


def test_review_document_filters_dimensions(api):
    build(api)
    full = body(api("POST", "/v2/documents/doc/review", {}))
    assert full["section_id"] is None and "findings" in full
    only = body(api("POST", "/v2/documents/doc/review", {"dimensions": ["structural"]}))
    assert {f["dimension"] for f in only["findings"]} <= {"structural"}
    bad = api("POST", "/v2/documents/doc/review", {"dimensions": ["bogus"]})
    assert bad.status == 400 and body(bad)["error"]["code"] == "invalid_request"


def test_stamp_section_records_provenance_from_the_request(api):
    build(api)
    response = api("POST", f"/v2/documents/doc/sections/{SECTION}/stamp", {"by": "ada", "model": "opus"})
    assert response.status == 200, response.body
    data = body(response)
    assert data["authored_by"] == "ada" and data["model"] == "opus" and data["stamped_at"]
    raw = (api.doc_root / data["path"]).read_text(encoding="utf-8")
    assert "ada" in raw and "opus" in raw
    assert api("POST", f"/v2/documents/doc/sections/{SECTION}/stamp", {}).status == 400
    assert api("POST", f"/v2/documents/doc/sections/{SECTION}/stamp", {"by": ""}).status == 400
    assert api("POST", "/v2/documents/doc/sections/nope/stamp", {"by": "ada"}).status == 404


def test_revision_uses_the_canonical_flow_and_records_a_diff(api):
    build(api)
    response = api("POST", "/v2/documents/doc/revisions", {
        "target_id": SECTION, "new_body": "## Introduccion\n\nTexto revisado.\n", "request": "ajuste",
    })
    assert response.status == 201, response.body
    data = body(response)
    assert data["target_id"] == SECTION and "Texto revisado" in data["diff"]
    assert not data["diff_path"].startswith(("/", "C:")) and (api.doc_root / data["diff_path"]).is_file()
    log = json.loads((api.doc_root / "sections" / "_revisions" / "revision-log.json").read_text(encoding="utf-8"))
    assert "ajuste" in json.dumps(log)
    assert api("POST", "/v2/documents/ghost/revisions", {"target_id": SECTION, "new_body": "x"}).status == 404
    structural = api("POST", "/v2/documents/doc/revisions", {"target_id": "no-such", "new_body": "x"})
    assert structural.status == 400 and body(structural)["error"]["code"] == "invalid_revision"
    assert api("POST", "/v2/documents/doc/revisions", {"target_id": SECTION}).status == 400


@pytest.mark.parametrize(("path", "payload"), [
    (f"/v2/documents/doc/sections/{SECTION}/build", None),
    ("/v2/documents/doc/context-pack", {"target": "document"}),
    (f"/v2/documents/doc/sections/{SECTION}/review", None),
    ("/v2/documents/doc/review", None),
    (f"/v2/documents/doc/sections/{SECTION}/stamp", {"by": "ada"}),
    ("/v2/documents/doc/revisions", {"target_id": SECTION, "new_body": "x"}),
])
def test_section_routes_require_write_scope(api, path, payload):
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:read"})) if token == "ok" else None
    response = api("POST", path, payload, headers={"Authorization": "Bearer ok"})
    assert response.status == 403 and body(response)["error"]["code"] == "insufficient_scope"
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:write"})) if token == "ok" else None
    assert api("POST", path, payload, headers={"Authorization": "Bearer ok"}).status != 403


def test_catalogue_and_openapi_declare_every_section_operation():
    paths = build_openapi_document()["paths"]
    catalog = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, scope) in NEW_COMMANDS.items():
        capability = catalog[command]
        assert capability["status"] == "available", command
        route_method, route_path = capability["route"].split(" ", 1)
        assert route_method == method
        assert paths[route_path][method.lower()]["x-rbac-scopes"] == [scope], command


def test_unknown_document_is_404_for_section_routes(api):
    assert api("POST", f"/v2/documents/ghost/sections/{SECTION}/build").status == 404
    assert api("POST", "/v2/documents/ghost/review").status == 404
    missing_ws = api.app.dispatch(Request("POST", f"/v2/documents/doc/sections/{SECTION}/build"))
    assert missing_ws.status == 400
