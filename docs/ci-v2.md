# Docs Harness v2 CI

The repository's GitHub Actions workflow is the source of truth for continuous verification. It runs on pushes to `main`, pull requests, a weekly schedule, and manual dispatch.

## Jobs

| Job | Checks |
|---|---|
| `check` | Installs locked dependencies and pandoc; runs `ruff check .`, `mypy`, and pytest with coverage floor `93`. |
| `architecture` | Builds a GitNexus index and runs `tests/architecture` with `ARCHITECTURE_REQUIRE_GRAPH=1`. |
| `toolchains` | Installs optional pandoc, LibreOffice, Java, Mermaid CLI, and resvg; runs unit/integration tests and fails if a tool-dependent test unexpectedly skips. |

The jobs deliberately cover both sides of portability: `check` exercises graceful degradation when optional tools are absent, while `toolchains` exercises the available-tool paths. `doctor` is run in the toolchain job to record the resolved environment.

## Reproduce locally

```bash
uv sync --locked
uv run ruff check .
uv run mypy
uv run pytest -q --cov=src --cov-report=term-missing --cov-fail-under=93
uv run pytest tests/architecture -q
uv run docs doctor
```

For v2 behavior, add focused checks:

```bash
uv run pytest tests/integration/test_v2_source_commands.py tests/integration/test_v2_cli.py tests/integration/test_v2_artifact_commands.py -q
```

Do not make CI depend on an authoring plugin. Install only the declared executable toolchains when a job is intended to exercise optional capability paths; the product runtime remains native and reports missing tools through capabilities and policy.
