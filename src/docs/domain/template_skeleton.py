# src/docs/domain/template_skeleton.py
from __future__ import annotations

from typing import Any

# ponytail: the skeleton is data, not a code generator -- one pure function
# returning a plain dict; `template init` (CLI) just serializes it.


def build_template_skeleton(doc_type: str) -> dict[str, Any]:
    """Documented template skeleton with every recognized policy block
    present (design.md Decision 1c, spec: document-template "Template
    Skeleton Generation" / "Optional blocks ship as documented
    placeholders"). Required-to-fill leaves use the literal `"TODO"`
    sentinel (`template_validation.validate_template` treats it as
    incomplete); optional blocks (apa7, preliminaries, format, paths,
    normative) ship as already-valid documented placeholders instead --
    ONLY blocks the author must actually author get a TODO."""
    return {
        "$comment": (
            "Generado por `template init`. Complete cada TODO y ejecute "
            "`template validate` antes de usar esta plantilla en el arnés."
        ),
        "type": doc_type,
        "title": "TODO",
        "project_defaults": {
            "language": "es-MX",
            "voice": "third_person_singular",
            "document_type": doc_type,
        },
        "structure": [
            {"type": "cover_from_template"},
            {
                "type": "sections",
                "body_restart_section": "introduccion",
                "body_pagination": {"format": "decimal", "start": 1},
            },
        ],
        "sections": [
            {"id": "introduccion", "title": "TODO", "order": 10, "required": True},
        ],
        "section_contracts": {
            "introduccion": {
                "title": "TODO",
                "required_content": ["TODO"],
                "evidence_required": False,
                "apa_required": False,
            },
        },
        "context_schema": {
            "topics": [
                {
                    "id": "documento",
                    "title": "TODO",
                    "required": True,
                    "fields": [{"key": "titulo", "label": "TODO", "required": True}],
                },
            ],
        },
        "apa7": {
            "$comment": (
                "OPCIONAL: cambie enabled a true y complete los campos si el "
                "documento usa citas APA 7. Elimine el bloque si no aplica."
            ),
            "enabled": False,
        },
        "preliminaries": {
            "$comment": (
                "OPCIONAL: portada/hoja en blanco/página de responsabilidad/"
                "paginación romana. Elimine el bloque si el documento no "
                "tiene preliminares, o ajuste `body_pagination_start.section_id` "
                "a una sección real declarada en `sections`."
            ),
            "body_pagination_start": {"section_id": "introduccion", "start": 1, "format": "decimal"},
        },
        "format": {
            "$comment": (
                "page_margins_cm.non_cover es OPCIONAL -- decláralo solo si "
                "hay una política de márgenes fija; los valores deben ser "
                "numéricos (cm)."
            ),
            "page_margins_cm": {
                "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5},
            },
        },
        "paths": {
            "$comment": (
                "extracted_dir/extracted_dir_policy son OPCIONALES -- "
                "decláralos solo si el documento consume una carpeta "
                "extracted/ generada por ingest."
            ),
        },
        "normative": {
            "$comment": (
                "OPCIONAL: reglas de redacción normativa propias del "
                "documento (evacuadas del dominio -- design.md Decision 1d). "
                "Vacío por defecto."
            ),
            "normative_source": "",
            "excluded_front_matter": {},
            "first_person_patterns": [],
            "subjective_terms": [],
        },
        "strict_policy": {
            "draft": {
                "allow_pending": True,
                "length_violations": "warning",
                "missing_evidence": "warning",
                "apa_violations": "warning",
            },
            "strict": {
                "allow_pending": False,
                "length_violations": "error",
                "missing_evidence": "error",
                "apa_violations": "error",
            },
        },
    }
