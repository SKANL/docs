import json

from docs.api.openapi import build_openapi_document, canonical_json


def test_x20_catalog_covers_required_v1_resources() -> None:
    document = build_openapi_document()
    routes = {(method.upper(), path) for path, item in document["paths"].items() for method in item}

    assert {
        ("GET", "/v1/documents"),
        ("GET", "/v1/graph"),
        ("GET", "/v1/findings"),
        ("POST", "/v1/runs"),
        ("GET", "/v1/runs/{run_id}"),
        ("POST", "/v1/runs/{run_id}/cancel"),
        ("GET", "/v1/runs/{run_id}/passport"),
        ("GET", "/v1/runs/{run_id}/artifacts"),
        ("GET", "/v1/runs/{run_id}/progress"),
        ("GET", "/v1/runs/{run_id}/graph"),
        ("GET", "/v1/artifacts/{artifact_id}"),
        ("GET", "/v1/artifacts/{artifact_id}/previews"),
        ("GET", "/v1/revisions"),
        ("GET", "/v1/revisions/{revision_id}"),
        ("GET", "/v1/baselines"),
        ("POST", "/v1/baselines"),
        ("GET", "/v1/baselines/{baseline_id}"),
        ("POST", "/v1/baselines/promotions"),
        ("POST", "/v1/baselines/{baseline_id}/promote"),
        ("GET", "/v1/plugins"),
        ("GET", "/v1/plugins/{plugin_id}"),
    } <= routes

    assert document["openapi"] == "3.1.0"
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
    expected_security = [{"bearerAuth": []}, {"apiKeyAuth": []}]

    assert document["security"] == expected_security
    for path_item in document["paths"].values():
        for method, operation in path_item.items():
            if method == "parameters":
                continue
            assert operation["security"] == expected_security
            assert {"400", "401", "404"} <= set(operation["responses"])

    for path in (
        "/v1/documents",
        "/v1/findings",
        "/v1/runs/{run_id}/artifacts",
        "/v1/artifacts/{artifact_id}/previews",
        "/v1/revisions",
        "/v1/baselines",
        "/v1/plugins",
    ):
        schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert {"$ref": "#/components/schemas/page"} in schema["allOf"]
        assert schema["allOf"][1]["properties"]["items"]["items"]["$ref"].startswith("#/components/schemas/")

    progress = document["paths"]["/v1/runs/{run_id}/progress"]["get"]["responses"]["200"]
    assert "text/event-stream" in progress["content"]


def test_builder_returns_independent_documents() -> None:
    first = build_openapi_document()
    first["info"]["title"] = "changed"

    assert build_openapi_document()["info"]["title"] == "X20 API"


def test_graph_query_modes_are_documented() -> None:
    graph = build_openapi_document()["paths"]["/v1/graph"]
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
    graph = build_openapi_document()["paths"]["/v1/graph"]
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


def test_run_graph_reuses_the_graph_query_contract_and_scope() -> None:
    paths = build_openapi_document()["paths"]
    graph = paths["/v1/graph"]
    run_graph = paths["/v1/runs/{run_id}/graph"]

    assert run_graph["get"]["x-rbac-scopes"] == ["graph:read"]
    assert run_graph["parameters"][1:] == graph["parameters"]
    assert run_graph["get"]["responses"]["200"] == graph["get"]["responses"]["200"]


def test_collection_baseline_promotion_contract_matches_the_facade() -> None:
    operation = build_openapi_document()["paths"]["/v1/baselines/promotions"]["post"]

    assert operation["x-rbac-scopes"] == ["baselines:write"]
    assert operation["requestBody"]["required"] is True
