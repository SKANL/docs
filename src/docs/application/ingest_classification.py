# src/docs/application/ingest_classification.py
"""Deciding what an ingested source IS: role, duplicates, conflicts.

Extracted from `IngestService`, which had grown to 34 methods across
1047 lines covering four unrelated concerns. This cluster was already
self-contained -- not one of its seven methods called anything outside
itself -- so it was a class hiding inside another class.

Advisory by contract: every method here PROPOSES (a queue entry, a
warning) and none of them blocks ingest. The agent adjudicates.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from docs.application.ingest_names import CLASSIFICATION_QUEUE_NAME, SOURCE_MANIFEST_NAME
from docs.domain.near_duplicate import DuplicateDecision, SourceDoc, find_duplicates
from docs.domain.ports.ingest_artifact_writer import IngestArtifactWriter
from docs.domain.source_conflict import Conflict, detect_conflicts
from docs.domain.source_role import ROLES as _VALID_ROLES


class SourceClassifier:
    """Role gating, near-duplicate detection and stack-conflict
    detection over an already-built manifest."""

    def __init__(self, writer: IngestArtifactWriter) -> None:
        self.writer = writer

    def resolve_role_gate(
        self, proposed_role: str, confidence: str, confirmed_role: str | None, strict: bool
    ) -> dict[str, Any]:
        # Gating (design.md Decision 4 + item D bound decision, spec:
        # "Confirmed role recorded and enforced" / "High-confidence
        # classification acts automatically" / "Low-confidence
        # classification is held, not guessed"): a confirmed role always
        # routes the source under that role, in any mode. Otherwise, strict
        # mode blocks outright regardless of confidence (Decision 7). In
        # draft mode: `high` confidence ACTS automatically (proposed role
        # admitted, PENDIENTE-style confirmation gap noted); `medium`/`low`
        # confidence is HELD -- never silently defaulted, always queued for
        # explicit confirmation (`inbox/_classification-queue.json`).
        if confirmed_role:
            return {"effective_role": confirmed_role, "blocked": False, "gap": None}
        if strict:
            return {
                "effective_role": None,
                "blocked": True,
                "gap": (
                    f"Rol sin confirmar (propuesto: {proposed_role}); "
                    "bloqueado en modo estricto hasta que se confirme."
                ),
            }
        if confidence == "high":
            return {
                "effective_role": proposed_role,
                "blocked": False,
                "gap": f"PENDIENTE: rol sin confirmar (propuesto: {proposed_role}).",
            }
        return {
            "effective_role": None,
            "blocked": True,
            "gap": (
                f"Rol retenido (confianza {confidence}, propuesto: {proposed_role}); "
                f"confirma en {CLASSIFICATION_QUEUE_NAME} antes de continuar."
            ),
        }

    def read_prior_confirmed_roles(self, inbox_dir: Path) -> dict[str, str]:
        queue_path = inbox_dir / CLASSIFICATION_QUEUE_NAME
        if not queue_path.exists():
            return {}
        try:
            data = json.loads(queue_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        confirmed: dict[str, str] = {}
        for relative_path, entry in data.get("entries", {}).items():
            role = entry.get("confirmed_role")
            if not role:
                continue
            if role not in _VALID_ROLES:
                # A hand-edited `confirmed_role` that is not one of
                # `source_role.classify`'s actual roles (e.g. a section id
                # like "architecture") must never be silently accepted as a
                # confirmation -- it stays pending, same as unconfirmed.
                print(
                    f"WARN: `confirmed_role` inválido para {relative_path} en "
                    f"{CLASSIFICATION_QUEUE_NAME}: '{role}'; valores permitidos: "
                    f"{', '.join(sorted(_VALID_ROLES))}. Se mantiene pendiente.",
                    file=sys.stderr,
                )
                continue
            confirmed[relative_path] = role
        return confirmed

    def write_classification_queue(
        self, inbox_dir: Path, manifest_sources: list[dict[str, Any]]
    ) -> None:
        # `inbox/_classification-queue.json` (design.md Decision 4): the
        # interface where EXTERNAL confirmation enters. Atomic, sort_keys
        # writer via IngestArtifactWriter (Decision 9); entries KEYED BY
        # relative_path.
        entries = {
            source["relative_path"]: {
                "proposed_role": source["proposed_role"],
                "confidence": source["confidence"],
                "signals": source["signals"],
                "confirmed_role": source.get("confirmed_role"),
            }
            for source in manifest_sources
        }
        payload = {"schema": 1, "entries": entries}
        self.writer.write_json(inbox_dir / CLASSIFICATION_QUEUE_NAME, payload)

    # --- Front E: near-duplicate detection (design.md Decision 5) -------

    def find_near_duplicates(
        self, inbox_dir: Path, manifest_sources: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        # A post-ingest pass over the just-produced `ingested/` outputs
        # (spec: document-ingest "Near-Duplicate Detection") -- their
        # content is stable and already deterministic, so this sees final
        # normalized artifacts, not raw heterogeneous sources.
        docs: list[SourceDoc] = []
        for source in manifest_sources:
            output = source.get("output")
            if not output:
                continue
            try:
                text = Path(output).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            docs.append(SourceDoc(relative_path=source["relative_path"], kind=source["kind"], text=text))

        manual_overrides = self._read_manual_duplicate_overrides(inbox_dir)
        fresh_decisions = find_duplicates(docs)
        final_decisions: list[dict[str, Any]] = []
        for decision in fresh_decisions:
            pair_key = frozenset({decision.kept, decision.superseded})
            override = manual_overrides.get(pair_key)
            if override is not None:
                # Reversible (spec: "Duplicate decision is reversible") --
                # a human edited kept/superseded for this pair in the
                # manifest; respect that choice, but keep the FRESH jaccard
                # score/reason (reflects current content).
                final_decisions.append(
                    {
                        "kept": override.kept,
                        "superseded": override.superseded,
                        "jaccard": decision.jaccard,
                        "reason": decision.reason,
                    }
                )
            else:
                final_decisions.append(
                    {
                        "kept": decision.kept,
                        "superseded": decision.superseded,
                        "jaccard": decision.jaccard,
                        "reason": decision.reason,
                    }
                )
        return sorted(final_decisions, key=lambda d: (d["kept"], d["superseded"]))

    def _read_manual_duplicate_overrides(
        self, inbox_dir: Path
    ) -> dict[frozenset[str], DuplicateDecision]:
        manifest_path = inbox_dir / SOURCE_MANIFEST_NAME
        if not manifest_path.exists():
            return {}
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        overrides: dict[frozenset[str], DuplicateDecision] = {}
        for entry in data.get("duplicates", []):
            kept, superseded = entry.get("kept"), entry.get("superseded")
            if not kept or not superseded:
                continue
            overrides[frozenset({kept, superseded})] = DuplicateDecision(
                kept=kept,
                superseded=superseded,
                jaccard=entry.get("jaccard", 0.0),
                reason=entry.get("reason", ""),
            )
        return overrides

    # --- Item K: cross-source conflict detection (design.md ADR-K) --------

    def detect_source_conflicts(self, manifest_sources: list[dict[str, Any]]) -> list[Conflict]:
        # Reads each ingested source's OWN converted text (same `output`
        # field `find_near_duplicates` already reads) -- pure, deterministic
        # detection lives entirely in `domain/source_conflict.py`; I/O
        # (reading the produced .md text) stays here in the application
        # layer.
        texts: list[tuple[str, str]] = []
        for source in manifest_sources:
            output = source.get("output")
            if not output:
                continue
            try:
                text = Path(output).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            texts.append((source["relative_path"], text))
        return detect_conflicts(texts)

    def warn_conflicts(self, conflicts: list[Conflict]) -> None:
        for conflict in conflicts:
            sources = ", ".join(conflict.sources)
            members = ", ".join(conflict.members)
            print(
                f"WARN: fuentes en conflicto ({sources}) afirman miembros distintos de "
                f"`{conflict.group}` ({members}); revisa y resuelve manualmente.",
                file=sys.stderr,
            )
