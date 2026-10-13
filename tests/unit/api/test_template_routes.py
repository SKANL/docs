"""S6.1: template administration, document summary/import and the read-only plugin contract."""

import base64
import hashlib
import json

from docs.api.auth import Principal
from docs.api.openapi import build_capability_catalog, build_openapi_document

NEW_COMMANDS = {
    "template show": ("GET", "/v2/templates/{template_name}", "documents:read"),
    "template use": ("POST", "/v2/templates/{template_name}/use", "documents:write"),
    "template init": ("POST", "/v2/templates", "documents:write"),
    "template create": ("POST", "/v2/templates", "documents:write"),
    "template validate": ("POST", "/v2/templates/{template_name}/validate", "documents:read"),
    "doc status": ("GET", "/v2/documents/{document_id}/summary", "documents:read"),
    "document import": ("POST", "/v2/documents/{document_id}/imports", "documents:write"),
}


def body(response):
    return json.loads(response.body)


def code(response):
    return body(response)["error"]["code"]


# -- show -----------------------------------------------------------------------
def test_show_returns_the_resolved_template_and_404_when_missing(api):
    response = api("GET", "/v2/templates/documento-generico")
    assert response.status == 200, response.body
    data = body(response)
    assert data["name"] == "documento-generico" and data["template"]["type"]
    missing = api("GET", "/v2/templates/nope")
    assert missing.status == 404 and code(missing) == "template_not_found"


# -- use ------------------------------------------------------------------------
def test_use_refuses_to_overwrite_without_force_and_overwrites_with_it(api):
    target = api.ws_root / "templates" / "documento-generico.json"
    target.write_text("{}", encoding="utf-8")
    refused = api("POST", "/v2/templates/documento-generico/use", {})
    assert refused.status == 409 and code(refused) == "template_exists"
    assert target.read_text(encoding="utf-8") == "{}"
    forced = api("POST", "/v2/templates/documento-generico/use", {"force": True})
    assert forced.status == 200, forced.body
    assert body(forced)["path"] == "templates/documento-generico.json"
    assert json.loads(target.read_text(encoding="utf-8"))["type"]


def test_use_copies_a_missing_builtin_and_rejects_unknown_ones(api):
    (api.ws_root / "templates" / "technical-report-srs.json").unlink()
    assert api("POST", "/v2/templates/technical-report-srs/use", {}).status == 200
    assert (api.ws_root / "templates" / "technical-report-srs.json").is_file()
    unknown = api("POST", "/v2/templates/not-builtin/use", {})
    assert unknown.status == 404 and code(unknown) == "builtin_template_not_found"
    assert api("POST", "/v2/templates/documento-generico/use", {"force": "yes"}).status == 400


# -- create / init --------------------------------------------------------------
def test_create_writes_a_skeleton_and_conflicts_on_repeat(api):
    created = api("POST", "/v2/templates", {"name": "nuevo"})
    assert created.status == 201, created.body
    assert body(created) == {"name": "nuevo", "path": "templates/nuevo.json"}
    assert json.loads((api.ws_root / "templates" / "nuevo.json").read_text(encoding="utf-8"))
    again = api("POST", "/v2/templates", {"name": "nuevo"})
    assert again.status == 409 and code(again) == "template_exists"


def test_create_rejects_traversal_and_unknown_fields(api):
    for name in ("../escape", "a/b", "..", "a\\b", ""):
        response = api("POST", "/v2/templates", {"name": name})
        assert response.status == 400, name
    assert not (api.ws_root / "escape.json").exists()
    assert api("POST", "/v2/templates", {"name": "x", "extra": 1}).status == 400


# -- validate -------------------------------------------------------------------
def test_validate_reports_structured_issues_for_an_invalid_template(api):
    api("POST", "/v2/templates", {"name": "borrador"})
    response = api("POST", "/v2/templates/borrador/validate", {})
    assert response.status == 200, response.body
    data = body(response)
    assert data["name"] == "borrador" and data["passed"] is False
    assert data["issues"] and {"severity", "message", "code"} <= data["issues"][0].keys()


def test_validate_never_fails_with_500_on_broken_json_or_non_objects(api):
    (api.ws_root / "templates" / "roto.json").write_text("{not json", encoding="utf-8")
    broken = api("POST", "/v2/templates/roto/validate", {})
    assert broken.status == 200 and body(broken)["passed"] is False
    assert body(broken)["issues"][0]["code"] == "template.json.invalid"
    (api.ws_root / "templates" / "lista.json").write_text("[]", encoding="utf-8")
    listed = api("POST", "/v2/templates/lista/validate", {})
    assert listed.status == 200 and body(listed)["passed"] is False


def test_validate_checks_an_uploaded_draft_without_writing_it(api):
    response = api("POST", "/v2/templates/borrador/validate", {"template": {"type": "borrador"}})
    assert response.status == 200 and body(response)["passed"] is False
    assert not (api.ws_root / "templates" / "borrador.json").exists()


def test_validate_missing_stored_template_is_404(api):
    response = api("POST", "/v2/templates/nope/validate", {})
    assert response.status == 404 and code(response) == "template_not_found"


def test_a_builtin_template_validates_cleanly(api):
    response = api("POST", "/v2/templates/documento-generico/validate", {})
    assert response.status == 200 and body(response)["passed"] is True, response.body


# -- plugins are read-only by design ---------------------------------------------
def test_plugin_write_methods_are_not_routed(api):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in ("/v2/plugins", "/v2/plugins/some-plugin"):
            assert api(method, path, {}).status in {404, 405}, (method, path)
    paths = build_openapi_document()["paths"]
    for path in ("/v2/plugins", "/v2/plugins/{plugin_id}"):
        assert set(paths[path]) - {"parameters"} == {"get"}
        assert "never executed" in paths[path]["get"]["description"].lower()


# -- document summary (doc status) ------------------------------------------------
def test_summary_equals_what_the_cli_service_reports(api):
    from docs.application.document_summary import build_document_summary

    deps = api.app._workspace_services_for(str(api.ws_root.resolve()))
    _, expected = build_document_summary(deps, "doc")
    response = api("GET", "/v2/documents/doc/summary")
    assert response.status == 200, response.body
    data = body(response)
    assert data["document_id"] == "doc"
    assert data["summary"] == json.loads(json.dumps(expected))
    assert api("GET", "/v2/documents/ghost/summary").status == 404


# -- document import -------------------------------------------------------------
def test_import_stores_a_hash_prefixed_copy_and_is_idempotent(api):
    content = b"# hello\n"
    payload = {"filename": "notes.md", "content_base64": base64.b64encode(content).decode()}
    digest = hashlib.sha256(content).hexdigest()
    first = api("POST", "/v2/documents/doc/imports", payload)
    assert first.status == 201, first.body
    data = body(first)
    assert data["path"] == f"documents/doc/inbox/{digest[:12]}-notes.md"
    assert data["sha256"] == digest and data["size"] == len(content) and data["deduplicated"] is False
    assert (api.ws_root / data["path"]).read_bytes() == content
    assert str(api.ws_root) not in first.body.decode()
    assert body(api("POST", "/v2/documents/doc/imports", payload))["deduplicated"] is True


def test_import_rejects_bad_input(api):
    assert api("POST", "/v2/documents/doc/imports", {"filename": "../x.md", "content_base64": "aGk="}).status == 400
    assert api("POST", "/v2/documents/doc/imports", {"filename": "x.md", "content_base64": "%%%"}).status == 400
    assert api("POST", "/v2/documents/ghost/imports", {"filename": "x.md", "content_base64": "aGk="}).status == 404


# -- scopes / contract ----------------------------------------------------------
def test_template_operations_enforce_their_scopes(api):
    headers = {"Authorization": "Bearer ok"}
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:read"}), "t1", "o1") if token == "ok" else None
    assert api("GET", "/v2/templates/documento-generico", headers=headers).status == 200
    assert api("POST", "/v2/templates/documento-generico/validate", {}, headers=headers).status == 200
    assert api("POST", "/v2/templates", {"name": "x"}, headers=headers).status == 403
    assert api("POST", "/v2/templates/documento-generico/use", {}, headers=headers).status == 403
    assert api("POST", "/v2/documents/doc/imports", {}, headers=headers).status == 403
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:write"}), "t1", "o1") if token == "ok" else None
    assert api("POST", "/v2/templates", {"name": "x"}, headers=headers).status == 201


def test_openapi_and_catalogue_declare_the_template_operations():
    document = build_openapi_document()
    paths = document["paths"]
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, path, scope) in NEW_COMMANDS.items():
        assert paths[path][method.lower()]["x-rbac-scopes"] == [scope], command
        assert catalogue[command]["status"] == "available", command
        assert catalogue[command]["route"] == f"{method} {path}", command
    parameters = {p["name"] for p in paths["/v2/templates/{template_name}"]["parameters"]}
    assert {"template_name", "workspace_id"} <= parameters
    for name in ("TemplateCreateRequest", "TemplateValidationResponse", "DocumentSummaryResponse", "DocumentImportRequest"):
        assert name in document["components"]["schemas"]


def test_doc_init_is_an_explicit_exclusion_with_a_reason():
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    entry = catalogue["doc init"]
    assert entry["status"] == "excluded" and entry["route"] is None and entry["scopes"] == []
    assert "current directory" in entry["reason"]
