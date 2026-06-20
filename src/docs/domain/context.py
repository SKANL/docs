from __future__ import annotations

from dataclasses import dataclass, field

from docs.domain.models.template import Topic

_PROSE_MARKER = "(texto)"


def is_prose_topic(topic: Topic) -> bool:
    return topic.multiline or not topic.fields


def missing_fields(topic: Topic, answer: str | dict[str, str] | None) -> list[str]:
    if is_prose_topic(topic):
        text = answer if isinstance(answer, str) else ""
        if topic.required and not (answer and text.strip()):
            return [_PROSE_MARKER]
        return []

    values: dict[str, str] = answer if isinstance(answer, dict) else {}
    missing: list[str] = []
    for f in topic.fields:
        required = f.required if f.model_fields_set and "required" in f.model_fields_set else topic.required
        value = values.get(f.key, "")
        if required and not value.strip():
            missing.append(f.label)
    return missing


@dataclass(frozen=True)
class TopicStatus:
    id: str
    title: str
    required: bool
    exists: bool
    missing: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "required": self.required,
            "exists": self.exists,
            "missing": self.missing,
            "complete": self.complete,
        }
