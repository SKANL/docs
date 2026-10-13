"""S4.1 quality operations: evidence, baseline promotion, inspect, diff, qa-docx, apply-corrections."""

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from docs.api.auth import Principal
from docs.api.openapi import build_capability_catalog, build_openapi_document
from docs.domain.runtime_records import Artifact, Passport, Run

NEW_COMMANDS = {
    "document evidence": ("GET", "/v2/runs/{run_id}/evidence", "passport:read"),
    "document passport": ("GET", "/v2/runs/{run_id}/passport", "passport:read"),
    "document baseline": ("POST", "/v2/baselines/promotions", "baselines:write"),
    "document inspect": ("GET", "/v2/artifacts/{artifact_id}/inspect", "artifacts:read"),
    "document diff": ("POST", "/v2/artifacts/diff", "artifacts:read"),
    "qa-docx": ("POST", "/v2/documents/{document_id}/qa-docx", "documents:write"),
    "apply-corrections": ("POST", "/v2/documents/{document_id}/corrections/apply", "documents:write"),
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


class MemPassports:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item.run_id] = item

    def get(self, key):
        return self.items.get(key)


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


class MemFindings:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)

    def list(self):
        return list(self.items)

    def list_for_run(self, run_id):
        return [f for f in self.items if f["run_id"] == run_id]


@pytest.fixture
def stores(stores):
    return {
        **stores, "run_store": MemRuns(), "passport_store": MemPassports(),
        "artifact_store": MemArtifacts(), "findings_store": MemFindings(),
    }


def body(response):
    return json.loads(response.body)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put_artifact(api, run_id, artifact_id, path, *, kind="artifact", media_type=""):
    path = Path(path)
    value = {"path": str(path)}
    digest = sha(path) if path.is_file() else "0" * 64
    api.app.artifact_store.put(Artifact(
        artifact_id, run_id, kind, digest, media_type,
        {"value": value, "source": "pipeline", "materialized": path.is_file()},
    ))


def seed_run(api, run_id="r1", previews=2, document_id="doc"):
    api.app.run_store.put(Run(run_id, "succeeded", {"workspace_id": api.wid, "document_id": document_id, "tenant_id": "t1", "organization_id": "o1"}, ""))
    api.app.passport_store.put(Passport(run_id, ({"stage": "verify", "digest": "abc"},)))
    api.app.findings_store.put({"id": f"{run_id}-f1", "run_id": run_id, "severity": "high", "summary": "x"})
    out = api.ws_root / "output" / "qa" / run_id
    out.mkdir(parents=True, exist_ok=True)
    docx = out / "book.docx"
    docx.write_bytes(b"docx-bytes")
    put_artifact(api, run_id, f"{run_id}-docx", docx, kind="build-docx")
    for index in range(previews):
        png = out / f"page-{index + 1}.png"
        Image.new("RGB", (8, 8), (index * 40, 0, 0)).save(png)
        put_artifact(api, run_id, f"{run_id}-preview-{index}", png, kind="preview", media_type="image/png")
    return out


# -- evidence -------------------------------------------------------------------
def test_evidence_bundle_carries_immutable_references_not_file_contents(api):
    out = seed_run(api)
    first = api("GET", "/v2/runs/r1/evidence")
    second = api("GET", "/v2/runs/r1/evidence")
    assert first.status == 200, first.body
    assert first.body == second.body  # identity is stable across calls
    data = body(first)
    assert data["run_id"] == "r1" and data["passport"]["run_id"] == "r1"
    assert len(data["evidence_sha256"]) == 64
    docx = next(a for a in data["artifacts"] if a["id"] == "r1-docx")
    assert docx == {"id": "r1-docx", "kind": "build-docx", "digest": sha(out / "book.docx"), "media_type": ""}
    assert [f["id"] for f in data["findings"]] == ["r1-f1"]
    assert data["previews"] == {"available": True, "artifact_ids": ["r1-preview-0", "r1-preview-1"]}
    assert str(api.ws_root) not in first.body.decode()  # no absolute paths, no raw contents


def test_evidence_identity_changes_when_an_artifact_digest_changes(api):
    out = seed_run(api)
    before = body(api("GET", "/v2/runs/r1/evidence"))["evidence_sha256"]
    (out / "book.docx").write_bytes(b"other")
    put_artifact(api, "r1", "r1-docx", out / "book.docx", kind="build-docx")
    assert body(api("GET", "/v2/runs/r1/evidence"))["evidence_sha256"] != before


def test_evidence_reports_unavailable_previews_as_structured_degradation(api):
    seed_run(api, previews=0)
    data = body(api("GET", "/v2/runs/r1/evidence"))
    assert data["previews"] == {"available": False, "artifact_ids": []}


def test_evidence_of_a_missing_passport_or_foreign_run_is_404(api):
    assert api("GET", "/v2/runs/ghost/evidence").status == 404
    api.app.run_store.put(Run("nopass", "failed", {"workspace_id": api.wid}, ""))
    assert api("GET", "/v2/runs/nopass/evidence").status == 404
    api.app.run_store.put(Run("foreign", "failed", {"workspace_id": "other"}, ""))
    api.app.passport_store.put(Passport("foreign", ()))
    assert api("GET", "/v2/runs/foreign/evidence").status == 404


# -- baseline -------------------------------------------------------------------
def test_baseline_promotion_snapshots_the_run_previews_into_the_workspace(api):
    out = seed_run(api)
    response = api("POST", "/v2/baselines/promotions", {"run_id": "r1"})
    assert response.status == 201, response.body
    data = body(response)
    assert data["run_id"] == "r1" and data["name"] == "r1" and data["replaced"] is False
    assert data["destination"] == "baselines/r1"
    assert data["pages"] == [
        {"name": "page-1.png", "sha256": sha(out / "page-1.png")},
        {"name": "page-2.png", "sha256": sha(out / "page-2.png")},
    ]
    assert sha(api.ws_root / "baselines" / "r1" / "page-2.png") == sha(out / "page-2.png")
    assert str(api.ws_root) not in response.body.decode()


def test_baseline_refuses_overwrite_without_update(api):
    seed_run(api)
    assert api("POST", "/v2/baselines/promotions", {"run_id": "r1", "name": "golden"}).status == 201
    refused = api("POST", "/v2/baselines/promotions", {"run_id": "r1", "name": "golden"})
    assert refused.status == 409 and body(refused)["error"]["code"] == "baseline_exists"
    replaced = api("POST", "/v2/baselines/promotions", {"run_id": "r1", "name": "golden", "update": True})
    assert replaced.status == 201 and body(replaced)["replaced"] is True


def test_baseline_rejects_missing_foreign_unsafe_and_preview_less_runs(api):
    assert api("POST", "/v2/baselines/promotions", {"run_id": "ghost"}).status == 404
    api.app.run_store.put(Run("foreign", "failed", {"workspace_id": "other"}, ""))
    assert api("POST", "/v2/baselines/promotions", {"run_id": "foreign"}).status == 404
    seed_run(api, previews=0)
    bare = api("POST", "/v2/baselines/promotions", {"run_id": "r1"})
    assert bare.status == 409 and body(bare)["error"]["code"] == "previews_unavailable"
    seed_run(api, run_id="r2")
    for name in ("../escape", "a/b", ".."):
        assert api("POST", "/v2/baselines/promotions", {"run_id": "r2", "name": name}).status == 400
    assert not list((api.ws_root / "baselines").glob("*"))  # the workspace owns the directory; nothing was written


def test_baseline_never_accepts_a_filesystem_path(api):
    seed_run(api)
    response = api("POST", "/v2/baselines/promotions", {"run_id": "r1", "source_dir": str(api.ws_root)})
    assert response.status == 400


# -- inspect / diff -------------------------------------------------------------
def test_inspect_returns_the_structured_artifact_report(api):
    out = seed_run(api)
    response = api("GET", "/v2/artifacts/r1-docx/inspect")
    assert response.status == 200, response.body
    data = body(response)
    assert data["artifact_id"] == "r1-docx" and data["sha256"] == sha(out / "book.docx")
    assert data["size_bytes"] == len(b"docx-bytes") and data["path"] == "output/qa/r1/book.docx"
    assert "wordprocessingml" in data["media_type"]


def test_inspect_rejects_missing_unmaterialized_and_escaping_artifacts(api, tmp_path):
    seed_run(api)
    assert api("GET", "/v2/artifacts/ghost/inspect").status == 404
    put_artifact(api, "r1", "r1-gone", api.ws_root / "output" / "nope.bin")
    gone = api("GET", "/v2/artifacts/r1-gone/inspect")
    assert gone.status == 409 and body(gone)["error"]["code"] == "artifact_unavailable"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    put_artifact(api, "r1", "r1-escape", outside)
    escaped = api("GET", "/v2/artifacts/r1-escape/inspect")
    assert escaped.status == 400 and body(escaped)["error"]["code"] == "artifact_outside_workspace"
    assert "secret" not in escaped.body.decode()


def test_diff_compares_two_artifacts_by_identity_and_text(api):
    out = seed_run(api)
    (out / "a.md").write_text("one\ntwo\n", encoding="utf-8")
    (out / "b.md").write_text("one\nthree\n", encoding="utf-8")
    put_artifact(api, "r1", "r1-a", out / "a.md")
    put_artifact(api, "r1", "r1-b", out / "b.md")
    data = body(api("POST", "/v2/artifacts/diff", {"left": "r1-a", "right": "r1-b"}))
    assert data["same"] is False and data["left"]["sha256"] != data["right"]["sha256"]
    assert "-two\n" in data["text_diff"] and "+three\n" in data["text_diff"]
    assert str(api.ws_root) not in json.dumps(data)
    same = body(api("POST", "/v2/artifacts/diff", {"left": "r1-a", "right": "r1-a"}))
    assert same["same"] is True and same["text_diff"] == []


def test_diff_rejects_unknown_ids_and_paths_that_escape(api, tmp_path):
    out = seed_run(api)
    assert api("POST", "/v2/artifacts/diff", {"left": "r1-docx", "right": "ghost"}).status == 404
    assert api("POST", "/v2/artifacts/diff", {"left": "r1-docx"}).status == 400
    outside = tmp_path / "o.txt"
    outside.write_text("x", encoding="utf-8")
    put_artifact(api, "r1", "r1-escape", outside)
    escaped = api("POST", "/v2/artifacts/diff", {"left": "r1-docx", "right": "r1-escape"})
    assert escaped.status == 400 and out.exists()


# -- qa-docx / apply-corrections ---------------------------------------------------
class FakeQa:
    def __init__(self, *, fail=None, pdf=True):
        self.calls, self.fail, self.pdf = [], fail, pdf

    def qa_docx(self, config, path, strict=False):
        self.calls.append((Path(path), strict))
        if self.fail and strict:
            raise RuntimeError(self.fail)
        out = Path(config["paths"]["output_qa_dir"]) / "stem"
        out.mkdir(parents=True, exist_ok=True)
        (out / "qa-report.md").write_text("report", encoding="utf-8")
        if self.pdf:
            (out / "stem.pdf").write_bytes(b"%PDF")
        return out


def install_qa(api, monkeypatch, fake):
    deps = api.app._workspace_services_for(str(api.ws_root.resolve()))
    monkeypatch.setattr(deps, "qa", fake)
    return deps


def test_qa_docx_runs_the_canonical_service_on_a_workspace_artifact(api, monkeypatch):
    out = seed_run(api)
    fake = FakeQa()
    install_qa(api, monkeypatch, fake)
    response = api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "r1-docx"})
    assert response.status == 200, response.body
    data = body(response)
    assert data["passed"] is True and data["degraded"] is False and data["strict"] is False
    assert fake.calls == [((out / "book.docx").resolve(), False)]
    assert data["docx"] == "output/qa/r1/book.docx" and data["report"].endswith("qa-report.md")
    assert str(api.ws_root) not in response.body.decode()


def test_qa_docx_strict_failure_is_a_structured_result_not_a_500(api, monkeypatch):
    seed_run(api)
    fake = FakeQa(fail="render unavailable")
    install_qa(api, monkeypatch, fake)
    loose = body(api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "r1-docx"}))
    strict = api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "r1-docx", "strict": True})
    assert loose["passed"] is True
    assert strict.status == 200
    assert body(strict)["passed"] is False and body(strict)["message"] == "render unavailable"
    assert fake.calls[-1][1] is True


def test_qa_docx_reports_a_missing_render_as_degraded(api, monkeypatch):
    seed_run(api)
    install_qa(api, monkeypatch, FakeQa(pdf=False))
    data = body(api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "r1-docx"}))
    assert data["passed"] is True and data["degraded"] is True
    assert data["degraded_reason"] == "render.capability.unavailable"


def test_qa_docx_without_artifact_needs_a_built_docx_and_rejects_escapes(api, monkeypatch, tmp_path):
    seed_run(api)
    install_qa(api, monkeypatch, FakeQa())
    missing = api("POST", "/v2/documents/doc/qa-docx", {})
    assert missing.status == 409 and body(missing)["error"]["code"] == "docx_unavailable"
    outside = tmp_path / "evil.docx"
    outside.write_bytes(b"x")
    put_artifact(api, "r1", "r1-evil", outside)
    assert api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "r1-evil"}).status == 400
    assert api("POST", "/v2/documents/doc/qa-docx", {"artifact_id": "ghost"}).status == 404
    assert api("POST", "/v2/documents/ghost/qa-docx", {}).status == 404


def test_apply_corrections_calls_the_canonical_service(api, monkeypatch):
    calls = []

    class FakeCorrections:
        def apply_corrections(self, doc_id, config):
            calls.append(doc_id)
            return 3

    deps = api.app._workspace_services_for(str(api.ws_root.resolve()))
    monkeypatch.setattr(deps, "corrections", FakeCorrections())
    response = api("POST", "/v2/documents/doc/corrections/apply", {})
    assert response.status == 200 and body(response) == {"document_id": "doc", "applied": 3}
    assert calls == ["doc"]
    assert api("POST", "/v2/documents/ghost/corrections/apply", {}).status == 404


def test_apply_corrections_with_an_empty_inbox_applies_nothing(api):
    response = api("POST", "/v2/documents/doc/corrections/apply", {})
    assert response.status == 200, response.body
    assert body(response)["applied"] == 0


# -- scopes, openapi, catalogue -----------------------------------------------------
def test_quality_routes_enforce_scopes(api):
    seed_run(api)
    headers = {"Authorization": "Bearer ok"}
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:read", "passport:read"}), "t1", "o1") if token == "ok" else None
    assert api("POST", "/v2/baselines/promotions", {"run_id": "r1"}, headers=headers).status == 403
    assert api("POST", "/v2/artifacts/diff", {"left": "a", "right": "b"}, headers=headers).status == 403
    assert api("GET", "/v2/artifacts/r1-docx/inspect", headers=headers).status == 403
    assert api("POST", "/v2/documents/doc/qa-docx", {}, headers=headers).status == 403
    assert api("POST", "/v2/documents/doc/corrections/apply", {}, headers=headers).status == 403
    # evidence bundles artifacts and findings too: passport:read alone is not enough
    denied = api("GET", "/v2/runs/r1/evidence", headers=headers)
    assert denied.status == 403 and body(denied)["error"]["code"] == "insufficient_scope"


def test_evidence_succeeds_with_every_scope_it_discloses(api):
    seed_run(api)
    full = frozenset({"passport:read", "artifacts:read", "findings:read"})
    api.app.auth = lambda token: Principal("ada", full, "t1", "o1") if token == "ok" else None
    assert api("GET", "/v2/runs/r1/evidence", headers={"Authorization": "Bearer ok"}).status == 200


def test_openapi_and_catalogue_declare_every_quality_command():
    paths = build_openapi_document()["paths"]
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, path, scope) in NEW_COMMANDS.items():
        assert paths[path][method.lower()]["x-rbac-scopes"] == [scope], command
        assert catalogue[command]["status"] == "available", command
        assert catalogue[command]["route"] == f"{method} {path}", command
