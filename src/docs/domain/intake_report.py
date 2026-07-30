# src/docs/domain/intake_report.py
from __future__ import annotations

from typing import Any


def _found_lines(detection: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    roles_by_path = {s["relative_path"]: s for s in manifest.get("sources", [])}
    files = [e for e in detection.get("files", []) if e.get("status") != "empty_dir"]
    lines: list[str] = []
    for entry in sorted(files, key=lambda e: e.get("relative_path", "")):
        rel = entry.get("relative_path", "")
        kind = entry.get("kind", "unknown")
        status = entry.get("status", "")
        source = roles_by_path.get(rel)
        if source is None:
            lines.append(f"- `{rel}` ({kind}) -- {status}")
            continue
        role_status = source.get("role_status") or {}
        role = role_status.get("effective_role") or source.get("proposed_role") or "sin rol"
        confidence = source.get("confidence", "n/d")
        lines.append(f"- `{rel}` ({kind}, rol: {role}, confianza: {confidence}) -- {status}")
    return lines


def _pending_roles(manifest: dict[str, Any]) -> list[dict[str, str]]:
    pending = [
        {"relative_path": s["relative_path"], "gap": s["role_status"]["gap"]}
        for s in manifest.get("sources", [])
        if (s.get("role_status") or {}).get("blocked") and (s.get("role_status") or {}).get("gap")
    ]
    return sorted(pending, key=lambda p: p["relative_path"])


def _checklist(
    pending_roles: list[dict[str, str]],
    context_gaps: list[dict[str, Any]],
    section_gaps: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    ledger_pending: list[str],
) -> list[str]:
    steps: list[str] = []
    for entry in pending_roles:
        steps.append(f"Confirmar el rol de `{entry['relative_path']}` en `_classification-queue.json`.")
    for gap in context_gaps:
        steps.append(f"Completar el contexto `{gap['topic_id']}`: {', '.join(gap.get('missing', []))}.")
    for gap in section_gaps:
        steps.append(f"Redactar en la sección `{gap['section_id']}`: {', '.join(gap.get('missing', []))}.")
    for conflict in conflicts:
        members = ", ".join(conflict.get("members", []))
        steps.append(
            f"Resolver el conflicto de `{conflict['group']}` ({members}) entre las fuentes que lo afirman."
        )
    for item in ledger_pending:
        steps.append(f"Resolver en el ledger: {item}")
    return [f"{index}. {step}" for index, step in enumerate(steps, start=1)]


def render_intake_report(
    detection: dict[str, Any],
    manifest: dict[str, Any],
    gap_report: dict[str, Any],
    ledger_pending: list[str],
) -> str:
    """Pure, deterministic view over already-produced ingest/gap-report
    artifacts (design.md ADR-G: "a view over existing artifacts, not a new
    pipeline stage") -- joins `_detection.json` (`detection`),
    `_source-manifest.json` (`manifest`, including item K's `conflicts`),
    `gap-report.json` (`gap_report`), and `00-fact-ledger.md`'s PENDIENTE
    lines (`ledger_pending`) into one human/agent-readable Found/Missing/
    How-to-finish report. No new source of truth: every fact here is read
    straight from its owning artifact, never re-derived (reuses
    `ContextService.build_gap_report`'s output as-is)."""
    context_gaps = sorted(gap_report.get("context_gaps", []), key=lambda g: g.get("topic_id", ""))
    section_gaps = sorted(gap_report.get("section_gaps", []), key=lambda g: g.get("section_id", ""))
    pending_roles = _pending_roles(manifest)
    conflicts = sorted(manifest.get("conflicts", []), key=lambda c: c.get("group", ""))
    ledger_lines = sorted(ledger_pending)

    lines: list[str] = ["# Informe de ingesta", "", "## Encontrado", ""]
    lines.extend(_found_lines(detection, manifest) or ["No se encontraron fuentes en `inbox/`."])
    lines.append("")

    lines.append("## Faltante")
    lines.append("")
    if context_gaps:
        lines.append("### Contexto sin completar")
        lines.extend(f"- `{g['topic_id']}`: {', '.join(g.get('missing', []))}" for g in context_gaps)
        lines.append("")
    if section_gaps:
        lines.append("### Secciones con contenido obligatorio faltante")
        lines.extend(f"- `{g['section_id']}`: {', '.join(g.get('missing', []))}" for g in section_gaps)
        lines.append("")
    if pending_roles:
        lines.append("### Clasificaciones sin confirmar")
        lines.extend(f"- `{p['relative_path']}`: {p['gap']}" for p in pending_roles)
        lines.append("")
    if conflicts:
        lines.append("### Conflictos entre fuentes (WARN)")
        for conflict in conflicts:
            members = ", ".join(conflict.get("members", []))
            sources = ", ".join(f"`{s}`" for s in conflict.get("sources", []))
            lines.append(f"- grupo `{conflict['group']}`: {sources} afirman miembros distintos ({members}).")
        lines.append("")
    if ledger_lines:
        lines.append("### Ledger pendiente")
        lines.extend(f"- {item}" for item in ledger_lines)
        lines.append("")
    if not (context_gaps or section_gaps or pending_roles or conflicts or ledger_lines):
        lines.append("No se detectaron brechas.")
        lines.append("")

    lines.append("## Cómo terminar")
    lines.append("")
    lines.extend(
        _checklist(pending_roles, context_gaps, section_gaps, conflicts, ledger_lines)
        or ["No quedan pasos pendientes."]
    )
    lines.append("")

    return "\n".join(lines)
