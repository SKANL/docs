"""Compatibility helpers for CLI command adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer

from docs.composition import WORKSPACE_CONFIG_FILENAME, ApplicationComposition, build_workspace, resolve_renderer

__all__ = (
    "WORKSPACE_CONFIG_FILENAME",
    "Deps",
    "LazyDependencies",
    "_ctx",
    "build_workspace",
    "emit_result",
    "resolve_renderer",
)

Deps = ApplicationComposition


class LazyDependencies:
    """Construct one application composition on first ordinary command use."""

    def __init__(self, factory: Callable[[], ApplicationComposition]) -> None:
        self._factory = factory
        self._value: ApplicationComposition | None = None

    def resolve(self) -> ApplicationComposition:
        if self._value is None:
            self._value = self._factory()
        return self._value

    def __getattr__(self, name: str) -> Any:
        return getattr(self.resolve(), name)


def _ctx(ctx: typer.Context) -> tuple[ApplicationComposition, str]:
    deps = ctx.obj["deps"]
    if isinstance(deps, LazyDependencies):
        deps = deps.resolve()
    return deps, ctx.obj["doc"]


def emit_result(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
