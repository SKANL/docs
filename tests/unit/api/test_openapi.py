import json

from docs.api.openapi import build_openapi_document, canonical_json


def test_x20_catalog_covers_canonical_v2_resources() -> None:
    document = build_openapi_document()
    routes = {(method.upper(), path) for path, item in document["paths"].items() for method in item}

    assert {
        ("GET", "/v2/documents"),
        ("GET", "/v2/graph"),
        ("GET", "/v2/findings"),
        ("POST", "/v2/runs"),
        ("GET", "/v2/runs/{run_id}"),
        ("POST", "/v2/runs/{run_id}/cancel"),
        ("GET", "/v2/runs/{run_id}/passport"),
        ("GET", "/v2/runs/{run_id}/artifacts"),
        ("GET", "/v2/runs/{run_id}/progress"),
        ("GET", "/v2/runs/{run_id}/graph"),
        ("GET", "/v2/runs/{run_id}/findings"),
        ("GET", "/v2/runs/{run_id}/previews/{name}"),
        ("GET", "/v2/artifacts/{artifact_id}"),
        ("GET", "/v2/artifacts/{artifact_id}/previews"),
        ("GET", "/v2/revisions"),
        ("GET", "/v2/revisions/{revision_id}"),
        ("GET", "/v2/baselines"),
        ("GET", "/v2/baselines/{baseline_id}"),
        ("GET", "/v2/plugins"),
        ("GET", "/v2/plugins/{plugin_id}"),
    } <= routes

    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == "2.0.0"
    assert all(path.startswith("/v2/") for path in document["paths"])
    assert "post" not in document["paths"]["/v2/baselines"]
    assert "/v2/baselines/promotions" not in document["paths"]
    assert "/v2/baselines/{baseline_id}/promote" not in document["paths"]
    assert "$ref" in json.dumps(document["paths"])
    assert "bearerAuth" in document["components"]["securitySchemes"]
    assert "page" in document["components"]["schemas"]
    assert "error" in document["components"]["schemas"]


def test_canonical_json_is_stable_and_sorted() -> None:
    first = build_openapi_document()
    second = build_openapi_document()

    assert canonical_json(first) == canonical_json(second)
    assert canonical_json({"z": 1, "a": {"d": 2, "c": 3}}) == '{"a":{"c":3,"d":2},"z":1}'
    encoded = canonical_json({"é": "世界", "a": 1})
    assert encoded == '{"a":1,"é":"世界"}'
    assert "\n" not in encoded


def test_operations_retain_contract_references_security_and_errors() -> None:
    document = build_openapi_document()
    expected_security = [{"bearerAuth": []}]

    assert document["security"] == expected_security
    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method == "parameters":
                continue
            assert operation["security"] == expected_security
            assert {"400", "401", "404"} <= set(operation["responses"])

    for path in (
        "/v2/documents",
        "/v2/findings",
        "/v2/runs/{run_id}/artifacts",
        "/v2/artifacts/{artifact_id}/previews",
        "/v2/revisions",
        "/v2/baselines",
        "/v2/plugins",
    ):
        schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert {"$ref": "#/components/schemas/page"} in schema["allOf"]
        assert schema["allOf"][1]["properties"]["items"]["items"]["$ref"].startswith("#/components/schemas/")

    progress = document["paths"]["/v2/runs/{run_id}/progress"]["get"]["responses"]["200"]
    assert "text/event-stream" in progress["content"]


def test_builder_returns_independent_documents() -> None:
    first = build_openapi_document()
    first["info"]["title"] = "changed"

    assert build_openapi_document()["info"]["title"] == "X20 API"


def test_graph_query_modes_are_documented() -> None:
    graph = build_openapi_document()["paths"]["/v2/graph"]
    parameters = {parameter["name"]: parameter for parameter in graph["parameters"]}

    assert parameters["mode"]["schema"]["enum"] == [
        "claims_without_evidence",
        "findings_affected_by_revision",
        "artifacts_derived_from_input",
        "unused_references",
        "unmet_requirements",
    ]
    assert parameters["revision_id"]["description"]
    assert parameters["input_id"]["description"]


def test_review_studio_graph_query_aliases_and_id_are_documented() -> None:
    graph = build_openapi_document()["paths"]["/v2/graph"]
    parameters = {parameter["name"]: parameter for parameter in graph["parameters"]}

    assert parameters["query"]["schema"]["enum"] == [
        "claims_without_evidence",
        "findings_affected_by_revision",
        "artifacts_derived_from_input",
        "unused_references",
        "unmet_requirements",
    ]
    assert parameters["id"]["description"]
    assert parameters["mode"]["schema"]["enum"] == parameters["query"]["schema"]["enum"]
    assert parameters["revision_id"]["schema"] == {"type": "string"}
    assert parameters["input_id"]["schema"] == {"type": "string"}


def test_document_actions_document_workspace_format_and_policy_contract() -> None:
    paths = build_openapi_document()["paths"]
    expected = {"workspace_id", "run_id", "format", "policy"}

    for action in ("prepare", "build", "verify", "publish"):
        operation = paths[f"/v2/documents/{{document_id}}/{action}"]["post"]
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert set(schema["properties"]) == expected
        assert schema["required"] == ["workspace_id"]
        assert schema["properties"]["format"]["enum"] == ["docx", "html", "pdf"]
        assert schema["properties"]["policy"]["enum"] == ["draft", "strict", "release"]


def test_import_job_and_stage_are_versioned_contracts() -> None:
    schemas = build_openapi_document()["components"]["schemas"]

    assert {
        "id", "document_id", "filename", "path", "mime_type", "size", "sha256", "deduplicated"
    } == set(schemas["import_job"]["properties"])
    assert schemas["import_job"]["properties"]["size"] == {"type": "integer", "minimum": 1}
    assert {
        "name", "status", "progress", "started_at", "finished_at"
    } == set(schemas["stage"]["properties"])
    assert schemas["stage"]["properties"]["progress"]["type"] == "number"
    assert "expired" in schemas["status"]["enum"]


def test_run_schema_matches_the_docs_x20_contract_shape() -> None:
    run = build_openapi_document()["components"]["schemas"]["run"]

    assert set(run["properties"]) == {"schema", "id", "status", "payload", "created_at"}
    assert run["properties"]["schema"]["const"] == "docs.x20/v1"
    assert run["properties"]["payload"] == {"type": "object"}
    assert "document_id" not in run["properties"]


def test_run_graph_reuses_the_graph_query_contract_and_scope() -> None:
    paths = build_openapi_document()["paths"]
    graph = paths["/v2/graph"]
    run_graph = paths["/v2/runs/{run_id}/graph"]

    assert run_graph["get"]["x-rbac-scopes"] == ["graph:read"]
    assert run_graph["parameters"][1:] == graph["parameters"]
    assert run_graph["get"]["responses"]["200"] == graph["get"]["responses"]["200"]


def test_baseline_contract_contains_only_live_read_operations() -> None:
    paths = build_openapi_document()["paths"]

    assert set(paths["/v2/baselines"]) == {"get", "parameters"}
    assert set(paths["/v2/baselines/{baseline_id}"]) == {"get", "parameters"}


def test_workspace_identity_is_required_for_workspace_content_and_optional_for_global_plugins() -> None:
    paths = build_openapi_document()["paths"]
    for path in ("/v2/documents", "/v2/runs", "/v2/graph", "/v2/baselines", "/v2/revisions"):
        workspace = next(parameter for parameter in paths[path]["parameters"] if parameter["name"] == "workspace_id")
        assert workspace["in"] == "query"
        assert workspace["required"] is True

    plugin_workspace = next(parameter for parameter in paths["/v2/plugins"]["parameters"] if parameter["name"] == "workspace_id")
    assert plugin_workspace["required"] is False
    create_workspace = paths["/v2/documents"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "workspace_id" in create_workspace["required"]
    raw_import_workspace = next(
        parameter for parameter in paths["/v2/documents/import/raw"]["parameters"]
        if parameter["name"] == "workspace_id"
    )
    assert raw_import_workspace["in"] == "query" and raw_import_workspace["required"] is True

    create_workspace = paths["/v2/workspaces"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert create_workspace["required"] == ["name"]
    assert "root" not in create_workspace["properties"]
