"""Where a sidecar's workspaces live on disk, and per-root store caching."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Generic, TypeVar

from docs.application.workspaces import WorkspaceRegistry

Store = TypeVar("Store")


class WorkspaceRoots:
    """Where workspaces live: the active root, a root by id, and every known root.

    The one place that reads `registry.resolve(...)["root"]`; `fallback` is the sidecar's own
    workspace, used when no registered workspace is active.
    """

    def __init__(self, registry: WorkspaceRegistry | None, fallback: Path | None) -> None:
        self.registry = registry
        self.fallback = fallback.resolve() if fallback is not None else None

    def active_root(self) -> Path:
        active = self.registry.active() if self.registry is not None else None
        if active is not None:
            return Path(str(active["root"])).resolve()
        if self.fallback is None:
            raise ValueError("no active workspace")
        return self.fallback

    def root_for(self, workspace_id: str | None = None) -> Path:
        if workspace_id and self.registry is not None:
            return Path(str(self.registry.resolve(workspace_id)["root"])).resolve()
        return self.active_root()

    def all_roots(self) -> list[Path]:
        roots = [Path(str(item["root"])).resolve() for item in self.registry.list()] if self.registry is not None else []
        if self.fallback is not None and self.fallback not in roots:
            roots.append(self.fallback)
        return roots


class PerRoot(Generic[Store]):
    """One lazily built store per workspace root, reused for every later lookup."""

    def __init__(self, build: Callable[[Path], Store]) -> None:
        self._build = build
        self._items: dict[str, Store] = {}

    def __call__(self, root: str | Path) -> Store:
        resolved = Path(root).expanduser().resolve()
        key = str(resolved)
        if key not in self._items:
            self._items[key] = self._build(resolved)
        return self._items[key]

    def values(self) -> list[Store]:
        return list(self._items.values())
