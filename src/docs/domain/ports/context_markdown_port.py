from __future__ import annotations

from typing import Protocol

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema


class ContextMarkdownPort(Protocol):
    def render_requests(
        self,
        schema: ContextSchema,
        statuses_with_values: list[tuple[TopicStatus, str | dict[str, str]]],
        only_topic: str = "",
    ) -> str: ...

    def parse_requests(self, schema: ContextSchema, text: str) -> dict[str, str | dict[str, str]]: ...
