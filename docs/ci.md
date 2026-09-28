# Docs Harness X20 CI

The repository's GitHub Actions workflows are the source of truth for continuous verification. They run on pushes to `main`, pull requests, and manual dispatch.

## Jobs

| Job | Checks |
|---|---|
| `quality` | Installs Pandoc and Python 3.11 with `uv`, synchronizes locked dependencies, then runs linting, type checks, the Tauri sidecar contract, tests, project coverage, and differential coverage. Project coverage must meet `86%`; differential coverage against `origin/main` must meet `70%`. |
| `toolchains` | Installs the optional LibreOffice, Java, Poppler, Mermaid, resvg, and Node toolchain, records a manifest, and runs the unit and integration suites with that capability set. |
| `architecture` | Builds a GitNexus index and runs `tests/architecture` with `ARCHITECTURE_REQUIRE_GRAPH=1`. |

The `quality` job is the standard project-quality boundary. It invokes `uv python install 3.11`, enforces `--cov-fail-under=86`, and runs `diff-cover coverage.xml --compare-branch=origin/main --fail-under=70`.

The `toolchains` job exercises available optional-tool paths, but it does not run `docs doctor` and does not fail solely because an optional-tool test skips. Its `-rs` output records skip reasons so capability gaps remain visible without turning an optional dependency into a mandatory CI gate.

## Reproduce locally

```bash
uv sync --locked
uv run ruff check src tests
uv run mypy src tools
uv run pytest -q --cov=src --cov-report=xml:coverage.xml --cov-report=term --cov-fail-under=86
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=70
uv run pytest tests/architecture -q
```

For X20 behavior, add focused checks:

```bash
uv run pytest tests/integration/test_v2_source_commands.py tests/integration/test_v2_cli.py tests/integration/test_v2_artifact_commands.py -q
```

Do not make CI depend on an authoring plugin. The optional-toolchain workflow explicitly provisions its capability set; the product runtime remains native and reports missing capabilities through its own policy.

## Desktop contract check

The Linux quality job verifies the Tauri sidecar contract without attempting a
Windows installer build:

```bash
python desktop/scripts/check-sidecar-packaging.py
```

The check is static and deterministic: it validates the configured resource
glob, Rust resource lookup, and the `/health` handshake. Windows-only MSI/NSIS
packaging remains in `desktop/scripts/build-windows.ps1`.
