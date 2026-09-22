"""Compatibility helpers for CLI command adapters."""

from __future__ import annotations

import json
from typing import Any

import typer

from docs.composition import WORKSPACE_CONFIG_FILENAME, ApplicationComposition, build_workspace, resolve_renderer

__all__ = ("WORKSPACE_CONFIG_FILENAME", "Deps", "_ctx", "build_workspace", "emit_result", "resolve_renderer")

Deps = ApplicationComposition


def _ctx(ctx: typer.Context) -> tuple[ApplicationComposition, str]:
    return ctx.obj["deps"], ctx.obj["doc"]


def emit_result(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
