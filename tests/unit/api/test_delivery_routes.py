"""S5.1 delivery operations: package a document's build output, publish a verified artifact."""

import hashlib
import json
from pathlib import Path

import pytest

from docs.api.auth import Principal
from docs.api.openapi import build_capability_catalog, build_openapi_document
from docs.application.document_pipeline import _current_input_identities, _resolve_publish_inputs
from docs.application.provenance import ProvenanceLedger
from docs.domain.artifacts import ArtifactRef, BuildManifest
from docs.domain.runtime_records import Run

NEW_COMMANDS = {
    "document package": ("POST", "/v2/documents/{document_id}/package", "documents:write"),
    "document publish": ("POST", "/v2/documents/{document_id}/publications", "documents:write"),
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


class MemPublications:
    def __init__(self):
        self.items = {}

    def put(self, item):
        self.items[item["id"]] = item

    def put_if_absent(self, item):
        if item["id"] in self.items:
            return False
        self.items[item["id"]] = item
        return True

    def list(self):
        return list(self.items.values())


@pytest.fixture
def stores(stores):
    return {**stores, "run_store": MemRuns(), "publication_store": MemPublications()}


def body(response):
    return json.loads(response.body)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seed_release(api, fmt="docx", content=b"docx-bytes", run="run-1"):
    """A real verified build: manifest with live identities plus a recorded attestation."""
    deps = api.app._workspace_services_for(str(api.ws_root.resolve()))
    root = api.doc_root
    resolved, config, renderer = _resolve_publish_inputs(deps, root, fmt)
    ids = _current_input_identities(resolved=resolved, config=config, renderer=renderer, root=root, output_format=fmt)
    current = root / "output" / "current"
    current.mkdir(parents=True, exist_ok=True)
    artifact = current / f"doc.{fmt}"
    artifact.write_bytes(content)
    manifest = BuildManifest(
        document_id="doc", source_hash=ids["source_hash"], template_hash=ids["template_hash"],
        template_ir_hash=ids["template_ir_hash"], config_hash=ids["config_hash"], context_hash=ids["context_hash"],
        asset_hashes=ids["asset_hashes"], renderer_versions=ids["renderer_versions"],
        artifacts=(ArtifactRef(str(artifact.resolve()), sha(artifact)),),
        verification={"passed": True}, provenance_run=run,
    )
    manifest_path = current / f"doc.{fmt}.manifest.json"
    manifest_path.write_text(manifest.to_json(), encoding="utf-8")
    (root / "runs").mkdir(exist_ok=True)
    ledger = ProvenanceLedger(root / "runs" / "provenance.json", trusted_root=root)
    ledger.record_run(run, inputs=(), outputs=())
    ledger.record_attestation(run, manifest.attestation())
    return artifact, manifest_path


def seed_run(api, run_id="r1", document_id="doc"):
    api.app.run_store.put(Run(run_id, "succeeded", {"workspace_id": api.wid, "document_id": document_id, "tenant_id": "t1", "organization_id": "o1"}, ""))


# -- package --------------------------------------------------------------------
def test_package_writes_a_workspace_owned_archive_and_reports_its_digest(api):
    seed_release(api)
    seed_run(api)
    response = api("POST", "/v2/documents/doc/package", {"run_id": "r1", "name": "v1"})
    assert response.status == 200, response.body
    data = body(response)
    archive = api.ws_root / data["destination"]
    assert data["destination"] == "artifacts/packages/doc-v1.zip"
    assert data["document_id"] == "doc" and data["run_id"] == "r1"
    assert data["source"] == "documents/doc/output/current"
    assert data["sha256"] == sha(archive) and data["size_bytes"] == archive.stat().st_size
    assert str(api.ws_root) not in response.body.decode()


def test_package_digest_is_stable_across_identical_inputs(api):
    seed_release(api)
    first = body(api("POST", "/v2/documents/doc/package", {"name": "a"}))
    second = body(api("POST", "/v2/documents/doc/package", {"name": "b"}))
    again = body(api("POST", "/v2/documents/doc/package", {"name": "a"}))
    assert first["sha256"] == second["sha256"] == again["sha256"]
    assert first["run_id"] is None


def test_package_rejects_names_that_escape_the_package_directory(api):
    seed_release(api)
    for name in ("../evil", "a/b", ".."):
        response = api("POST", "/v2/documents/doc/package", {"name": name})
        assert response.status == 400, name
    assert not (api.ws_root / "evil.zip").exists()


def test_package_without_a_build_output_is_a_conflict(api):
    response = api("POST", "/v2/documents/doc/package", {})
    assert response.status == 409
    assert body(response)["error"]["code"] == "package_source_unavailable"


def test_package_of_unverified_output_is_rejected_with_the_reason(api):
    artifact, _ = seed_release(api)
    artifact.write_bytes(b"tampered")
    response = api("POST", "/v2/documents/doc/package", {})
    assert response.status == 409
    error = body(response)["error"]
    assert error["code"] == "package_rejected" and "hash" in error["message"]
    assert str(api.ws_root) not in response.body.decode()
    assert not (api.ws_root / "artifacts" / "packages" / "doc-current.zip").exists()


def test_package_unknown_run_and_document_are_not_found(api):
    seed_release(api)
    seed_run(api, "other", document_id="elsewhere")
    assert api("POST", "/v2/documents/doc/package", {"run_id": "ghost"}).status == 404
    assert api("POST", "/v2/documents/doc/package", {"run_id": "other"}).status == 404
    assert api("POST", "/v2/documents/ghost/package", {}).status == 404


# -- publish --------------------------------------------------------------------
def publish(api, **payload):
    payload.setdefault("destination", "doc.docx")
    return api("POST", "/v2/documents/doc/publications", payload)


def test_publish_to_a_permitted_destination_returns_immutable_release_evidence(api):
    artifact, _ = seed_release(api)
    response = publish(api, destination="v1/doc.docx")
    assert response.status == 201, response.body
    data = body(response)
    destination = api.doc_root / "output" / "release" / "v1" / "doc.docx"
    assert data["destination"] == "documents/doc/output/release/v1/doc.docx"
    assert destination.read_bytes() == artifact.read_bytes()
    assert data["artifact_sha256"] == sha(destination) == sha(artifact)
    assert data["manifest_sha256"] == sha(destination.with_suffix(".docx.manifest.json"))
    assert data["provenance_run"] == "run-1" and data["policy"] == "release" and data["format"] == "docx"
    assert {"source_hash", "config_hash", "template_hash"} <= data["identities"].keys()
    assert str(api.ws_root) not in response.body.decode()
    # re-reading changes nothing: same digests and the same publication record id
    again = body(publish(api, destination="v1/doc.docx"))
    for key in ("id", "artifact_sha256", "manifest_sha256", "identities"):
        assert again[key] == data[key], key
    listed = body(api("GET", "/v2/publications"))["items"]
    assert [item["id"] for item in listed] == [data["id"]]
    assert listed[0]["status"] == "passed" and listed[0]["document_id"] == "doc"
    # the history carries what the publish response reported, so the Delivery table has no blanks to guess
    assert listed[0]["policy"] == data["policy"] == "release"
    assert listed[0]["warnings"] == data["warnings"]


@pytest.mark.parametrize("destination", ["../escape.docx", "/abs/escape.docx", "a/../../escape.docx", "", "C:/escape.docx"])
def test_publish_rejects_a_destination_outside_the_permitted_area(api, destination):
    seed_release(api)
    response = publish(api, destination=destination)
    assert response.status == 400, destination
    assert body(response)["error"]["code"] == "destination_not_permitted"
    assert body(api("GET", "/v2/publications"))["items"] == []
    assert not (api.doc_root / "escape.docx").exists() and not (api.ws_root / "escape.docx").exists()


def test_publish_policy_denial_surfaces_the_server_reason(api):
    seed_release(api)
    response = publish(api, policy="draft")
    assert response.status == 422
    error = body(response)["error"]
    assert error["code"] == "publish_policy_denied" and "strict or --policy release" in error["message"]
    assert not (api.doc_root / "output" / "release").exists()
    assert body(api("GET", "/v2/publications"))["items"] == []


def test_publish_of_a_tampered_artifact_is_an_error_not_a_success(api):
    artifact, _ = seed_release(api)
    artifact.write_bytes(b"tampered")
    response = publish(api)
    assert response.status == 409
    error = body(response)["error"]
    assert error["code"] == "publish_rejected" and "artifact hash" in error["message"]
    assert not (api.doc_root / "output" / "release").exists()
    assert body(api("GET", "/v2/publications"))["items"] == []


def test_publish_after_an_input_changed_is_an_error_not_a_success(api):
    seed_release(api)
    (api.doc_root / "assets").mkdir(exist_ok=True)
    (api.doc_root / "assets" / "late.txt").write_text("new input", encoding="utf-8")
    response = publish(api)
    assert response.status == 409
    assert body(response)["error"]["code"] == "publish_failed"
    assert not (api.doc_root / "output" / "release").exists()
    assert body(api("GET", "/v2/publications"))["items"] == []


def test_publish_without_a_build_output_or_with_unknown_document(api):
    assert publish(api).status == 409
    assert api("POST", "/v2/documents/ghost/publications", {"destination": "x.docx"}).status == 404
    seed_release(api)
    assert publish(api, format="rtf").status == 400


# -- scopes / contract ----------------------------------------------------------
def test_delivery_routes_require_the_write_scope(api):
    seed_release(api)
    headers = {"Authorization": "Bearer ok"}
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:read"}), "t1", "o1") if token == "ok" else None
    assert api("POST", "/v2/documents/doc/package", {}, headers=headers).status == 403
    assert api("POST", "/v2/documents/doc/publications", {"destination": "x.docx"}, headers=headers).status == 403
    api.app.auth = lambda token: Principal("ada", frozenset({"documents:write"}), "t1", "o1") if token == "ok" else None
    assert api("POST", "/v2/documents/doc/package", {}, headers=headers).status == 200


def test_openapi_and_catalogue_declare_the_delivery_commands_and_the_two_publish_meanings():
    document = build_openapi_document()
    paths = document["paths"]
    catalogue = {c["cli_command"]: c for g in build_capability_catalog()["groups"] for c in g["capabilities"]}
    for command, (method, path, scope) in NEW_COMMANDS.items():
        assert paths[path][method.lower()]["x-rbac-scopes"] == [scope], command
        assert catalogue[command]["status"] == "available", command
        assert catalogue[command]["route"] == f"{method} {path}", command
    queued = paths["/v2/documents/{document_id}/publish"]["post"]["summary"].lower()
    direct = paths["/v2/documents/{document_id}/publications"]["post"]["summary"].lower()
    assert "queue" in queued and "synchronous" in direct
    for name in ("PackageRequest", "PackageResponse", "PublishRequest", "PublicationResponse"):
        assert name in document["components"]["schemas"]


# -- H1: service verdicts, narrowed handlers, race-free record ------------------------
def test_policy_denial_comes_from_the_services_verdict_not_the_policy_string(api, monkeypatch):
    from docs.application.package_publication_service import PackagePublicationError, PackagePublicationService

    seed_release(api)

    def other_rejection(self, *args, **kwargs):
        raise PackagePublicationError("publish requires an artifact with its matching manifest")

    monkeypatch.setattr(PackagePublicationService, "preflight_publish", other_rejection)
    response = publish(api, policy="draft")  # a draft policy, but the service said something else
    assert response.status == 409 and body(response)["error"]["code"] == "publish_rejected"


def test_policy_denial_is_422_when_the_service_denies(api, monkeypatch):
    from docs.application.package_publication_service import PackagePublicationService, PublishPolicyDeniedError

    seed_release(api)

    def denied(self, *args, **kwargs):
        raise PublishPolicyDeniedError("nope")

    monkeypatch.setattr(PackagePublicationService, "preflight_publish", denied)
    response = publish(api, policy="release")
    assert response.status == 422 and body(response)["error"]["code"] == "publish_policy_denied"


def test_unresolvable_inputs_are_409_but_programming_errors_are_not_swallowed(api, monkeypatch):
    seed_release(api)

    def failing(exc):
        def raiser(**kwargs):
            raise exc

        return raiser

    monkeypatch.setattr("docs.api.delivery_routes._current_input_identities", failing(ValueError("bad inputs")))
    assert publish(api).status == 409
    monkeypatch.setattr("docs.api.delivery_routes._current_input_identities", failing(AttributeError("bug")))
    assert publish(api).status == 500


def test_concurrent_identical_publishes_never_rewrite_the_record(api):
    class RacyPublications(MemPublications):
        def list(self):  # the existence pre-check always loses the race
            return []

        def put_if_absent(self, item):
            if item["id"] in self.items:
                return False
            self.items[item["id"]] = item
            return True

        def put(self, item):  # an unconditional write is the bug
            raise AssertionError("record must be written with put_if_absent")

    store = RacyPublications()
    api.app.publication_store = store
    seed_release(api)
    first = publish(api, destination="v1/doc.docx")
    assert first.status == 201, first.body
    published_at = next(iter(store.items.values()))["published_at"]
    assert publish(api, destination="v1/doc.docx").status == 201
    assert next(iter(store.items.values()))["published_at"] == published_at
