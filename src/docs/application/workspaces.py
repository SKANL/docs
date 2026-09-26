"""Persistent multi-workspace registry for local and self-hosted runtimes."""

from __future__ import annotations

import json
import os
import re
from importlib.resources import files
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from docs.domain.workspace_format import (
    WorkspaceFormatError,
    validate_workspace_layout,
    validate_workspace_marker,
    write_workspace_marker,
)


class WorkspaceRegistryError(ValueError):
    pass


class WorkspaceRegistry:
    def __init__(self, registry_path: str | Path | None = None) -> None:
        configured = registry_path or os.environ.get("DOCS_WORKSPACE_REGISTRY")
        self.path = Path(configured or (Path.home() / ".docs" / "workspaces.json")).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            data = self._read()
            return [dict(item) for item in data["workspaces"]]

    def create(self, name: str, root: str | Path) -> dict[str, Any]:
        normalized = self._name(name)
        resolved = Path(root).expanduser().resolve()
        with self._lock:
            data = self._read()
            if any(item["name"] == normalized for item in data["workspaces"]):
                raise WorkspaceRegistryError("workspace_name_conflict")
            try:
                validate_workspace_layout(
                    resolved,
                    resolved / "documents",
                    resolved / "templates",
                )
                if resolved.exists():
                    validate_workspace_marker(resolved)
                else:
                    write_workspace_marker(resolved)
                self._ensure_layout(resolved)
            except WorkspaceFormatError as exc:
                raise WorkspaceRegistryError(str(exc)) from exc
            except OSError as exc:
                raise WorkspaceRegistryError("invalid_workspace_root") from exc
            item = {"id": uuid4().hex, "name": normalized, "root": str(resolved)}
            data["workspaces"].append(item)
            self._write(data)
            self._seed_builtin_templates(resolved)
            return dict(item)

    @staticmethod
    def _seed_builtin_templates(root: Path) -> None:
        """Make every newly-created workspace usable from CLI, API, or Desktop."""
        templates = root / "templates"
        templates.mkdir(parents=True, exist_ok=True)
        if any(templates.glob("*.json")):
            return
        package = files("docs.templates.builtin")
        for entry in package.iterdir():
            if entry.name.endswith(".json"):
                (templates / entry.name).write_text(
                    entry.read_text(encoding="utf-8"), encoding="utf-8"
                )

    def ensure(self, name: str, root: str | Path) -> dict[str, Any]:
        """Return the registered workspace for a root, creating it if needed."""
        resolved = str(Path(root).expanduser().resolve())
        with self._lock:
            for item in self._read()["workspaces"]:
                if str(Path(str(item["root"])).expanduser().resolve()) == resolved:
                    self._validate_root(Path(resolved))
                    self._ensure_layout(Path(resolved))
                    self._seed_builtin_templates(Path(resolved))
                    return dict(item)
        return self.create(name, resolved)

    @staticmethod
    def _ensure_layout(root: Path) -> None:
        """Create the durable workspace boundary before it becomes selectable."""
        for relative in (
            "documents",
            "templates",
            "assets",
            "runs",
            "artifacts",
            "baselines",
            "passports",
            ".docs",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)

    def get(self, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            for item in self._read()["workspaces"]:
                if item["id"] == workspace_id:
                    return dict(item)
        raise WorkspaceRegistryError("workspace_not_found")

    def select(self, workspace_id: str) -> dict[str, Any]:
        item = self.get(workspace_id)
        root = Path(str(item["root"])).expanduser().resolve()
        self._validate_root(root)
        self._ensure_layout(root)
        self._seed_builtin_templates(root)
        with self._lock:
            data = self._read()
            data["active"] = workspace_id
            self._write(data)
        return item

    def rename(self, workspace_id: str, name: str) -> dict[str, Any]:
        normalized = self._name(name)
        with self._lock:
            data = self._read()
            target = next((item for item in data["workspaces"] if item["id"] == workspace_id), None)
            if target is None:
                raise WorkspaceRegistryError("workspace_not_found")
            if any(item["id"] != workspace_id and item["name"] == normalized for item in data["workspaces"]):
                raise WorkspaceRegistryError("workspace_name_conflict")
            target["name"] = normalized
            self._write(data)
            return dict(target)

    def delete(self, workspace_id: str) -> None:
        with self._lock:
            data = self._read()
            remaining = [item for item in data["workspaces"] if item["id"] != workspace_id]
            if len(remaining) == len(data["workspaces"]):
                raise WorkspaceRegistryError("workspace_not_found")
            data["workspaces"] = remaining
            if data.get("active") == workspace_id:
                data["active"] = remaining[0]["id"] if remaining else None
            self._write(data)

    def active(self) -> dict[str, Any] | None:
        with self._lock:
            active = self._read().get("active")
        if not active:
            return None
        item = self.get(active)
        root = Path(str(item["root"])).expanduser().resolve()
        self._validate_root(root)
        self._ensure_layout(root)
        return item

    @staticmethod
    def _validate_root(root: Path) -> None:
        try:
            validate_workspace_layout(root, root / "documents", root / "templates")
            validate_workspace_marker(root)
        except WorkspaceFormatError as exc:
            raise WorkspaceRegistryError(str(exc)) from exc

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"active": None, "workspaces": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkspaceRegistryError("workspace_registry_unreadable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("workspaces", []), list):
            raise WorkspaceRegistryError("workspace_registry_invalid")
        return value

    def _write(self, value: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _name(value: str) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}", value.strip()):
            raise WorkspaceRegistryError("invalid_workspace_name")
        return value.strip()
