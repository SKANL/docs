"""S6.2: specialist tool operations (collection, rules, ledger, DOCX, translation, diagnostics, issue codes)."""

import base64
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from docs.api.auth import Principal
from docs.api.openapi import build_capability_catalog, build_openapi_document
from docs.application.imports import ImportError
from docs.application.templates import builtin_names
from docs.application.translate import TranslateReport, UntranslatablePdfError
from docs.domain.review import Issue, ReviewResult
from docs.domain.runtime_records import Artifact, Run
from docs.domain.tool_capability import ToolUnavailableError

NEW_COMMANDS = {
    "collect-sources": ("POST", "/v2/documents/{document_id}/collect-sources", "documents:write"),
    "collect-issues": ("POST", "/v2/documents/{document_id}/collect-issues", "documents:write"),
    "collect-code-evidence": ("POST", "/v2/documents/{document_id}/collect-code-evidence", "documents:write"),
    "build-rules": ("POST", "/v2/documents/{document_id}/build-rules", "documents:write"),
    "build-ledger": ("POST", "/v2/documents/{document_id}/build-ledger", "documents:write"),
    "review-rules": ("POST", "/v2/documents/{document_id}/review-rules", "documents:read"),
    "build-docx": ("POST", "/v2/documents/{document_id}/build-docx", "documents:write"),
    "format-audit-docx": ("POST", "/v2/documents/{document_id}/format-audit-docx", "documents:read"),
    "translate": ("POST", "/v2/translations", "documents:write"),
    "doctor": ("GET", "/v2/diagnostics", "documents:read"),
    "explain": ("GET", "/v2/issue-codes/{code}", "documents:read"),
}


class MemRuns:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.id] = item

    def get(self, key):
        return self.items.get(key)

    def list(self):
        return list(self.items.values())


class MemArtifacts:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.id] = item

    def get(self, key):
        return self.items.get(key)

    def list(self):
        return list(self.items.values())

    def list_for_run(self, run_id):
        return [a for a in self.items.values() if a.run_id == run_id]


@pytest.fixture
def stores(stores):
    return {**stores, "run_store": MemRuns(), "artifact_store": MemArtifacts()}


def body(response):
    return json.loads(response.body)


def code(response):
    return body(response)["error"]["code"]


def deps_of(api):
    return api.app._workspace_services_for(str(api.ws_root.resolve()))


def seed_artifact(api, path: Path, artifact_id="a1", run_id="r1"):
    api.app.run_store.put(Run(run_id, "succeeded", {
        "workspace_id": api.wid, "document_id": "doc", "tenant_id": "t1", "organization_id": "o1",
    }, ""))
    api.app.artifact_store.put(Artifact(
        artifact_id, run_id, "artifact", "0" * 64, "",
        {"value": {"path": str(path)}, "source": "pipeline", "materialized": path.is_file()},
    ))


# -- template catalogue -----------------------------------------------------------
def test_template_catalog_lists_every_builtin_and_whether_it_is_installed(api):
    (api.ws_root / "templates" / "technical-report-srs.json").unlink()
    response = api("GET", "/v2/template-catalog")
    assert response.status == 200, response.body
    items = {item["name"]: item for item in body(response)["items"]}
    assert sorted(items) == builtin_names()
    assert items["documento-generico"]["installed"] is True
    assert items["technical-report-srs"]["installed"] is False
    assert str(api.ws_root) not in response.body.decode()


# -- explain ----------------------------------------------------------------------
def test_issue_code_explains_a_known_code_and_404s_an_unknown_one(api):
    response = api("GET", "/v2/issue-codes/apa.required")
    assert response.status == 200, response.body
    data = body(response)
    assert data["code"] == "apa.required" and data["family"] == "apa"
    assert data["family_description"] and data["meaning"] and data["fix"]
    unknown = api("GET", "/v2/issue-codes/nope.nothing")
    assert unknown.status == 404 and code(unknown) == "issue_code_not_found"


# -- doctor / diagnostics ---------------------------------------------------------
def test_diagnostics_return_structured_checks(api):
    response = api("GET", "/v2/diagnostics")
    assert response.status == 200, response.body
    data = body(response)
    assert data["document_id"] == "doc" and isinstance(data["passed"], bool)
    assert {"name", "status", "required", "detail", "version"} <= data["checks"][0].keys()
    assert {c["status"] for c in data["checks"]} <= {"ok", "warn", "error", "unavailable"}
    assert "capabilities" in data and "capability_diagnostics" in data
    assert str(api.ws_root) not in response.body.decode()


def test_diagnostics_show_a_missing_tool_as_unavailable_not_a_failure(api, monkeypatch):
    deps = deps_of(api)
    monkeypatch.setattr(deps.doctor.tool_resolver, "resolve_libreoffice", lambda paths=None: None)
    response = api("GET", "/v2/diagnostics")
    assert response.status == 200, response.body
    checks = {c["name"]: c for c in body(response)["checks"]}
    assert checks["libreoffice"]["status"] == "unavailable"
    assert checks["libreoffice"]["required"] is False


def test_diagnostics_report_the_tool_version_when_present(api, monkeypatch):
    deps = deps_of(api)
    monkeypatch.setattr(deps.doctor.tool_resolver, "resolve_pandoc", lambda paths=None: "/bin/pandoc")
    monkeypatch.setattr(deps.doctor.tool_resolver, "tool_version", lambda exe: "pandoc 3.1.3")
    checks = {c["name"]: c for c in body(api("GET", "/v2/diagnostics"))["checks"]}
    assert checks["pandoc"]["status"] == "ok" and checks["pandoc"]["version"] == "3.1.3"


def test_diagnostics_need_a_resolvable_document(api):
    assert api("GET", "/v2/diagnostics?document_id=ghost").status == 404
    assert api("GET", "/v2/diagnostics?document_id=../x").status == 400


# -- collect-* --------------------------------------------------------------------
def test_collect_sources_writes_the_manifest(api):
    response = api("POST", "/v2/documents/doc/collect-sources", {})
    assert response.status == 200, response.body
    data = body(response)
    assert data["degraded"] is False and data["message"] is None
    assert (api.ws_root / data["path"]).is_file()
    assert str(api.ws_root) not in response.body.decode()
    assert api("POST", "/v2/documents/ghost/collect-sources", {}).status == 404


def test_collect_code_evidence_defaults_to_the_workspace_and_rejects_other_roots(api, tmp_path):
    ok = api("POST", "/v2/documents/doc/collect-code-evidence", {})
    assert ok.status == 200, ok.body
    assert (api.ws_root / body(ok)["path"]).is_file()
    for evil in (str(tmp_path), "..", "../elsewhere", "C:\\Windows", "/etc"):
        refused = api("POST", "/v2/documents/doc/collect-code-evidence", {"repo_root": evil})
        assert refused.status == 400 and code(refused) == "repo_root_not_permitted", evil


def test_collect_issues_rejects_other_roots(api, tmp_path):
    refused = api("POST", "/v2/documents/doc/collect-issues", {"repo_root": str(tmp_path)})
    assert refused.status == 400 and code(refused) == "repo_root_not_permitted"


def test_collect_issues_without_gh_is_a_degraded_result_not_a_500(api, monkeypatch):
    deps = deps_of(api)
    monkeypatch.setattr(deps.collection.source_repository, "find_executable", lambda name: None)
    response = api("POST", "/v2/documents/doc/collect-issues", {})
    assert response.status == 200, response.body
    data = body(response)
    assert data["degraded"] is True and data["path"] is None and "gh" in data["message"]


def test_collect_issues_passes_the_workspace_root_as_default_repo_root(api, monkeypatch):
    calls = []
    deps = deps_of(api)

    class FakeCollection:
        def collect_issues(self, config, repo_root):
            calls.append(Path(repo_root))
            target = Path(config["paths"]["issues_manifest"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            return target

    monkeypatch.setattr(deps, "collection", FakeCollection())
    response = api("POST", "/v2/documents/doc/collect-issues", {"repo_root": "."})
    assert response.status == 200, response.body
    assert calls == [api.ws_root.resolve()]
    assert body(response)["degraded"] is False


# -- rules / ledger ---------------------------------------------------------------
def test_build_rules_then_review_rules_are_structured(api):
    before = api("POST", "/v2/documents/doc/review-rules", {})
    assert before.status == 200, before.body
    assert body(before)["strict"] is False and isinstance(body(before)["issues"], list)
    built = api("POST", "/v2/documents/doc/build-rules", {})
    assert built.status == 200, built.body
    assert (api.ws_root / body(built)["path"]).is_file()
    after = body(api("POST", "/v2/documents/doc/review-rules", {"strict": True}))
    assert after["strict"] is True and isinstance(after["passed"], bool)


def test_build_ledger_writes_the_ledger_under_the_workspace(api):
    response = api("POST", "/v2/documents/doc/build-ledger", {})
    assert response.status == 200, response.body
    path = api.ws_root / body(response)["path"]
    assert path.is_file() and path.read_text(encoding="utf-8").startswith("# Fact Ledger")
    assert str(api.ws_root) not in response.body.decode()


# -- build-docx -------------------------------------------------------------------
class FakeDocx:
    def __init__(self, *, fail=None):
        self.calls, self.fail = [], fail

    def build(self, doc_id, config, output=None):
        self.calls.append(output)
        if self.fail:
            raise self.fail
        target = output or Path(config["paths"]["output_draft_dir"]) / "doc-draft.docx"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"docx")
        return target


def test_build_docx_defaults_to_the_draft_dir_and_accepts_a_workspace_output(api, monkeypatch):
    deps = deps_of(api)
    fake = FakeDocx()
    monkeypatch.setattr(deps, "docx", fake)
    default = api("POST", "/v2/documents/doc/build-docx", {})
    assert default.status == 200, default.body
    assert body(default)["built"] is True and body(default)["docx"].endswith("doc-draft.docx")
    assert fake.calls == [None]
    custom = api("POST", "/v2/documents/doc/build-docx", {"output": "output/custom/out.docx"})
    assert body(custom)["docx"] == "output/custom/out.docx"
    assert (api.ws_root / "output" / "custom" / "out.docx").is_file()


def test_build_docx_rejects_outputs_outside_the_workspace(api, monkeypatch, tmp_path):
    fake = FakeDocx()
    monkeypatch.setattr(deps_of(api), "docx", fake)
    for evil in (str(tmp_path / "x.docx"), "../x.docx", "output/../../x.docx", "C:\\x.docx", "output/x.txt"):
        refused = api("POST", "/v2/documents/doc/build-docx", {"output": evil})
        assert refused.status == 400 and code(refused) == "output_not_permitted", evil
    assert fake.calls == []


def test_build_docx_toolchain_failure_is_a_structured_result(api, monkeypatch):
    monkeypatch.setattr(deps_of(api), "docx", FakeDocx(fail=ToolUnavailableError("Pandoc no está disponible")))
    response = api("POST", "/v2/documents/doc/build-docx", {})
    assert response.status == 200, response.body
    data = body(response)
    assert data["built"] is False and data["docx"] is None and "Pandoc" in data["message"]


# -- format-audit-docx ------------------------------------------------------------
class FakeAudit:
    def __init__(self):
        self.calls = []

    def audit_format(self, docx, config, strict=False):
        self.calls.append((Path(docx), strict))
        if strict:
            return ReviewResult([Issue("error", "margins differ", code="structure.margin")])
        return ReviewResult([Issue("warning", "margins differ", code="structure.margin")])


def test_format_audit_surfaces_strict_failure_and_non_strict_pass(api, monkeypatch, tmp_path):
    docx = api.ws_root / "output" / "qa" / "book.docx"
    docx.parent.mkdir(parents=True)
    docx.write_bytes(b"x")
    seed_artifact(api, docx)
    fake = FakeAudit()
    monkeypatch.setattr(deps_of(api), "format_audit", fake)
    loose = api("POST", "/v2/documents/doc/format-audit-docx", {"artifact_id": "a1"})
    assert loose.status == 200, loose.body
    assert body(loose)["passed"] is True and body(loose)["issues"][0]["code"] == "structure.margin"
    strict = body(api("POST", "/v2/documents/doc/format-audit-docx", {"artifact_id": "a1", "strict": True}))
    assert strict["passed"] is False and strict["strict"] is True and strict["docx"] == "output/qa/book.docx"
    assert "margins differ" in strict["report"]
    assert fake.calls == [(docx.resolve(), False), (docx.resolve(), True)]
    assert str(api.ws_root) not in json.dumps(strict)


def test_format_audit_needs_a_built_docx_and_rejects_escapes(api, monkeypatch, tmp_path):
    monkeypatch.setattr(deps_of(api), "format_audit", FakeAudit())
    missing = api("POST", "/v2/documents/doc/format-audit-docx", {})
    assert missing.status == 409 and code(missing) == "docx_unavailable"
    outside = tmp_path / "evil.docx"
    outside.write_bytes(b"x")
    seed_artifact(api, outside, "evil")
    assert api("POST", "/v2/documents/doc/format-audit-docx", {"artifact_id": "evil"}).status == 400
    assert api("POST", "/v2/documents/doc/format-audit-docx", {"artifact_id": "ghost"}).status == 404
    not_docx = api.ws_root / "x.pdf"
    not_docx.write_bytes(b"x")
    seed_artifact(api, not_docx, "pdf")
    assert api("POST", "/v2/documents/doc/format-audit-docx", {"artifact_id": "pdf"}).status == 400


# -- translate --------------------------------------------------------------------
class FakeTranslator:
    pending_count = 0

    def flush_pending(self, source_lang, target_lang):
        return None


class FakeTranslateService:
    def __init__(self, *, error=None):
        self.calls, self.error = [], error

    def translate_pdf(self, src, out, target_lang, source_lang="auto"):
        self.calls.append((Path(src), Path(out), target_lang, source_lang))
        if self.error:
            raise self.error
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"%PDF translated")
        return TranslateReport(output_path=out, blocks_total=2, blocks_translated=2)


def install_translate(api, monkeypatch, service):
    deps = deps_of(api)
    monkeypatch.setattr(deps, "build_translate_service", lambda memory_dir, pending: (service, FakeTranslator()))


def pdf_upload(name="book.pdf"):
    return {"filename": name, "content_base64": base64.b64encode(b"%PDF-1.4 source").decode()}


def test_translate_an_uploaded_pdf_writes_inside_the_workspace(api, monkeypatch):
    service = FakeTranslateService()
    install_translate(api, monkeypatch, service)
    response = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert response.status == 200, response.body
    data = body(response)
    assert data["status"] == "translated" and data["output"] == "artifacts/translations/book.en.pdf"
    assert (api.ws_root / data["output"]).read_bytes() == b"%PDF translated"
    assert data["report"]["blocks_translated"] == 2 and "2/2" in data["line"]
    assert service.calls[0][2:] == ("en", "auto")
    assert not (api.ws_root / ".docs" / "staging").exists() or not list((api.ws_root / ".docs" / "staging").iterdir())
    assert str(api.ws_root) not in response.body.decode()


def test_translate_a_workspace_artifact(api, monkeypatch):
    pdf = api.ws_root / "artifacts" / "src.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF")
    seed_artifact(api, pdf)
    service = FakeTranslateService()
    install_translate(api, monkeypatch, service)
    response = api("POST", "/v2/translations", {"artifact_id": "a1", "to": "es", "source_lang": "en",
                                                 "output": "artifacts/translations/custom.pdf"})
    assert response.status == 200, response.body
    assert body(response)["output"] == "artifacts/translations/custom.pdf"
    assert service.calls[0][0] == pdf.resolve() and service.calls[0][3] == "en"


def test_translate_rejects_invalid_input(api, monkeypatch, tmp_path):
    install_translate(api, monkeypatch, FakeTranslateService())
    for bad in ({"to": "en"}, {**pdf_upload(), "artifact_id": "a1", "to": "en"}, {**pdf_upload(), "to": ""},
                {**pdf_upload(), "to": "en; rm -rf /"}, {**pdf_upload(), "to": "en", "source_lang": "../x"},
                {**pdf_upload("book.txt"), "to": "en"}, {**pdf_upload(), "to": "en", "output": "../x.pdf"},
                {**pdf_upload(), "to": "en", "output": str(tmp_path / "x.pdf")},
                {**pdf_upload(), "to": "en", "output": "artifacts/translations/x.txt"},
                {"filename": "b.pdf", "content_base64": "%%%", "to": "en"}, {**pdf_upload()}):
        response = api("POST", "/v2/translations", bad)
        assert response.status == 400, (bad, response.body)
        assert code(response) in {"invalid_request", "invalid_language", "invalid_source", "output_not_permitted",
                                  "invalid_base64"}, bad


def test_translate_without_a_backend_is_a_structured_unavailable_result(api, monkeypatch):
    monkeypatch.setattr(deps_of(api), "build_translate_service", lambda memory_dir, pending: (None, None))
    response = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert response.status == 200, response.body
    data = body(response)
    assert data["status"] == "unavailable" and data["output"] is None and "pypdfium2" in data["message"]


def test_translate_a_pdf_without_a_text_layer_is_a_structured_result(api, monkeypatch):
    install_translate(api, monkeypatch, FakeTranslateService(error=UntranslatablePdfError("sin capa de texto")))
    response = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert response.status == 200, response.body
    assert body(response)["status"] == "untranslatable" and "capa de texto" in body(response)["message"]


# -- scopes / contract ------------------------------------------------------------
def test_tool_operations_enforce_their_scopes(api):
    headers = {"Authorization": "Bearer ok"}
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:read"}), "t1", "o1") if token == "ok" else None
    assert api("GET", "/v2/diagnostics", headers=headers).status == 200
    assert api("GET", "/v2/issue-codes/apa.required", headers=headers).status == 200
    assert api("GET", "/v2/template-catalog", headers=headers).status == 200
    assert api("POST", "/v2/documents/doc/review-rules", {}, headers=headers).status == 200
    for path in ("collect-sources", "collect-issues", "collect-code-evidence", "build-rules", "build-ledger", "build-docx"):
        assert api("POST", f"/v2/documents/doc/{path}", {}, headers=headers).status == 403, path
    assert api("POST", "/v2/translations", {**pdf_upload(), "to": "en"}, headers=headers).status == 403
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:write"}), "t1", "o1") if token == "ok" else None
    assert api("GET", "/v2/diagnostics", headers=headers).status == 403
    assert api("POST", "/v2/documents/doc/build-rules", {}, headers=headers).status == 200


def test_openapi_and_catalogue_declare_the_tool_operations():
    document = build_openapi_document()
    paths = document["paths"]
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, path, scope) in NEW_COMMANDS.items():
        assert paths[path][method.lower()]["x-rbac-scopes"] == [scope], command
        assert catalogue[command]["status"] == "available", command
        assert catalogue[command]["route"] == f"{method} {path}", command
    assert "/v2/template-catalog" in paths
    assert catalogue["template list"]["route"] == "GET /v2/templates"
    for name in ("TranslateRequest", "TranslateResponse", "DiagnosticsResponse", "IssueCodeResponse",
                 "TemplateCatalogResponse", "FormatAuditResponse"):
        assert name in document["components"]["schemas"]


def test_guide_and_stamp_are_explicit_cli_only_exclusions_and_nothing_is_planned():
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command in ("guide", "stamp"):
        entry = catalogue[command]
        assert entry["status"] == "excluded" and entry["route"] is None and entry["surface"] == "cli"
        assert len(entry["reason"]) > 40
    assert [c for c, e in catalogue.items() if e["status"] == "planned"] == []


# -- real sidecar -----------------------------------------------------------------
def test_sidecar_serves_the_tool_routes_over_real_wsgi(canonical_workspace_root):
    tmp_path = canonical_workspace_root
    from docs.sidecar import SidecarConfig, build_server, run

    server = build_server(SidecarConfig(host="127.0.0.1", port=0, workspace=tmp_path))
    workspace_id = server._docs_application.application.workspace_registry.list()[0]["id"]
    thread = threading.Thread(target=run, args=(server,), daemon=True)
    thread.start()

    def get(path):
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}")
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    try:
        status, known = get(f"/v2/issue-codes/apa.required?workspace_id={workspace_id}")
        assert status == 200 and known["code"] == "apa.required"
        status, missing = get(f"/v2/issue-codes/nope.nothing?workspace_id={workspace_id}")
        assert status == 404 and missing["error"]["code"] == "issue_code_not_found"
        status, catalog = get(f"/v2/template-catalog?workspace_id={workspace_id}")
        assert status == 200 and sorted(i["name"] for i in catalog["items"]) == builtin_names()
    finally:
        server.shutdown()
        thread.join(timeout=2)


# -- H1: narrowed degradation, overwrite guard, stable import code ------------------
def test_an_unexpected_runtime_error_is_not_reported_as_a_degraded_tool(api, monkeypatch):
    monkeypatch.setattr(deps_of(api), "docx", FakeDocx(fail=RuntimeError("kaboom")))
    response = api("POST", "/v2/documents/doc/build-docx", {})
    assert response.status == 500, response.body


def test_translate_refuses_to_overwrite_an_existing_output_unless_asked(api, monkeypatch):
    service = FakeTranslateService()
    install_translate(api, monkeypatch, service)
    first = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert first.status == 200, first.body
    out = api.ws_root / "artifacts" / "translations" / "book.en.pdf"
    out.write_bytes(b"%PDF precious")
    again = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert again.status == 409 and code(again) == "output_exists"
    assert out.read_bytes() == b"%PDF precious" and len(service.calls) == 1
    forced = api("POST", "/v2/translations", {**pdf_upload(), "to": "en", "overwrite": True})
    assert forced.status == 200, forced.body
    assert out.read_bytes() == b"%PDF translated"


def test_translate_upload_error_code_is_stable(api, monkeypatch):
    install_translate(api, monkeypatch, FakeTranslateService())

    def odd(*args, **kwargs):
        raise ImportError("quota /tmp/secret exceeded")

    monkeypatch.setattr(api.app._tools._import, "decode_upload", odd)
    response = api("POST", "/v2/translations", {**pdf_upload(), "to": "en"})
    assert response.status == 400 and code(response) == "invalid_source"
    assert "secret" not in response.body.decode()
