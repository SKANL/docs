"""Workspace config, token expansion and path derivation for a resolved document.

Pure logic with no adapters: the composition root only wires, it does not
compute. Kept out of `composition.py` so config rules can change without
touching wiring.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from docs.application.ingest import SOURCE_MANIFEST_NAME
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace
from docs.template_compiler import TemplateCompilationError, TemplateIR, compile_template

logger = logging.getLogger(__name__)

WORKSPACE_CONFIG_FILENAME = "docs.config.json"


def load_workspace_config() -> dict[str, str] | None:
    """Best-effort read of `docs.config.json` in cwd (spec: workspace-config
    "Persisted Workspace Configuration"). A malformed file WARNs to stderr and
    is ignored — fail-open, never bricks a command (design.md item A)."""
    path = Path.cwd() / WORKSPACE_CONFIG_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"WARN: no se pudo leer {path}, se ignora ({exc}).", file=sys.stderr)
        return None


def rules_manifest_state(config: dict[str, Any]) -> tuple[bool, int]:
    """Read the rules manifest without constructing the alternate pipeline."""
    try:
        path = Path(config["paths"]["rules_manifest"])
        return (True, path.stat().st_size) if path.is_file() else (False, 0)
    except (KeyError, OSError, TypeError):
        return False, 0


def try_compile_template(template: Template) -> TemplateIR | None:
    """Compile the template IR; return None (and warn) when it does not compile.

    A template that does not compile still resolves as its source template, so
    the document stays usable; the warning keeps that degradation visible."""
    try:
        return compile_template(template)
    except TemplateCompilationError as exc:
        logger.warning("template IR unavailable, using the source template: %s", exc)
        return None


def apply_confirmed_placements(parts: list[dict[str, Any]], inbox_dir: Path) -> list[dict[str, Any]]:
    """CRITICAL-1 fix (PR5 verify): the WRITE half of design.md Decision 6a's
    "confirmation lands TWICE" -- reads confirmed placements' precomputed
    `structure_part` from `inbox/_source-manifest.json` (IngestService's own
    output, `route_and_queue_assets`) and splices them into the resolved
    document structure, so the EXISTING `structure_parts()` consumer
    (docx_assembly.py/doctor.py) can actually see them. No new consumer.
    """
    manifest_path = inbox_dir / SOURCE_MANIFEST_NAME
    if not manifest_path.exists():
        return parts
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return parts
    confirmed_parts = [
        placement["structure_part"]
        for placement in manifest.get("placements", [])
        if placement.get("structure_part")
    ]
    if not confirmed_parts:
        return parts
    parts = list(parts)
    for part in confirmed_parts:
        if part.get("type") == "cover_from_asset":
            # A confirmed cover REPLACES whatever cover the template already
            # declared -- cover_from_template OR its own cover_from_asset (the
            # real reporte-estadia-tic declares the latter, and filtering only
            # cover_from_template left the document with two covers). There is
            # exactly one cover.
            parts = [
                p
                for p in parts
                if p.get("type") not in ("cover_from_template", "cover_from_asset")
            ]
            parts.insert(0, part)
        else:
            # embed_docx ("back" kind) -- appended after the sections part.
            parts.append(part)
    return parts


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def expand_tokens(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: expand_tokens(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_tokens(v, tokens) for v in value]
    if isinstance(value, str):
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
    return value


def standard_tokens(workspace: Workspace, doc_root: Path) -> dict[str, str]:
    # Harness-global tokens have no library equivalent (Judgment call 2);
    # expand only what the workspace/cwd can supply. Unresolved tokens stay literal.
    # `{doc_root}`/`{inbox_dir}` are per-document: a template's source paths point
    # into the document's OWN inbox, since every document is an isolated workspace
    # and its material arrives by being dropped there.
    return {
        "{templates_dir}": str(workspace.templates_dir.resolve()),
        "{documents_dir}": str(workspace.documents_dir.resolve()),
        "{doc_root}": str(doc_root.resolve()),
        "{inbox_dir}": str((doc_root / "inbox").resolve()),
        "{cwd}": str(Path.cwd().resolve()),
    }


def computed_paths(doc_root: Path) -> dict[str, str]:
    # Persist absolute paths.  SourcePipeline receives the document root as
    # its resolution base; relative values here would otherwise be prefixed a
    # second time (documents/<id>/documents/<id>/inbox).
    doc_root = doc_root.resolve()
    sections = doc_root / "sections"
    context = doc_root / "context"
    corrections = doc_root / "corrections"
    output = doc_root / "output"
    return {
        "context_dir": str(context),
        "context_index": str(context / "index.json"),
        "context_requests": str(context / "_requests.md"),
        "assets_dir": str(doc_root / "assets"),
        "inbox_dir": str(doc_root / "inbox"),
        "sections_dir": str(sections),
        "source_manifest": str(sections / "source-manifest.json"),
        "issues_manifest": str(sections / "issues-manifest.json"),
        "code_evidence_manifest": str(sections / "code-evidence-manifest.json"),
        "rules_manifest": str(sections / "manual-rules.json"),
        "fact_ledger": str(sections / "00-fact-ledger.md"),
        "corrections_inbox_dir": str(corrections / "inbox"),
        "corrections_applied": str(corrections / "applied.json"),
        "output_draft_dir": str(output / "draft"),
        "output_final_dir": str(output / "final"),
        "output_qa_dir": str(output / "qa"),
        "runs_dir": str(doc_root / "runs"),
    }
