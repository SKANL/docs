# src/docs/cli/commands/translate_app.py
"""`docs translate` -- translate a document, unconditionally.

There is no content gate here and there must never be one. If a user asks for
a translation, it translates. A block the engine will not or cannot translate
passes through as the original and is COUNTED in the output line; it never
stops the run.
"""
from __future__ import annotations

from pathlib import Path

import typer

from docs.application.translate import UntranslatablePdfError
from docs.cli._shared import _ctx
from docs.infrastructure.translate.pending_slot_translator import pending_path_for

translate_app = typer.Typer()

_MEMORY_DIRNAME = "translations"


@translate_app.command("translate")
def translate(
    ctx: typer.Context,
    source: Path = typer.Argument(..., help="Archivo PDF a traducir."),
    to: str = typer.Option(..., "--to", help="Idioma destino (por ejemplo: es, en, pt)."),
    source_lang: str = typer.Option("auto", "--from", help="Idioma origen; 'auto' lo detecta."),
    output: str = typer.Option("", "--output", help="Ruta de salida del PDF traducido."),
) -> None:
    """Traduce un PDF conservando su maquetación.

    Escribe siempre un documento completo. Los bloques que aún no tienen
    traducción quedan en el idioma original, se cuentan en la salida y se
    listan en el archivo `.pending.json` que acompaña al resultado: rellená
    ese archivo y volvé a ejecutar el mismo comando."""
    deps, _doc = _ctx(ctx)

    if not source.is_file():
        print(f"El archivo no existe: {source}")
        raise typer.Exit(code=1)

    destination = Path(output) if output else source.with_name(f"{source.stem}.{to}.pdf")
    memory_dir = destination.parent / _MEMORY_DIRNAME
    pending_file = pending_path_for(destination)

    service, translator = deps.build_translate_service(memory_dir, pending_file)
    if service is None:
        print("Traducción no disponible: faltan los adaptadores de PDF (pypdfium2 / pdf-inspector).")
        raise typer.Exit(code=1)

    try:
        report = service.translate_pdf(source, destination, to, source_lang)
    except UntranslatablePdfError as error:
        print(f"No se puede traducir: {error}")
        raise typer.Exit(code=1) from error

    written = translator.flush_pending(source_lang, to)

    print(report.to_line())
    print(f"Escrito: {destination}")
    if written is not None:
        print(
            f"Pendiente: {translator.pending_count} bloques por traducir en {written}. "
            "Rellená cada 'translation' y volvé a ejecutar el mismo comando."
        )
