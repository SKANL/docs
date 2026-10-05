"""Template administration shared by the CLI (`template use/init/create/validate`) and the HTTP API.

Writes stay inside one templates directory; names are single path segments.
"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any
from uuid import uuid4

from docs.domain.review import Issue, ReviewResult
from docs.domain.template_skeleton import build_template_skeleton
from docs.domain.template_validation import validate_template

_BUILTIN_PACKAGE = "docs.templates.builtin"
_CONTROL = re.compile(r"[\x00-\x1f]")


def builtin_names() -> list[str]:
    """Built-in template ids shippable as package data (never a hardcoded filesystem path)."""
    return sorted(
        entry.name.removesuffix(".json")
        for entry in files(_BUILTIN_PACKAGE).iterdir()
        if entry.name.endswith(".json")
    )


def read_builtin(name: str) -> str:
    return files(_BUILTIN_PACKAGE).joinpath(f"{name}.json").read_text(encoding="utf-8")


class TemplateError(Exception):
    """A refused template operation; `code` is a stable machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _invalid_json(message: str) -> ReviewResult:
    return ReviewResult([Issue("error", message, code="template.json.invalid")])


class TemplateService:
    def __init__(self, templates_dir: Path) -> None:
        self.templates_dir = Path(templates_dir)

    def path(self, name: str) -> Path:
        if (
            not name
            or name in {".", ".."}
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or _CONTROL.search(name)
        ):
            raise TemplateError("invalid_template_name", "Invalid template name")
        return self.templates_dir / f"{name}.json"

    def _write(self, name: str, text: str, *, overwrite: bool) -> Path:
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite:
            try:
                with path.open("x", encoding="utf-8") as handle:  # the filesystem decides existence
                    handle.write(text)
            except FileExistsError as exc:
                raise TemplateError("template_exists", f"Ya existe `{path}`. Usa --force para sobrescribir.") from exc
            return path
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def use(self, name: str, *, force: bool = False) -> Path:
        """Copy a built-in template into the templates directory."""
        if name not in builtin_names():
            raise TemplateError("builtin_template_not_found", f"No existe la plantilla integrada `{name}`.")
        return self._write(name, read_builtin(name), overwrite=force)

    def create(self, name: str, *, overwrite: bool = False) -> Path:
        """Write the documented skeleton for `name` (what `template init`/`create` emit)."""
        skeleton = json.dumps(build_template_skeleton(name), ensure_ascii=False, indent=2)
        return self._write(name, skeleton, overwrite=overwrite)

    def validate(self, name: str) -> ReviewResult:
        path = self.path(name)
        if not path.exists():
            raise TemplateError("template_not_found", f"No existe la plantilla `{name}` en {path}.")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return _invalid_json(f"La plantilla no es JSON legible: {exc}")
        return self.validate_raw(raw)

    @staticmethod
    def validate_raw(raw: Any) -> ReviewResult:
        if not isinstance(raw, dict):
            return _invalid_json("La plantilla debe ser un objeto JSON.")
        return ReviewResult(validate_template(raw))
