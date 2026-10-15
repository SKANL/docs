"""A missing optional-at-runtime library costs its feature, not the CLI."""
from __future__ import annotations

import subprocess
import sys
import textwrap

_BLOCK_AND_RUN = textwrap.dedent(
    """
    import sys
    from importlib.abc import MetaPathFinder

    class _Block(MetaPathFinder):
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in {"opendataloader_pdf", "filetype", "pypdfium2"}:
                raise ModuleNotFoundError(name)
            return None

    sys.meta_path.insert(0, _Block())
    from docs.cli.main import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    print("CLI-STARTED")
    """
)


def test_cli_starts_when_pdf_and_filetype_libraries_are_missing() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _BLOCK_AND_RUN], check=False, capture_output=True, text=True, timeout=120
    )

    assert "CLI-STARTED" in completed.stdout, completed.stderr[-2000:]
