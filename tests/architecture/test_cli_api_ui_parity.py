"""Executable coverage of the CLI-to-capability-to-HTTP contract."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
from typer.main import get_command

from docs.api import openapi
from docs.api.application import X20Application
from docs.cli.main import app as cli_app

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs/review-studio/cli-api-ui-parity.md"
PARITY_UI = ROOT / "docs/review-studio/parity-ui.json"
ROUTES_TSX = ROOT / "review-studio/src/app/routes.tsx"
PROOF_SEP = " › "

# Available commands whose UI is still being built. `parity-ui.json` may mark a row `pending` only if it is
# listed here, so an unfinished surface is a reviewed decision and never a silent default.
# S7.2 must empty this set (and delete the skip on `test_no_pending_ui_rows_remain`) before release.
PENDING_UI: frozenset[str] = frozenset()
# Available commands with no direct automated API test of their own route yet (the route exists and is
# catalogued). S7.2 must close this set too.
API_PROOF_GAPS: frozenset[str] = frozenset()


def _load_regen():
    spec = importlib.util.spec_from_file_location("regen_parity_matrix", ROOT / "tools/regen_parity_matrix.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parity_ui() -> dict:
    assert PARITY_UI.exists(), "the hand-curated UI cells and proof references live in parity-ui.json"
    return json.loads(PARITY_UI.read_text(encoding="utf-8"))


def _available() -> dict:
    return {item["cli_command"]: item for item in _capabilities() if item["status"] == "available"}


def _split_ref(ref: str) -> tuple[Path, str]:
    path, _, name = ref.partition(PROOF_SEP) if PROOF_SEP in ref else ref.partition("::")
    return ROOT / path, name


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
# S6.2 closed the last `planned` rows: `guide` and `stamp` are terminal-only agent helpers, excluded with a reason.
def test_excluded_commands_carry_a_reason_and_no_route():
    excluded = [item for item in _capabilities() if item["status"] == "excluded"]
    assert {item["cli_command"] for item in excluded} == {"doc init", "guide", "stamp"}
    for item in excluded:
        assert item["route"] is None and item["scopes"] == [], item
        assert item["reason"].strip(), item
    assert all("reason" not in item for item in _capabilities() if item["status"] != "excluded")


def test_every_available_command_has_a_ui_cell_or_an_allow_listed_pending_one():
    ui, available = _parity_ui(), _available()
    assert set(ui) == set(available), "parity-ui.json must carry exactly the available commands"
    for command, entry in ui.items():
        assert bool(entry.get("ui")) != bool(entry.get("pending")), f"{command}: exactly one of ui / pending"
    assert {c for c, e in ui.items() if e.get("pending")} == PENDING_UI


def test_every_available_command_has_an_api_proof():
    ui = _parity_ui()
    missing = {c for c, e in ui.items() if not e.get("api")}
    assert missing == API_PROOF_GAPS


def test_every_ui_exposed_command_has_a_frontend_or_e2e_proof():
    for command, entry in _parity_ui().items():
        if entry.get("ui"):
            proofs = entry.get("proof", [])
            assert proofs, f"{command}: a UI-exposed row needs a frontend or E2E test"
            assert all(p.startswith(("review-studio/src/test/", "review-studio/e2e/")) for p in proofs), command


def test_every_proof_reference_resolves_to_a_real_test():
    for command, entry in _parity_ui().items():
        for ref in entry.get("api", []):
            file, name = _split_ref(ref)
            assert file.suffix == ".py" and file.exists(), f"{command}: {ref}"
            assert re.search(rf"^\s*(async )?def {re.escape(name)}\(", file.read_text(encoding="utf-8"), re.MULTILINE), f"{command}: {ref}"
        for ref in entry.get("proof", []):
            file, title = _split_ref(ref)
            assert file.exists() and title, f"{command}: {ref}"
            assert f'"{title}"' in file.read_text(encoding="utf-8"), f"{command}: {ref}"


def _route_patterns() -> list[re.Pattern]:
    patterns = []
    for raw in re.findall(r'path="([^"]+)"', ROUTES_TSX.read_text(encoding="utf-8")):
        if raw == "*" or raw.startswith("legacy"):
            continue
        body = "".join(
            r"(?:/[^/]+)?" if seg.endswith("?") else "/" + (r"[^/]+" if seg.startswith(":") else re.escape(seg))
            for seg in raw.split("/")
        )
        patterns.append(re.compile(body))
    return patterns


def test_every_claimed_ui_route_exists_in_the_router():
    patterns = _route_patterns()
    tabs = {"authoring": "features/authoring/AuthoringRoute.tsx", "review": "features/quality/QualityRoute.tsx"}
    for command, entry in _parity_ui().items():
        if not entry.get("ui"):
            continue
        route = entry["ui"].split(PROOF_SEP)[0]
        assert route.startswith("/") and not route.startswith("/legacy"), f"{command}: {route}"
        assert any(p.fullmatch(route) for p in patterns), f"{command}: {route} is not in routes.tsx"
        area, _, tab = route.strip("/").partition("/")
        if area in tabs and tab and not tab.startswith(":"):
            source = (ROOT / "review-studio/src" / tabs[area]).read_text(encoding="utf-8")
            assert f'["{tab.split("/")[0]}",' in source, f"{command}: no {area} tab {tab}"


def test_excluded_rows_carry_their_reason_in_the_matrix_and_no_ui_data():
    matrix, ui = MATRIX.read_text(encoding="utf-8"), _parity_ui()
    for item in (c for c in _capabilities() if c["status"] == "excluded"):
        assert item["cli_command"] not in ui
        row = next(line for line in matrix.splitlines() if line.startswith(f'| `docs {item["cli_command"]}` |'))
        assert item["reason"].strip() in row


def test_committed_matrix_is_the_regenerated_output():
    assert MATRIX.read_text(encoding="utf-8") == _load_regen().render(), "run: uv run python tools/regen_parity_matrix.py"


@pytest.mark.skip(reason=f"S7.2 must remove this skip once these UI/API gaps close: {sorted(PENDING_UI | API_PROOF_GAPS)}")
def test_no_pending_ui_rows_remain():
    assert not PENDING_UI and not API_PROOF_GAPS
