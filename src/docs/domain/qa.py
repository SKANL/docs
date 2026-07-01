from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.review import ReviewResult


def ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved == child_resolved or parent_resolved not in child_resolved.parents:
        raise RuntimeError(f"Ruta insegura para limpieza recursiva: {child_resolved}")


def render_qa_report(
    docx_path: Path,
    pdf_path: Path,
    pngs: list[Path],
    audit: ReviewResult,
    document_audits: list[dict[str, Any]] | None = None,
) -> str:
    document_audits = document_audits or []
    lines = [
        "# QA DOCX",
        "",
        f"- DOCX: {docx_path}",
        f"- PDF: {pdf_path} ({pdf_path.stat().st_size if pdf_path.exists() else 0} bytes)",
        f"- PNG pages: {len(pngs)}",
        "- Índice dinámico: el campo TOC se actualiza al abrir el DOCX en Word o con Ctrl+A y F9; el render de QA puede mostrar el texto de actualización pendiente.",
        "",
        "## Auditoría de formato",
        "",
        audit.to_markdown(),
        "",
        "## Auditorías Documents",
        "",
    ]
    if document_audits:
        for item in document_audits:
            marker = "OK" if item.get("ok") else "FAIL"
            lines.append(f"- {marker} `{item.get('name')}`: {item.get('report', '')}")
    else:
        lines.append("- No ejecutadas.")
    lines.extend(
        [
            "",
            "## Checklist visual manual",
            "",
            "- [ ] Sin texto cortado o solapado.",
            "- [ ] Portada preservada y páginas no-portada con márgenes de 2.5 cm.",
            "- [ ] Paginación visible desde Introducción.",
            "- [ ] Títulos en jerarquía institucional.",
            "- [ ] Tablas sin colores y sólo líneas horizontales.",
            "- [ ] Figuras con caption inferior.",
        ]
    )
    return "\n".join(lines)
