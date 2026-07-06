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

# Ingest/context-file generation stage names are just as format-agnostic as
# `_PREP_STAGES` -- they never vary by output format (document-render's
# `DocumentRendererPort`), so they stay a module constant here too, rather
# than a caller-supplied parameter like `assemble` (PR8 task 8.1).
_INGEST_STAGES: list[tuple[str, bool]] = [
    ("ingest", True),
    ("build-context-files", True),
    ("build-context-index", True),
]


def pipeline_stage_plan(
    stage_set: str, assemble: list[tuple[str, bool]] | None = None
) -> list[tuple[str, bool]]:
    """Devuelve (nombre, fail_fast) en orden de dependencias para el stage_set dado.

    `prep` and `ingest` stages are format-agnostic and stay defined here.
    `assemble` stages are supplied by the caller (the composition root
    resolves the active `DocumentRendererPort` and passes its
    `stage_plan()`) — this module holds zero format-specific or
    renderer-specific identifiers.
    """
    if stage_set == "prep":
        return list(_PREP_STAGES)
    if stage_set == "ingest":
        return list(_INGEST_STAGES)
    if stage_set in ("assemble", "all"):
        if assemble is None:
            raise ValueError(
                f"pipeline_stage_plan requiere 'assemble' (stages del renderer resuelto) "
                f"para stage_set='{stage_set}'."
            )
        if stage_set == "assemble":
            return list(assemble)
        return list(_PREP_STAGES) + [("review-document", True)] + list(assemble)
    raise ValueError(f"Conjunto de etapas desconocido: {stage_set}. Usa prep, assemble, all o ingest.")
