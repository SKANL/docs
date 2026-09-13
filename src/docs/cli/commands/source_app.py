"""Public source pipeline command namespace."""
from __future__ import annotations

import typer

from docs.cli.commands.v2_app import _run_source_command

source_app = typer.Typer(help="Source ingestion and normalization commands.")


@source_app.command("ingest")
def source_ingest(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Ingest source material through the native v2 source stage."""
    _run_source_command(ctx, "ingest", json_output)
