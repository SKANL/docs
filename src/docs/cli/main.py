# src/docs/cli/main.py
from __future__ import annotations

import sys

import typer

from docs.cli._shared import Deps
from docs.cli.commands.asset_app import asset_app
from docs.cli.commands.collection_app import collection_app
from docs.cli.commands.context_app import context_app
from docs.cli.commands.core_app import core_app
from docs.cli.commands.doc_app import doc_app
from docs.cli.commands.docx_app import docx_app
from docs.cli.commands.section_app import section_app
from docs.cli.commands.template_app import template_app

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False, help="Arnés multi-documento para Word.")


@app.callback()
def _root(ctx: typer.Context, doc: str = typer.Option("", "--doc", help="ID del documento (por defecto, el activo).")) -> None:
    # One Deps per invocation; commands read ctx.obj.
    ctx.obj = {"deps": Deps(), "doc": doc}


# Flat concern modules: mounted without a `name` so their commands stay
# top-level (identical surface to the pre-split monolithic main.py).
app.add_typer(core_app)
app.add_typer(collection_app)
app.add_typer(section_app)
app.add_typer(docx_app)

# Named group modules: mounted with the same group name they already had.
app.add_typer(template_app, name="template")
app.add_typer(doc_app, name="doc")
app.add_typer(asset_app, name="asset")
app.add_typer(context_app, name="context")


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, standalone_mode=False)
    except typer.Exit as exc:
        return exc.exit_code
    except Exception as exc:  # legacy main() parity (3945-3947)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
