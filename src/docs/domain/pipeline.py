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


def pipeline_stage_plan(
    stage_set: str, assemble: list[tuple[str, bool]] | None = None
) -> list[tuple[str, bool]]:
    """Devuelve (nombre, fail_fast) en orden de dependencias para el stage_set dado.

    `prep` stages are format-agnostic and stay defined here. `assemble` stages
    are supplied by the caller (the composition root resolves the active
    `DocumentRendererPort` and passes its `stage_plan()`) — this module holds
    zero format-specific or renderer-specific identifiers.
    """
    if stage_set == "prep":
        return list(_PREP_STAGES)
    if stage_set in ("assemble", "all"):
        if assemble is None:
            raise ValueError(
                f"pipeline_stage_plan requiere 'assemble' (stages del renderer resuelto) "
                f"para stage_set='{stage_set}'."
            )
        if stage_set == "assemble":
            return list(assemble)
        return list(_PREP_STAGES) + [("review-document", True)] + list(assemble)
    raise ValueError(f"Conjunto de etapas desconocido: {stage_set}. Usa prep, assemble o all.")
