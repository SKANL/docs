# src/docs/domain/document_status.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentStatus:
    """Resumable status summary (design.md item I, ADR-I: aggregate-and-read,
    never persist). Pure data model, mirrors `domain/doctor.py`'s
    `DoctorResult` dual to_dict/to_markdown pattern."""

    doc_id: str
    context_filled: int
    context_total: int
    context_missing_topics: list[str] = field(default_factory=list)
    sections_authored: int = 0
    sections_total: int = 0
    sections_missing: list[str] = field(default_factory=list)
    sections_scaffold: list[str] = field(default_factory=list)
    sections_needs_review: list[str] = field(default_factory=list)
    ingest_ran: bool = False
    classification_pending: int = 0
    figures_count: int = 0
    output_draft_exists: bool = False
    output_final_exists: bool = False
    # Lifecycle-lite (design.md item F, spec: document-lifecycle): the
    # document's user-set state and the latest build version logged under
    # `runs/`. `build_version` is `None` before any assemble run.
    lifecycle: str = "draft"
    build_version: int | None = None
    cover: dict[str, Any] | None = None
    v2_capabilities: dict[str, Any] | None = None
    v2_execution: dict[str, Any] | None = None
    v2_provenance: dict[str, Any] | None = None
    v2_succeeded: bool | None = None
    unsupported_stages: list[str] = field(default_factory=list)
    publication_blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "doc_id": self.doc_id,
            "lifecycle": self.lifecycle,
            "build_version": self.build_version,
            "context": {
                "filled": self.context_filled,
                "total": self.context_total,
                "missing_topics": self.context_missing_topics,
            },
            "sections": {
                "authored": self.sections_authored,
                "total": self.sections_total,
                "missing": self.sections_missing,
                "scaffold": self.sections_scaffold,
                "needs_review": self.sections_needs_review,
            },
            "ingest": {
                "ran": self.ingest_ran,
                "classification_pending": self.classification_pending,
            },
            "figures": {"count": self.figures_count},
            "output": {
                "draft_exists": self.output_draft_exists,
                "final_exists": self.output_final_exists,
            },
        }
        if self.cover is not None:
            result["cover"] = self.cover
        v2 = {
            "capabilities": self.v2_capabilities,
            "execution": self.v2_execution,
            "provenance": self.v2_provenance,
            "succeeded": self.v2_succeeded,
            "unsupported_stages": self.unsupported_stages,
            "publication_blockers": self.publication_blockers,
        }
        if (
            any(
                value is not None
                for value in (self.v2_capabilities, self.v2_execution, self.v2_provenance, self.v2_succeeded)
            )
            or self.unsupported_stages
            or self.publication_blockers
        ):
            result["v2"] = v2
        return result

    def to_markdown(self) -> str:
        lines = [f"# Estado del documento `{self.doc_id}`", ""]
        build_version = self.build_version if self.build_version is not None else "sin compilar"
        lines.append(f"## Ciclo de vida: {self.lifecycle} (build: {build_version})")
        lines.append("")
        lines.append(f"## Contexto: {self.context_filled}/{self.context_total} temas completos")
        if self.context_missing_topics:
            lines.append(f"- Faltan: {', '.join(self.context_missing_topics)}")
        lines.append("")
        lines.append(f"## Secciones: {self.sections_authored}/{self.sections_total} redactadas")
        if self.sections_missing:
            lines.append(f"- Sin crear: {', '.join(self.sections_missing)}")
        if self.sections_scaffold:
            lines.append(f"- Todavía borrador (scaffold): {', '.join(self.sections_scaffold)}")
        if self.sections_needs_review:
            lines.append(f"- Necesitan revisión: {', '.join(self.sections_needs_review)}")
        lines.append("")
        lines.append("## Ingesta")
        lines.append(f"- Ejecutada: {'sí' if self.ingest_ran else 'no'}")
        lines.append(f"- Clasificaciones pendientes de confirmar: {self.classification_pending}")
        lines.append("")
        lines.append(f"## Figuras: {self.figures_count} en el catálogo")
        lines.append("")
        lines.append("## Salida (output)")
        lines.append(f"- Borrador (draft): {'sí' if self.output_draft_exists else 'no'}")
        lines.append(f"- Final: {'sí' if self.output_final_exists else 'no'}")
        if self.cover is not None:
            lines.extend(
                ["", "## Portada", f"- Modo: {self.cover['mode']}", f"- Variante: {self.cover['variant']}"]
            )
            if self.cover["missing_slots"]:
                lines.append(f"- Slots sin resolver: {', '.join(self.cover['missing_slots'])}")
        return "\n".join(lines)
