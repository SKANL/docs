from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path


def resolve_workspace_roots(
    config: Mapping[str, str] | None,
    env: Mapping[str, str],
    cwd_defaults: tuple[Path, Path],
) -> tuple[Path, Path]:
    """Resolve `(documents_dir, templates_dir)` per-field with strict
    precedence config file -> env var -> built-in default (spec:
    workspace-config "Config Precedence Resolution"). Pure, no I/O — callers
    parse the config file and read `os.environ` before calling this."""
    config = config or {}
    default_documents, default_templates = cwd_defaults
    documents_dir = config.get("documents_dir") or env.get("DOCS_DOCUMENTS_DIR") or str(default_documents)
    templates_dir = config.get("templates_dir") or env.get("DOCS_TEMPLATES_DIR") or str(default_templates)
    return Path(documents_dir), Path(templates_dir)
