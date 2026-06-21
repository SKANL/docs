# src/docs/domain/section_rendering.py
from __future__ import annotations

import re

from docs.domain.markdown_text import clean_markdown_text
from docs.domain.models.template import SectionContract

_TABLE_ROW_RE = re.compile(r"\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|")
_LEADING_HEADING_RE = re.compile(r"^#\s+.*\n")
_BOLD_SPAN_RE = re.compile(r"\*\*.+?\*\*")


def apply_keyword_bold(markdown: str, terms: list[str]) -> str:
    if not terms:
        return markdown
    placeholders: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        key = f"@@TESINA_BOLD_{len(placeholders)}@@"
        placeholders[key] = match.group(0)
        return key

    protected = _BOLD_SPAN_RE.sub(protect, markdown)
    for term in sorted((term for term in terms if term), key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w@])({re.escape(term)})(?![\w@])", re.IGNORECASE)
        protected = pattern.sub(r"**\1**", protected)
    for key, value in placeholders.items():
        protected = protected.replace(key, value)
    return protected


def render_toc_section(section_title: str) -> str:
    return f"# {section_title}\n\n[[TOC]]\n"


def _summarize_context(context: dict[str, str]) -> list[str]:
    """Resume el contexto a demanda en viñetas `etiqueta: valor` (de tablas) y notas de prosa."""
    lines: list[str] = []
    for _name, text in sorted(context.items()):
        for match in _TABLE_ROW_RE.finditer(text):
            label = clean_markdown_text(match.group(1))
            value = clean_markdown_text(match.group(2))
            if value and label.lower() != "campo":
                lines.append(f"- {label}: {value}")
        prose = _LEADING_HEADING_RE.sub("", text, count=1).strip()
        if "|" not in text and prose:
            heading = text.splitlines()[0].lstrip("# ").strip() if text.startswith("#") else _name
            snippet = prose[:200] + ("…" if len(prose) > 200 else "")
            lines.append(f"- {heading}: {snippet}")
    return lines


def render_contract_scaffold(section_title: str, contract: SectionContract, context: dict[str, str]) -> str:
    lines = [
        f"# {section_title}",
        "",
        "_Borrador inicial generado por el arnés. Esta sección no debe considerarse lista hasta resolver todos los PENDIENTE con evidencia._",
        "",
    ]
    context_lines = _summarize_context(context)
    if context_lines:
        lines.extend(["## Contexto disponible", "", *context_lines, ""])
    required = contract.required_content
    if required:
        lines.extend(["## Pendientes normativos", ""])
        for item in required:
            lines.append(f"- PENDIENTE: documentar {item} con evidencia del ledger, contexto o fuentes.")
        lines.append("")
    if contract.apa_required:
        lines.extend(
            [
                "## Fuentes APA 7",
                "",
                "- PENDIENTE: agregar citas autor-fecha y referencias APA 7 realmente consultadas.",
                "",
            ]
        )
    if contract.references_list:
        lines.extend(
            [
                "PENDIENTE: ordenar alfabéticamente todas las fuentes citadas en el cuerpo conforme a APA 7.",
                "",
            ]
        )
    return "\n".join(lines)


def render_section_draft(
    section_id: str,
    section_title: str,
    contract: SectionContract,
    context: dict[str, str],
    keyword_bold_terms: list[str],
) -> str:
    if contract.toc:
        body = render_toc_section(section_title)
    else:
        body = render_contract_scaffold(section_title, contract, context)
    return apply_keyword_bold(body, keyword_bold_terms)


def _extract_table_value(markdown: str, field: str) -> str:
    pattern = re.compile(rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.*?)\s*\|", re.IGNORECASE)
    match = pattern.search(markdown)
    if not match:
        return ""
    return clean_markdown_text(match.group(1))


def _extract_heading_block(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    block: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(rf"#+\s*\*\*{re.escape(heading)}\*\*", stripped, re.IGNORECASE) or re.fullmatch(
            rf"#+\s*{re.escape(heading)}", stripped, re.IGNORECASE
        ):
            capture = True
            continue
        if capture and stripped.startswith("#"):
            break
        if capture:
            block.append(line)
    return "\n".join(block).strip()
