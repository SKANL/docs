from __future__ import annotations

from typing import Protocol, runtime_checkable

from docs.domain.models.template import Template


@runtime_checkable
class TemplateRepository(Protocol):
    def load_template(self, name: str) -> Template: ...
    def list_templates(self) -> list[str]: ...
