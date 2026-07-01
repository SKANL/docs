from __future__ import annotations

_PREP_STAGES: list[tuple[str, bool]] = [
    ("doctor", True),
    ("build-rules", False),
    ("review-rules", True),
    ("collect-sources", False),
    ("collect-code-evidence", False),
    ("collect-issues", False),
    ("build-ledger", False),
    ("build-sections", False),
    ("pack-context", False),
]

_ASSEMBLE_STAGES: list[tuple[str, bool]] = [
    ("build-docx", True),
    ("format-audit-docx", True),
    ("qa-docx", True),
]


def pipeline_stage_plan(stage_set: str) -> list[tuple[str, bool]]:
    """Devuelve (nombre, fail_fast) en orden de dependencias para el stage_set dado."""
    if stage_set == "prep":
        return list(_PREP_STAGES)
    if stage_set == "assemble":
        return list(_ASSEMBLE_STAGES)
    if stage_set == "all":
        return list(_PREP_STAGES) + [("review-document", True)] + list(_ASSEMBLE_STAGES)
    raise ValueError(f"Conjunto de etapas desconocido: {stage_set}. Usa prep, assemble o all.")
