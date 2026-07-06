# src/docs/domain/docx_structure.py
from __future__ import annotations

from typing import Any

EMU_PER_CM = 360000

DEFAULT_RESPONSIBILITY_TEXT = (
    "Aunque este trabajo hubiere servido para obtener el Grado de Técnico Superior Universitario en Desarrollo de Software "
    "Multiplataforma y hubiere sido aprobado por la Dirección de Tecnologías de la Información y Comunicación, sólo su autor "
    "es responsable de las doctrinas en él emitida"
)

_MARGIN_KEYS = ("top", "right", "bottom", "left")


def structure_parts(config: dict[str, Any]) -> list[dict[str, Any]]:
    structure = config.get("structure")
    if structure:
        return structure
    prelim = config.get("preliminaries", {})
    parts: list[dict[str, Any]] = [{"type": "cover_from_template"}]
    if prelim.get("blank_page", {}).get("enabled"):
        parts.append({"type": "blank_page"})
    if prelim.get("responsibility_page", {}).get("enabled"):
        parts.append(
            {
                "type": "fixed_text_page",
                "text": prelim["responsibility_page"].get("text", DEFAULT_RESPONSIBILITY_TEXT),
            }
        )
    roman = prelim.get("roman_pagination", {})
    body_start = prelim.get("body_pagination_start", {})
    parts.append(
        {
            "type": "sections",
            "preliminary_pagination": (
                {"format": "lowerRoman", "start": int(prelim.get("blank_page", {}).get("start", 2))}
                if roman.get("enabled")
                else {}
            ),
            "body_restart_section": body_start.get("section_id", ""),
            "body_pagination": {
                "format": body_start.get("format", "decimal"),
                "start": int(body_start.get("start", 1)),
            },
        }
    )
    return parts


def resolve_part_text(config: dict[str, Any], part: dict[str, Any]) -> str:
    if part.get("text"):
        return part["text"]
    field = part.get("text_field")
    if field:
        return str(config.get("project", {}).get(field, ""))
    return ""


def non_cover_margin_emu(config: dict[str, Any]) -> dict[str, int]:
    margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
    expected: dict[str, int] = {}
    for key in _MARGIN_KEYS:
        value = margins.get(key)
        if isinstance(value, (int, float)):
            expected[key] = int(round(float(value) * EMU_PER_CM))
    return expected


def margins_match(actual: dict[str, int], expected: dict[str, int], tolerance: int = 10000) -> bool:
    return all(
        key in actual and key in expected and abs(actual[key] - expected[key]) <= tolerance
        for key in expected
    )


def sections_index(parts: list[dict[str, Any]]) -> int:
    """Locate the "sections" part within an assembled document's ordered
    part list. Single shared implementation (PR8 de-duplication,
    document-pipeline spec: `Single _sections_index implementation`) --
    `DocxRendererAdapter` (application layer) and `PythonDocxAssemblyAdapter`
    (infrastructure layer) each used to carry their own byte-identical
    private copy of this exact logic; both now call this domain function."""
    return next((i for i, p in enumerate(parts) if p.get("type") == "sections"), len(parts))
