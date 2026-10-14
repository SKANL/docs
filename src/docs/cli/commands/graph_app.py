"""`docs graph <query>`: the author's view of the document graph (sources, claims, sections, artifacts)."""
from __future__ import annotations

import json

import typer

from docs.application.graph_queries import NAMED_QUERIES, GraphAnswer
from docs.cli._shared import _ctx

graph_app = typer.Typer()

_QUERIES = ", ".join(NAMED_QUERIES)


def _counts(coverage: dict[str, int] | None) -> str:
    return ", ".join(f"{count} {kind}" for kind, count in (coverage or {}).items())


def _render(name: str, answer: GraphAnswer) -> str:
    if answer.no_data:
        return (
            f"Sin datos: la consulta {name} no tenía nada que evaluar ({_counts(answer.coverage)}). "
            "Un resultado vacío no significaría que todo esté bien; ejecuta el pipeline y vuelve a intentarlo."
        )
    if not answer.items:
        return f"Nada encontrado: ninguna coincidencia en {name}. Revisado: {_counts(answer.coverage)}."
    lines = [f"Consulta {name}: {len(answer.items)} resultado(s)"]
    for item in answer.items:
        if "section" in item:  # requirement_coverage: one row per section
            lines.append(f"## {item['section']['id']}")
            lines.append("  cumplidos: " + (", ".join(n["label"] for n in item["satisfied"]) or "-"))
            lines.append("  faltantes: " + (", ".join(n["label"] for n in item["missing"]) or "-"))
        else:
            lines.append(f"- {item['id']}: {item['label']}")
    return "\n".join(lines)


@graph_app.command("graph")
def graph(
    ctx: typer.Context,
    query: str = typer.Argument(..., help=f"Consulta: {_QUERIES}."),
    node_id: str = typer.Option("", "--id", help="Id del nodo (revisión, input o fuente) que piden algunas consultas."),
    as_json: bool = typer.Option(False, "--json", help="Imprime la misma carga que la API."),
) -> None:
    """Consulta la trazabilidad de los documentos: afirmaciones sin evidencia, requisitos sin cubrir, salidas obsoletas...

    Consultas: claims_without_evidence, findings_affected_by_revision (--id),
    artifacts_derived_from_input (--id), unused_references, unmet_requirements,
    stale_artifacts, source_impact (--id) y requirement_coverage. Con `--doc <id>`
    solo se muestra ese documento. "Sin datos" significa que no había nada que
    evaluar; no es lo mismo que "nada encontrado"."""
    deps, doc = _ctx(ctx)
    if query not in NAMED_QUERIES:
        typer.echo(f"Consulta desconocida: {query}. Disponibles: {_QUERIES}.", err=True)
        raise typer.Exit(code=2)
    if NAMED_QUERIES[query] and not node_id:
        typer.echo(f"La consulta {query} requiere --id.", err=True)
        raise typer.Exit(code=2)
    answer = deps.graph_queries.answer(query, node_id or None, document=doc or None)
    if answer.unavailable:
        typer.echo("Grafo no disponible: " + "; ".join(answer.warnings), err=True)
        raise typer.Exit(code=1)
    print(json.dumps(answer.to_payload(), ensure_ascii=False, indent=2) if as_json else _render(query, answer))
