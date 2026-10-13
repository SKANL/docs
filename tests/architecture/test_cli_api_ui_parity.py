"""Executable coverage of the CLI-to-capability-to-HTTP contract."""

import re
from pathlib import Path

from typer.main import get_command

from docs.api import openapi
from docs.api.application import X20Application
from docs.cli.main import app as cli_app

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/review-studio/cli-api-ui-parity.md"


def _cli_commands(group, prefix="") -> set[str]:
    commands = set()
    for name, command in group.commands.items():
        full_name = f"{prefix} {name}".strip()
        if hasattr(command, "commands"):
            commands.update(_cli_commands(command, full_name))
        else:
            commands.add(full_name)
    return commands


def _capabilities():
    builder = getattr(openapi, "build_capability_catalog", None)
    assert callable(builder), "S0.1 must expose a capability catalogue builder"
    return [item for group in builder()["groups"] for item in group["capabilities"]]


def test_every_registered_cli_command_has_exactly_one_capability_and_matrix_row():
    commands = _cli_commands(get_command(cli_app))
    capabilities = _capabilities()
    represented = [item["cli_command"] for item in capabilities]
    assert len(represented) == len(set(represented))
    assert set(represented) == commands

    assert MATRIX.exists(), "S0.1 must publish the parity matrix"
    rows = re.findall(r"^\| `docs ([^`]+)` \|", MATRIX.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(rows) == len(set(rows))
    assert set(rows) == commands

    matrix = MATRIX.read_text(encoding="utf-8")
    for item in capabilities:
        row = next(line for line in matrix.splitlines() if line.startswith(f'| `docs {item["cli_command"]}` |'))
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert cells[1] == (f'`{item["route"]}`' if item["route"] else "—")
        assert cells[2] == item["status"]
        assert cells[4] == item["slice"]


def test_available_capabilities_have_real_registered_routes_and_matching_scopes():
    application = X20Application(
        run_store=None, queue=None, passport_store=None, artifact_store=None,
        graph_store=None,
    )
    paths = openapi.build_openapi_document()["paths"]
    for capability in _capabilities():
        assert {"id", "cli_command", "route", "scopes", "surface", "slice", "status"} <= capability.keys()
        if capability["status"] != "available":
            assert capability["route"] is None
            continue
        method, path = capability["route"].split(" ", 1)
        assert method.lower() in paths[path], capability
        assert capability["scopes"] == paths[path][method.lower()].get("x-rbac-scopes", []), capability
        actual = re.sub(r"\{[^}]+\}", "sample", path)
        assert (method, path) in application._registered_route_keys() or application._dynamic_handler(method, actual) is not None, capability
        assert application._required_scope(method, actual) in capability["scopes"], capability


def test_capability_catalog_http_route_returns_the_declared_catalog():
    from docs.api.http import Request

    application = X20Application(
        run_store=None, queue=None, passport_store=None, artifact_store=None,
        graph_store=None,
    )
    response = application.dispatch(Request("GET", "/v2/capabilities"))
    assert response.status == 200
    assert response.headers["content-type"].startswith("application/json")
    assert b'"groups"' in response.body


# `document classify` left the partial-equivalent guard in S2.1, `document publish` in S5.1
# and `doc status` in S6.1: each now runs the same canonical service as its CLI command
# (`doc status` through `build_document_summary`), so none is partial any more.
def test_excluded_commands_carry_a_reason_and_no_route():
    excluded = [item for item in _capabilities() if item["status"] == "excluded"]
    assert {item["cli_command"] for item in excluded} == {"doc init"}
    for item in excluded:
        assert item["route"] is None and item["scopes"] == [], item
        assert item["reason"].strip(), item
    assert all("reason" not in item for item in _capabilities() if item["status"] != "excluded")
