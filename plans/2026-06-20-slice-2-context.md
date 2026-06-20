# Slice 2 — Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the context subsystem — pure domain completion rules, markdown (de)serialization for topic files and the requests file, a `ContextRepository` port with a JSON/markdown filesystem adapter, an index regenerator, and a `ContextService` use case (`status`, `set`, `show`, `remove`, `ingest`) — replacing the legacy global-state context module while preserving its on-disk format and quirks byte-for-byte.

**Architecture:** Pragmatic hexagonal, same shape as Slice 1. `domain/context.py` is pure (no I/O): completion rules and the `TopicStatus` value object. `infrastructure/persistence/context_markdown.py` is pure string (de)serialization (no filesystem access) so it is unit-testable without `tmp_path`. `infrastructure/persistence/json_context_repository.py` is the only layer that touches the filesystem, implementing `ContextRepository` over `Workspace.doc_root(doc_id)/context/`. `application/context.py` exposes `ContextService`, which composes the repository port with the document repository (to load the active document's `Template`) and orchestrates index regeneration after every mutation.

**Tech Stack:** Python ≥3.11, Pydantic v2 (reusing Slice 1's `Topic`/`Field`/`ContextSchema` models — no new boundary models needed), pytest, regex-based markdown parsing (no markdown library dependency).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. `domain/context.py` imports nothing from `application`, `infrastructure`, or `cli`.
- **Completion rule (verbatim):** a prose topic's value is missing iff `topic.required and not (answer and str(answer).strip())`, with marker `"(texto)"`; a field is missing iff `field.get("required", topic.required) and not value.strip()`. Missing entries returned are field **labels**, never keys. `sensitive` is irrelevant to completion — never filtered or redacted because of it.
- **On-disk JSON parity:** every JSON file (`context/index.json`) is written with `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True)`. The top-level key is literally `"schema"` (not `schema_version`/alias — `index.json` has no reserved-word collision, unlike `registry.json`) and its value is `1`.
- **Ordering:** schema declaration order is preserved everywhere user-visible — `ContextService.status()` results, `index.json`'s `topics` list, and the requests file's topic blocks. Only `by_section` groups are keyed by section id (insertion order = first time each section is seen while walking topics in schema order).
- **No redaction:** legacy never redacts `sensitive` fields in topic files, the index, or the requests file. Do not add redaction.
- **Ingest merge never erases:** `merged = {**current, **{k: v for k, v in new.items() if v}}` — an empty incoming answer never overwrites a previously non-empty value.
- **`show` does not validate against the schema** (legacy quirk preserved): it reads the raw topic file by id; raises `FileNotFoundError` only if the file is absent. `set` **does** validate: unknown topic id or unknown field key both raise `ValueError`.
- **`set` on a prose topic ignores `field`** (legacy quirk preserved): the `field=""` parameter is accepted but has no effect on prose topics.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/domain/context.py` — `is_prose_topic`, `missing_fields`, `TopicStatus`.
- `src/docs/infrastructure/persistence/context_markdown.py` — `render_topic`, `parse_topic`, `_extract_field_cell`, `_clean_markdown`, `render_requests`, `parse_requests`.
- `src/docs/domain/ports/context_repository.py` — `ContextRepository` Protocol.
- `src/docs/infrastructure/persistence/json_context_repository.py` — `JsonContextRepository`.
- `src/docs/application/context.py` — `ContextService`.
- `tests/unit/domain/test_context.py`
- `tests/unit/infrastructure/test_context_markdown.py`
- `tests/integration/test_json_context_repository.py`
- `tests/integration/test_context_service.py`

---

### Task 1: Domain completion rules

**Files:**
- Create: `src/docs/domain/context.py`
- Test: `tests/unit/domain/test_context.py`

**Interfaces:**
- Consumes: `Topic`, `Field` (from `docs.domain.models.template`, Slice 1).
- Produces:
  - `is_prose_topic(topic: Topic) -> bool` — `True` iff `topic.multiline or not topic.fields`.
  - `missing_fields(topic: Topic, answer: str | dict[str, str] | None) -> list[str]` — pure completion rule, returns field **labels**.
  - `TopicStatus` frozen dataclass: `id: str, title: str, required: bool, exists: bool, missing: list[str], complete: bool` (computed as `not missing`, not stored independently as a constructor arg — see Step 3) with `to_dict() -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_context.py
from docs.domain.models.template import Field, Topic
from docs.domain.context import is_prose_topic, missing_fields, TopicStatus


def _prose_topic(required: bool = True) -> Topic:
    return Topic(id="intro", title="Introducción", required=required, multiline=True)


def _field_topic(required: bool = True, field_required: bool | None = None) -> Topic:
    field_kwargs = {} if field_required is None else {"required": field_required}
    return Topic(
        id="alumno",
        title="Alumno",
        required=required,
        fields=[Field(key="nombre", label="Nombre", **field_kwargs)],
    )


def test_is_prose_topic_true_when_multiline():
    assert is_prose_topic(_prose_topic()) is True


def test_is_prose_topic_true_when_no_fields():
    topic = Topic(id="x", title="X", multiline=False, fields=[])
    assert is_prose_topic(topic) is True


def test_is_prose_topic_false_when_fields_and_not_multiline():
    assert is_prose_topic(_field_topic()) is False


def test_prose_required_and_empty_is_missing():
    assert missing_fields(_prose_topic(required=True), None) == ["(texto)"]


def test_prose_required_and_blank_is_missing():
    assert missing_fields(_prose_topic(required=True), "   ") == ["(texto)"]


def test_prose_not_required_and_empty_is_not_missing():
    assert missing_fields(_prose_topic(required=False), None) == []


def test_prose_with_text_is_not_missing():
    assert missing_fields(_prose_topic(required=True), "Ya hay contenido.") == []


def test_field_missing_when_required_and_absent_answer():
    topic = _field_topic(required=True)
    assert missing_fields(topic, None) == ["Nombre"]
    assert missing_fields(topic, {}) == ["Nombre"]


def test_field_missing_when_whitespace_only_value():
    topic = _field_topic(required=True)
    assert missing_fields(topic, {"nombre": "   "}) == ["Nombre"]


def test_field_not_missing_when_value_present():
    topic = _field_topic(required=True)
    assert missing_fields(topic, {"nombre": "Ana"}) == []


def test_field_level_required_overrides_topic_level_true_to_false():
    # topic.required=True but field.required=False -> field is NOT forced missing
    topic = _field_topic(required=True, field_required=False)
    assert missing_fields(topic, None) == []


def test_field_level_required_overrides_topic_level_false_to_true():
    # topic.required=False but field.required=True -> field IS forced missing
    topic = _field_topic(required=False, field_required=True)
    assert missing_fields(topic, None) == ["Nombre"]


def test_field_falls_back_to_topic_required_when_unset():
    # field.required unset (default False on the model) still falls back to
    # topic.required via missing_fields' explicit fallback, not the model default.
    topic = _field_topic(required=True, field_required=None)
    assert missing_fields(topic, None) == ["Nombre"]


def test_sensitive_does_not_affect_completion():
    topic = Topic(
        id="alumno", title="Alumno", required=True,
        fields=[Field(key="dni", label="DNI", required=True, sensitive=True)],
    )
    assert missing_fields(topic, {"dni": "12345678"}) == []
    assert missing_fields(topic, None) == ["DNI"]


def test_topic_status_complete_is_derived_from_missing():
    status = TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[])
    assert status.complete is True
    status2 = TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Nombre"])
    assert status2.complete is False


def test_topic_status_to_dict():
    status = TopicStatus(id="alumno", title="Alumno", required=True, exists=False, missing=["Nombre"])
    assert status.to_dict() == {
        "id": "alumno", "title": "Alumno", "required": True,
        "exists": False, "missing": ["Nombre"], "complete": False,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.context`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/context.py
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
```

Note on the field-level override: `Field.required` defaults to `False` on the Pydantic model, so we cannot distinguish "explicitly set to False" from "not set" by value alone. `model_fields_set` (populated by Pydantic v2 on every validated instance) tells us whether `required` was present in the input — use it to decide whether to fall back to `topic.required`. This makes `test_field_falls_back_to_topic_required_when_unset` and both override tests pass simultaneously.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_context.py -v`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/context.py tests/unit/domain/test_context.py
git commit -m "feat(domain): add context completion rules and TopicStatus"
```

---

### Task 2: Topic markdown (de)serialization

**Files:**
- Create: `src/docs/infrastructure/persistence/context_markdown.py`
- Test: `tests/unit/infrastructure/test_context_markdown.py`

**Interfaces:**
- Consumes: `Topic`, `Field` (Slice 1); `is_prose_topic` (Task 1).
- Produces:
  - `render_topic(topic: Topic, values: str | dict[str, str] | None) -> str`
  - `parse_topic(topic: Topic, text: str) -> str | dict[str, str]`
  - `_extract_field_cell(text: str, label: str) -> str` (module-private helper, exact regex below)
  - `_clean_markdown(text: str) -> str` (module-private helper)

Exact prose format: `f"# {title}\n\n{str(values).strip()}\n"` (when `values` is `None`, `str(None)` is `"None"` — guard explicitly: treat `None`/non-str as `""` before formatting, per Step 3 code, so the file body is empty rather than the literal text `"None"`).

Exact field-topic format: line `f"**{topic.title}**"`, blank line, `"| Campo | Información |"`, `"| :---- | :---- |"`, then one line per field `f"| **{f.label}** | {value} |"` (value = the corresponding entry of `values` dict, or `""` if absent), all lines joined by `"\n"` plus a single trailing `"\n"`.

Parse: for prose topics, strip the first line (the `# {title}` heading) and return the remaining text stripped. For field topics, for each field extract its cell via `_extract_field_cell` using the case-insensitive regex `r"\|\s*\*\*" + re.escape(label) + r"\*\*\s*\|\s*(.*?)\s*\|"`, then clean it via `_clean_markdown` (strip backslashes, `**`, `*`, `` ` ``, collapse internal whitespace, then strip `" \t\r\n|"` from both ends). Missing file content or no matching row → `""` for that field (never raises).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_context_markdown.py
from docs.domain.models.template import Field, Topic
from docs.infrastructure.persistence.context_markdown import render_topic, parse_topic


def _prose_topic() -> Topic:
    return Topic(id="intro", title="Introducción", multiline=True)


def _field_topic() -> Topic:
    return Topic(
        id="alumno",
        title="Alumno",
        fields=[
            Field(key="nombre", label="Nombre"),
            Field(key="legajo", label="Legajo"),
        ],
    )


def test_render_prose_topic_exact_format():
    text = render_topic(_prose_topic(), "Hola mundo.")
    assert text == "# Introducción\n\nHola mundo.\n"


def test_render_prose_topic_with_none_values_is_empty_body():
    text = render_topic(_prose_topic(), None)
    assert text == "# Introducción\n\n\n"


def test_render_field_topic_exact_format():
    text = render_topic(_field_topic(), {"nombre": "Ana", "legajo": "123"})
    expected = (
        "**Alumno**\n"
        "\n"
        "| Campo | Información |\n"
        "| :---- | :---- |\n"
        "| **Nombre** | Ana |\n"
        "| **Legajo** | 123 |\n"
    )
    assert text == expected


def test_render_field_topic_missing_values_are_blank_cells():
    text = render_topic(_field_topic(), {"nombre": "Ana"})
    assert "| **Legajo** |  |" in text


def test_parse_prose_topic_strips_heading_and_whitespace():
    text = "# Introducción\n\n  Hola mundo.  \n"
    assert parse_topic(_prose_topic(), text) == "Hola mundo."


def test_parse_field_topic_extracts_each_field():
    text = (
        "**Alumno**\n\n"
        "| Campo | Información |\n"
        "| :---- | :---- |\n"
        "| **Nombre** | Ana |\n"
        "| **Legajo** | 123 |\n"
    )
    assert parse_topic(_field_topic(), text) == {"nombre": "Ana", "legajo": "123"}


def test_parse_field_topic_cleans_markdown_noise():
    text = (
        "| **Nombre** | **Ana** *Garcia* `code` |\n"
        "| **Legajo** | 123 |\n"
    )
    parsed = parse_topic(_field_topic(), text)
    assert parsed["nombre"] == "Ana Garcia code"


def test_parse_field_topic_missing_row_is_empty_string():
    text = "| **Nombre** | Ana |\n"
    parsed = parse_topic(_field_topic(), text)
    assert parsed == {"nombre": "Ana", "legajo": ""}


def test_round_trip_prose():
    original = "Texto con\nvarias líneas."
    rendered = render_topic(_prose_topic(), original)
    assert parse_topic(_prose_topic(), rendered) == original


def test_round_trip_field_topic():
    values = {"nombre": "Ana", "legajo": "123"}
    rendered = render_topic(_field_topic(), values)
    assert parse_topic(_field_topic(), rendered) == values
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_context_markdown.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.context_markdown`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/infrastructure/persistence/context_markdown.py
from __future__ import annotations

import re

from docs.domain.context import is_prose_topic
from docs.domain.models.template import Topic

_FIELD_TABLE_HEADER = "| Campo | Información |"
_FIELD_TABLE_DIVIDER = "| :---- | :---- |"
_NOISE_RE = re.compile(r"[\\*`]")
_WHITESPACE_RE = re.compile(r"\s+")


def render_topic(topic: Topic, values: str | dict[str, str] | None) -> str:
    if is_prose_topic(topic):
        body = values.strip() if isinstance(values, str) else ""
        return f"# {topic.title}\n\n{body}\n"

    data = values if isinstance(values, dict) else {}
    lines = [f"**{topic.title}**", "", _FIELD_TABLE_HEADER, _FIELD_TABLE_DIVIDER]
    for f in topic.fields:
        value = data.get(f.key, "")
        lines.append(f"| **{f.label}** | {value} |")
    return "\n".join(lines) + "\n"


def parse_topic(topic: Topic, text: str) -> str | dict[str, str]:
    if is_prose_topic(topic):
        if not text:
            return ""
        lines = text.split("\n")
        body = "\n".join(lines[1:]) if lines and lines[0].startswith("#") else text
        return body.strip()

    return {f.key: _extract_field_cell(text, f.label) for f in topic.fields}


def _extract_field_cell(text: str, label: str) -> str:
    if not text:
        return ""
    pattern = re.compile(
        r"\|\s*\*\*" + re.escape(label) + r"\*\*\s*\|\s*(.*?)\s*\|",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return _clean_markdown(match.group(1))


def _clean_markdown(text: str) -> str:
    cleaned = _NOISE_RE.sub("", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip(" \t\r\n|")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_context_markdown.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/context_markdown.py tests/unit/infrastructure/test_context_markdown.py
git commit -m "feat(infra): add topic markdown render/parse with byte-exact legacy format"
```

---

### Task 3: ContextRepository port + adapter topic I/O

**Files:**
- Create: `src/docs/domain/ports/context_repository.py`
- Create: `src/docs/infrastructure/persistence/json_context_repository.py`
- Test: `tests/integration/test_json_context_repository.py`

**Interfaces:**
- Consumes: `Workspace` (Slice 1); `Topic` (Slice 1); `render_topic`, `parse_topic` (Task 2).
- Produces:
  - `ContextRepository` Protocol: `read_topic(doc_id: str, topic: Topic) -> str | dict[str, str]`, `read_topic_raw(doc_id: str, topic_id: str) -> str`, `write_topic(doc_id: str, topic: Topic, values: str | dict[str, str]) -> Path`, `topic_exists(doc_id: str, topic_id: str) -> bool`, `remove_topic(doc_id: str, topic_id: str) -> None`. `read_topic_raw` returns the raw file text by bare `topic_id` (no schema lookup, no parsing) and raises `FileNotFoundError` if the file is absent — this is what `ContextService.show` (Task 5) uses to preserve the legacy "show does not validate against the schema" quirk WITHOUT reaching into adapter internals.
  - `JsonContextRepository(workspace: Workspace)` implementing the above. Topic file path: `workspace.doc_root(doc_id) / "context" / f"{topic.id}.md"` (by `topic.id`, not `topic_id`, for `read_topic`/`write_topic`; `topic_exists`/`remove_topic` take a bare `topic_id` string since no `Topic` is available at call sites that only check existence).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_json_context_repository.py
from pathlib import Path

import pytest

from docs.domain.models.template import Field, Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository


@pytest.fixture
def repo(tmp_path: Path) -> JsonContextRepository:
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    (ws.doc_root("alpha")).mkdir(parents=True)
    return JsonContextRepository(ws)


def _prose_topic() -> Topic:
    return Topic(id="intro", title="Introducción", multiline=True)


def _field_topic() -> Topic:
    return Topic(id="alumno", title="Alumno", fields=[Field(key="nombre", label="Nombre")])


def test_write_then_read_prose_topic_roundtrip(repo):
    repo.write_topic("alpha", _prose_topic(), "Hola mundo.")
    assert repo.read_topic("alpha", _prose_topic()) == "Hola mundo."


def test_write_then_read_field_topic_roundtrip(repo):
    repo.write_topic("alpha", _field_topic(), {"nombre": "Ana"})
    assert repo.read_topic("alpha", _field_topic()) == {"nombre": "Ana"}


def test_read_missing_topic_returns_empty(repo):
    assert repo.read_topic("alpha", _prose_topic()) == ""
    assert repo.read_topic("alpha", _field_topic()) == {"nombre": ""}


def test_write_topic_returns_path(repo):
    path = repo.write_topic("alpha", _prose_topic(), "x")
    assert path == repo.workspace.doc_root("alpha") / "context" / "intro.md"
    assert path.exists()


def test_topic_exists_true_and_false(repo):
    assert repo.topic_exists("alpha", "intro") is False
    repo.write_topic("alpha", _prose_topic(), "x")
    assert repo.topic_exists("alpha", "intro") is True


def test_remove_topic_deletes_file(repo):
    repo.write_topic("alpha", _prose_topic(), "x")
    repo.remove_topic("alpha", "intro")
    assert repo.topic_exists("alpha", "intro") is False


def test_remove_topic_no_error_if_absent(repo):
    repo.remove_topic("alpha", "ghost")  # must not raise


def test_read_topic_raw_returns_text(repo):
    repo.write_topic("alpha", _prose_topic(), "Hola mundo.")
    assert repo.read_topic_raw("alpha", "intro") == "# Introducción\n\nHola mundo.\n"


def test_read_topic_raw_missing_raises(repo):
    with pytest.raises(FileNotFoundError):
        repo.read_topic_raw("alpha", "ghost")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_json_context_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.json_context_repository`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/context_repository.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from docs.domain.models.template import Topic


class ContextRepository(Protocol):
    def read_topic(self, doc_id: str, topic: Topic) -> str | dict[str, str]: ...
    def read_topic_raw(self, doc_id: str, topic_id: str) -> str: ...
    def write_topic(self, doc_id: str, topic: Topic, values: str | dict[str, str]) -> Path: ...
    def topic_exists(self, doc_id: str, topic_id: str) -> bool: ...
    def remove_topic(self, doc_id: str, topic_id: str) -> None: ...
```

```python
# src/docs/infrastructure/persistence/json_context_repository.py
from __future__ import annotations

from pathlib import Path

from docs.domain.models.template import Topic
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.context_markdown import parse_topic, render_topic


class JsonContextRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def _context_dir(self, doc_id: str) -> Path:
        return self.workspace.doc_root(doc_id) / "context"

    def _topic_path(self, doc_id: str, topic_id: str) -> Path:
        return self._context_dir(doc_id) / f"{topic_id}.md"

    def read_topic(self, doc_id: str, topic: Topic) -> str | dict[str, str]:
        path = self._topic_path(doc_id, topic.id)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return parse_topic(topic, text)

    def read_topic_raw(self, doc_id: str, topic_id: str) -> str:
        path = self._topic_path(doc_id, topic_id)
        if not path.exists():
            raise FileNotFoundError(f"Context file for topic `{topic_id}` does not exist ({path}).")
        return path.read_text(encoding="utf-8")

    def write_topic(self, doc_id: str, topic: Topic, values: str | dict[str, str]) -> Path:
        path = self._topic_path(doc_id, topic.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_topic(topic, values), encoding="utf-8")
        return path

    def topic_exists(self, doc_id: str, topic_id: str) -> bool:
        return self._topic_path(doc_id, topic_id).exists()

    def remove_topic(self, doc_id: str, topic_id: str) -> None:
        path = self._topic_path(doc_id, topic_id)
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_json_context_repository.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/context_repository.py src/docs/infrastructure/persistence/json_context_repository.py tests/integration/test_json_context_repository.py
git commit -m "feat(infra): add ContextRepository port and topic file I/O adapter"
```

---

### Task 4: Index regeneration

**Files:**
- Modify: `src/docs/domain/ports/context_repository.py` (add `regenerate_index` to Protocol)
- Modify: `src/docs/infrastructure/persistence/json_context_repository.py` (add `regenerate_index`)
- Test: `tests/integration/test_json_context_repository.py` (add cases)

**Interfaces:**
- Consumes: `ContextSchema` (Slice 1); `TopicStatus` (Task 1).
- Produces: `JsonContextRepository.regenerate_index(doc_id: str, schema: ContextSchema, statuses: list[TopicStatus]) -> Path` — writes both `context/index.json` and `context/index.md`, returns the path to `index.json`.

`index.json` shape (dumped with `ensure_ascii=False, indent=2, sort_keys=True`):
```json
{
  "schema": 1,
  "topics": [
    {"id": "alumno", "title": "Alumno", "file": "alumno.md", "consumed_by": ["introduccion"], "complete": false}
  ],
  "by_section": {"introduccion": ["alumno"]}
}
```
Topic list order = schema declaration order (the order of `statuses`, which callers always build by walking `schema.topics` in order — see Task 5). `by_section` groups each topic id under every section id in its `consumed_by` list, built by iterating topics (schema order) and appending to each section's list in the order first encountered — so within each section's list, topic order also follows schema declaration order.

`index.md` shape: a Spanish-language human table:
```
| Tema | Archivo | Completo | Consumido por |
| :---- | :---- | :---- | :---- |
| Alumno | alumno.md | no | introduccion |
```
`'sí'`/`'no'` for the `Completo` column; `', '.join(consumed_by) or '—'` for the `Consumido por` column.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_json_context_repository.py
import json

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema


def _schema() -> ContextSchema:
    return ContextSchema(
        topics=[
            Topic(id="alumno", title="Alumno", consumed_by=["introduccion"], fields=[Field(key="nombre", label="Nombre")]),
            Topic(id="intro", title="Introducción", multiline=True, consumed_by=["introduccion", "resumen"]),
        ]
    )


def _statuses() -> list[TopicStatus]:
    return [
        TopicStatus(id="alumno", title="Alumno", required=False, exists=True, missing=["Nombre"]),
        TopicStatus(id="intro", title="Introducción", required=False, exists=False, missing=[]),
    ]


def test_regenerate_index_writes_json_and_md(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    assert path == repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert path.exists()
    assert (path.parent / "index.md").exists()


def test_index_json_schema_key_and_sort_keys(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["schema"] == 1
    # sort_keys=True -> top-level keys alphabetical: by_section, schema, topics
    assert text.index('"by_section"') < text.index('"schema"') < text.index('"topics"')


def test_index_json_topic_order_matches_schema_order(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [t["id"] for t in data["topics"]] == ["alumno", "intro"]
    assert data["topics"][0]["complete"] is False
    assert data["by_section"]["introduccion"] == ["alumno", "intro"]
    assert data["by_section"]["resumen"] == ["intro"]


def test_index_md_contains_human_table(repo):
    path = repo.regenerate_index("alpha", _schema(), _statuses())
    text = (path.parent / "index.md").read_text(encoding="utf-8")
    assert "| Tema | Archivo | Completo | Consumido por |" in text
    assert "| Alumno | alumno.md | no | introduccion |" in text
    assert "| Introducción | intro.md | sí | introduccion, resumen |" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_json_context_repository.py -k regenerate_index -v`
Expected: FAIL with `AttributeError: 'JsonContextRepository' object has no attribute 'regenerate_index'`.

- [ ] **Step 3: Write minimal implementation**

Add to the Protocol in `context_repository.py`:

```python
# add to src/docs/domain/ports/context_repository.py
from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema

# ... inside ContextRepository(Protocol):
    def regenerate_index(
        self, doc_id: str, schema: ContextSchema, statuses: list[TopicStatus]
    ) -> Path: ...
```

Add to `JsonContextRepository`:

```python
# add to src/docs/infrastructure/persistence/json_context_repository.py
import json

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema

# ... inside JsonContextRepository:
    def regenerate_index(
        self, doc_id: str, schema: ContextSchema, statuses: list[TopicStatus]
    ) -> Path:
        context_dir = self._context_dir(doc_id)
        context_dir.mkdir(parents=True, exist_ok=True)
        topics_by_id = {t.id: t for t in schema.topics}

        topic_entries = []
        by_section: dict[str, list[str]] = {}
        for status in statuses:
            topic = topics_by_id[status.id]
            topic_entries.append({
                "id": status.id,
                "title": status.title,
                "file": f"{status.id}.md",
                "consumed_by": list(topic.consumed_by),
                "complete": status.complete,
            })
            for section_id in topic.consumed_by:
                by_section.setdefault(section_id, []).append(status.id)

        index = {"schema": 1, "topics": topic_entries, "by_section": by_section}
        json_path = context_dir / "index.json"
        json_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        md_lines = ["| Tema | Archivo | Completo | Consumido por |", "| :---- | :---- | :---- | :---- |"]
        for status in statuses:
            topic = topics_by_id[status.id]
            complete = "sí" if status.complete else "no"
            consumed = ", ".join(topic.consumed_by) or "—"
            md_lines.append(f"| {status.title} | {status.id}.md | {complete} | {consumed} |")
        md_path = context_dir / "index.md"
        md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        return json_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_json_context_repository.py -v`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/context_repository.py src/docs/infrastructure/persistence/json_context_repository.py tests/integration/test_json_context_repository.py
git commit -m "feat(infra): add context index regeneration (index.json + index.md)"
```

---

### Task 5: ContextService — status / set / show / remove

**Files:**
- Create: `src/docs/application/context.py`
- Test: `tests/integration/test_context_service.py`

**Interfaces:**
- Consumes: `ContextRepository` (Task 3/4); `DocumentRepository` (Slice 1, used only to confirm a document exists — **not** to load its template, since `Template` is passed in explicitly by the caller, matching the `DocumentService.create`-style "caller supplies the template" pattern used in Slice 1 rather than re-deriving it from `doc_id` on every call); `is_prose_topic`, `missing_fields`, `TopicStatus` (Task 1).
- Produces: `ContextService(context_repo: ContextRepository, document_repo: DocumentRepository)` with:
  - `status(doc_id: str, template: Template) -> list[TopicStatus]`
  - `set(doc_id: str, template: Template, topic_id: str, value: str, field: str = "") -> Path`
  - `show(doc_id: str, topic_id: str) -> str`
  - `remove(doc_id: str, template: Template, topic_id: str) -> None`

**Design decision — how `ContextService` gets the `Template`:** the service does not load templates itself. Every method that needs schema knowledge (`status`, `set`, `remove`) takes `template: Template` as an explicit parameter, supplied by the caller (the future CLI layer, which already has `DocumentService.repository.load_template(...)` or can read `document.template` then load it). This mirrors Slice 1's existing pattern where `DocumentService.create` receives `template_name` and resolves it once via the document repository — `ContextService` simply receives the already-resolved `Template` instead of re-resolving it, keeping `ContextService` free of a second dependency on `DocumentRepository.load_template` and free of any caching/staleness concerns. `document_repo` is still injected and used by `status`/`set`/`remove` only to assert `document_repo.exists(doc_id)` is true (raising `DocumentNotFoundError`, reusing Slice 1's exception) before touching the context directory — `show` does not take this check because it must work even when the document repository doesn't know about the doc (legacy quirk: `show` never validates the document either, only the topic file path).

`index` regeneration is orchestrated entirely inside `ContextService` (not inside the repository's mutating methods themselves): `set` and `remove` both call `self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))` as their last step, after the topic write/delete. This keeps `JsonContextRepository.write_topic`/`remove_topic` single-purpose (Task 3) and `regenerate_index` callable standalone (used again by `ingest`, Task 7, which regenerates once at the end of a batch instead of once per topic).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_context_service.py
from pathlib import Path

import pytest

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import ContextSchema, Field, Template, Topic
from docs.domain.ports.document_repository import DocumentNotFoundError
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.application.context import ContextService


def _template() -> Template:
    return Template(
        type="documento-generico",
        title="Doc",
        context_schema=ContextSchema(
            topics=[
                Topic(id="alumno", title="Alumno", required=True, fields=[Field(key="nombre", label="Nombre", required=True)]),
                Topic(id="intro", title="Introducción", required=True, multiline=True),
            ]
        ),
    )


@pytest.fixture
def setup(tmp_path: Path):
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    document_repo = JsonDocumentRepository(ws)
    context_repo = JsonContextRepository(ws)
    # Build the doc workspace manually: Slice 1's create() needs a template file on
    # disk, but this integration test only needs doc_root("alpha") to exist plus a
    # registered document so document_repo.exists("alpha") is True.
    ws.doc_root("alpha").mkdir(parents=True)
    document_repo.write_document(Document(id="alpha", title="Alpha", template="documento-generico"))
    document_repo.register(
        DocumentSummary(id="alpha", title="Alpha", template="documento-generico", created_at="t")
    )
    service = ContextService(context_repo, document_repo)
    return service, _template()


def test_status_reports_missing_for_unanswered_required_topics(setup):
    service, template = setup
    statuses = service.status("alpha", template)
    assert [s.id for s in statuses] == ["alumno", "intro"]
    assert statuses[0].missing == ["Nombre"]
    assert statuses[1].missing == ["(texto)"]


def test_set_field_topic_merges_single_field(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    statuses = service.status("alpha", template)
    assert statuses[0].missing == []


def test_set_unknown_topic_raises(setup):
    service, template = setup
    with pytest.raises(ValueError):
        service.set("alpha", template, "ghost", "x", field="nombre")


def test_set_unknown_field_raises(setup):
    service, template = setup
    with pytest.raises(ValueError):
        service.set("alpha", template, "alumno", "x", field="ghost")


def test_set_prose_topic_ignores_field_arg(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.", field="ignored")
    statuses = service.status("alpha", template)
    assert statuses[1].missing == []


def test_set_regenerates_index(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    index_path = service.context_repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert index_path.exists()


def test_show_returns_raw_text(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    assert "Texto." in service.show("alpha", "intro")


def test_show_missing_topic_raises_file_not_found(setup):
    service, template = setup
    with pytest.raises(FileNotFoundError):
        service.show("alpha", "intro")


def test_show_does_not_validate_against_schema(setup):
    # legacy quirk: show works for a topic id that doesn't exist in the schema,
    # as long as the file happens to exist on disk.
    service, template = setup
    service.context_repo.write_topic("alpha", template.context_schema.topics[1], "manual write")
    assert service.show("alpha", "intro") != ""


def test_remove_deletes_topic_and_no_error_if_absent(setup):
    service, template = setup
    service.set("alpha", template, "intro", "Texto.")
    service.remove("alpha", template, "intro")
    with pytest.raises(FileNotFoundError):
        service.show("alpha", "intro")
    service.remove("alpha", template, "intro")  # second call: no error


def test_status_and_set_raise_for_unknown_document(setup):
    service, template = setup
    with pytest.raises(DocumentNotFoundError):
        service.status("ghost", template)
    with pytest.raises(DocumentNotFoundError):
        service.set("ghost", template, "intro", "x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_context_service.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.application.context`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/context.py
from __future__ import annotations

from pathlib import Path

from docs.domain.context import TopicStatus, is_prose_topic, missing_fields
from docs.domain.models.template import Template, Topic
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.document_repository import DocumentNotFoundError, DocumentRepository


class ContextService:
    def __init__(self, context_repo: ContextRepository, document_repo: DocumentRepository) -> None:
        self.context_repo = context_repo
        self.document_repo = document_repo

    def _require_document(self, doc_id: str) -> None:
        if not self.document_repo.exists(doc_id):
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist.")

    @staticmethod
    def _find_topic(template: Template, topic_id: str) -> Topic:
        for topic in template.context_schema.topics:
            if topic.id == topic_id:
                return topic
        raise ValueError(f"Unknown topic: {topic_id}.")

    def status(self, doc_id: str, template: Template) -> list[TopicStatus]:
        self._require_document(doc_id)
        statuses = []
        for topic in template.context_schema.topics:
            exists = self.context_repo.topic_exists(doc_id, topic.id)
            answer = self.context_repo.read_topic(doc_id, topic)
            statuses.append(
                TopicStatus(
                    id=topic.id,
                    title=topic.title,
                    required=topic.required,
                    exists=exists,
                    missing=missing_fields(topic, answer),
                )
            )
        return statuses

    def set(self, doc_id: str, template: Template, topic_id: str, value: str, field: str = "") -> Path:
        self._require_document(doc_id)
        topic = self._find_topic(template, topic_id)

        if is_prose_topic(topic):
            written_value: str | dict[str, str] = value
        else:
            known_keys = {f.key for f in topic.fields}
            if field not in known_keys:
                raise ValueError(f"Unknown field `{field}` for topic `{topic_id}`.")
            current = self.context_repo.read_topic(doc_id, topic)
            merged = dict(current) if isinstance(current, dict) else {}
            merged[field] = value
            written_value = merged

        path = self.context_repo.write_topic(doc_id, topic, written_value)
        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
        return path

    def show(self, doc_id: str, topic_id: str) -> str:
        # Legacy quirk: show does NOT validate the topic id against the schema;
        # it reads the raw file by id. read_topic_raw raises FileNotFoundError if absent.
        return self.context_repo.read_topic_raw(doc_id, topic_id)

    def remove(self, doc_id: str, template: Template, topic_id: str) -> None:
        self._require_document(doc_id)
        self.context_repo.remove_topic(doc_id, topic_id)
        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
```

Note on `show`: it intentionally does **not** call `_find_topic`/`_require_document` against the schema (legacy quirk) — it reads the raw file by bare `topic_id`. This is served by the `read_topic_raw(doc_id, topic_id) -> str` Protocol method (Task 3), so `ContextService.show` depends only on the port, never on adapter internals — the dependency rule (`application → domain port`) holds, and the no-schema-validation quirk is preserved.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_context_service.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/context.py tests/integration/test_context_service.py
git commit -m "feat(app): add ContextService status/set/show/remove"
```

---

### Task 6: Requests file render + parse

**Files:**
- Modify: `src/docs/infrastructure/persistence/context_markdown.py` (add `render_requests`, `parse_requests`)
- Modify: `src/docs/infrastructure/persistence/json_context_repository.py` (add `read_requests`, `write_requests`)
- Modify: `src/docs/domain/ports/context_repository.py` (add `read_requests`, `write_requests` to Protocol)
- Test: `tests/unit/infrastructure/test_context_markdown.py` (add cases)

**Interfaces:**
- Consumes: `ContextSchema`, `Topic` (Slice 1); `TopicStatus`, `is_prose_topic`, `missing_fields` (Task 1).
- Produces:
  - `render_requests(schema: ContextSchema, statuses_with_values: list[tuple[TopicStatus, str | dict[str, str]]], only_topic: str = "") -> str`
  - `parse_requests(schema: ContextSchema, text: str) -> dict[str, str | dict[str, str]]`
  - `JsonContextRepository.read_requests(doc_id: str) -> str` (raw file text; `""` if absent — used by `ContextService.ingest`, which itself raises `FileNotFoundError` per the spec, so the repository method stays a thin, exception-free file read and the service decides what "absent" means).
  - `JsonContextRepository.write_requests(doc_id: str, text: str) -> Path`. File path: `context/_requests.md`.

`render_requests` only emits topics whose `missing` (from the paired `TopicStatus`) is non-empty, filtered further to `only_topic` when given (empty string means "all pending topics"). For each emitted topic, in schema order:
- Prose: `f"## {topic.title} (\`{topic.id}\`) [prosa]"`, then if `topic.prompt` is truthy a line `f"> {topic.prompt}"`, then a blank line, `"<<<"`, a blank line (the always-blank template body — never pre-filled even if a prior empty value exists), blank line, `">>>"`.
- Field topic: `f"## {topic.title} (\`{topic.id}\`)"`, then one line per field `f"- **{f.label}** (\`{f.key}\`): {current_value}"` where `current_value` comes from the paired value dict (pre-filled with whatever is already on disk, including non-empty values — this lets the user see and edit existing answers).

If no topic has any missing entries, the entire output is the single line `"_No hay campos pendientes._"` (no trailing topic blocks).

`parse_requests` splits the text into topic blocks using header regex `r"^##\s+.*\(\`([^\`]+)\`\)\s*(\[prosa\])?\s*$"` per line (multiline mode), determining the topic's parsed mode by the **presence of a `<<<`/`>>>` delimited block** following the header — not by the `[prosa]` tag (which is cosmetic only). For a `<<<`/`>>>` block, the parsed value is the stripped text between the delimiters. For a non-delimited block, each `- **label** (\`key\`): value` line is captured via `r"^-\s+\*\*.+?\*\*\s+\(\`([^\`]+)\`\):\s*(.*)$"` into a `{key: value}` dict. Topic ids not present in `schema.topics` are ignored (not included in the returned dict, no error raised).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/infrastructure/test_context_markdown.py
from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema
from docs.infrastructure.persistence.context_markdown import render_requests, parse_requests


def _requests_schema() -> ContextSchema:
    return ContextSchema(
        topics=[
            Topic(id="alumno", title="Alumno", required=True, fields=[Field(key="nombre", label="Nombre"), Field(key="legajo", label="Legajo")]),
            Topic(id="intro", title="Introducción", required=True, multiline=True, prompt="Contanos el contexto."),
        ]
    )


def test_render_requests_emits_only_pending_topics():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses)
    assert "## Alumno (`alumno`)" in text
    assert "- **Nombre** (`nombre`): Ana" in text
    assert "- **Legajo** (`legajo`): " in text
    assert "## Introducción (`intro`) [prosa]" in text
    assert "> Contanos el contexto." in text
    assert "<<<" in text and ">>>" in text


def test_render_requests_skips_complete_topics():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[]), {"nombre": "Ana", "legajo": "1"}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses)
    assert "alumno" not in text
    assert "intro" in text


def test_render_requests_respects_only_topic():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    text = render_requests(schema, statuses, only_topic="intro")
    assert "alumno" not in text
    assert "intro" in text


def test_render_requests_nothing_pending():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=[]), {"nombre": "Ana", "legajo": "1"}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=True, missing=[]), "Ya escrito."),
    ]
    text = render_requests(schema, statuses)
    assert text == "_No hay campos pendientes._"


def test_parse_requests_field_and_prose_blocks():
    schema = _requests_schema()
    text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): Ana\n"
        "- **Legajo** (`legajo`): 123\n"
        "\n"
        "## Introducción (`intro`) [prosa]\n"
        "> Contanos el contexto.\n"
        "\n"
        "<<<\n"
        "Texto de respuesta.\n"
        ">>>\n"
    )
    parsed = parse_requests(schema, text)
    assert parsed == {
        "alumno": {"nombre": "Ana", "legajo": "123"},
        "intro": "Texto de respuesta.",
    }


def test_parse_requests_ignores_unknown_topic():
    schema = _requests_schema()
    text = "## Desconocido (`ghost`)\n- **X** (`x`): y\n"
    parsed = parse_requests(schema, text)
    assert parsed == {}


def test_render_then_parse_requests_round_trip():
    schema = _requests_schema()
    statuses = [
        (TopicStatus(id="alumno", title="Alumno", required=True, exists=True, missing=["Legajo"]), {"nombre": "Ana", "legajo": ""}),
        (TopicStatus(id="intro", title="Introducción", required=True, exists=False, missing=["(texto)"]), ""),
    ]
    rendered = render_requests(schema, statuses)
    parsed = parse_requests(schema, rendered)
    assert parsed["alumno"]["nombre"] == "Ana"
    assert parsed["intro"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_context_markdown.py -k requests -v`
Expected: FAIL with `ImportError: cannot import name 'render_requests'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/infrastructure/persistence/context_markdown.py
import re

from docs.domain.context import TopicStatus
from docs.domain.models.template import ContextSchema

_REQUEST_HEADER_RE = re.compile(r"^##\s+.*\(`([^`]+)`\)\s*(\[prosa\])?\s*$", re.MULTILINE)
_REQUEST_FIELD_RE = re.compile(r"^-\s+\*\*.+?\*\*\s+\(`([^`]+)`\):\s*(.*)$", re.MULTILINE)

_NO_PENDING = "_No hay campos pendientes._"


def render_requests(
    schema: ContextSchema,
    statuses_with_values: list[tuple[TopicStatus, str | dict[str, str]]],
    only_topic: str = "",
) -> str:
    topics_by_id = {t.id: t for t in schema.topics}
    blocks: list[str] = []

    for status, value in statuses_with_values:
        if not status.missing:
            continue
        if only_topic and status.id != only_topic:
            continue
        topic = topics_by_id[status.id]

        if is_prose_topic(topic):
            lines = [f"## {topic.title} (`{topic.id}`) [prosa]"]
            if topic.prompt:
                lines.append(f"> {topic.prompt}")
            lines += ["", "<<<", "", ">>>"]
            blocks.append("\n".join(lines))
        else:
            data = value if isinstance(value, dict) else {}
            lines = [f"## {topic.title} (`{topic.id}`)"]
            for f in topic.fields:
                current = data.get(f.key, "")
                lines.append(f"- **{f.label}** (`{f.key}`): {current}")
            blocks.append("\n".join(lines))

    if not blocks:
        return _NO_PENDING
    return "\n\n".join(blocks) + "\n"


def parse_requests(schema: ContextSchema, text: str) -> dict[str, str | dict[str, str]]:
    known_ids = {t.id for t in schema.topics}
    headers = list(_REQUEST_HEADER_RE.finditer(text))
    result: dict[str, str | dict[str, str]] = {}

    for i, header in enumerate(headers):
        topic_id = header.group(1)
        if topic_id not in known_ids:
            continue
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end]

        delim_match = re.search(r"<<<\s*\n(.*?)\n\s*>>>", block, re.DOTALL)
        if delim_match:
            result[topic_id] = delim_match.group(1).strip()
        else:
            fields = {m.group(1): m.group(2).strip() for m in _REQUEST_FIELD_RE.finditer(block)}
            result[topic_id] = fields

    return result
```

Add to the Protocol in `context_repository.py`:

```python
# add to src/docs/domain/ports/context_repository.py
    def read_requests(self, doc_id: str) -> str: ...
    def write_requests(self, doc_id: str, text: str) -> Path: ...
```

Add to `JsonContextRepository`:

```python
# add to src/docs/infrastructure/persistence/json_context_repository.py
    def _requests_path(self, doc_id: str) -> Path:
        return self._context_dir(doc_id) / "_requests.md"

    def read_requests(self, doc_id: str) -> str:
        path = self._requests_path(doc_id)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def write_requests(self, doc_id: str, text: str) -> Path:
        path = self._requests_path(doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_context_markdown.py -v`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/context_markdown.py src/docs/infrastructure/persistence/json_context_repository.py src/docs/domain/ports/context_repository.py tests/unit/infrastructure/test_context_markdown.py
git commit -m "feat(infra): add requests file render/parse and repository read/write"
```

---

### Task 7: ContextService.ingest

**Files:**
- Modify: `src/docs/application/context.py` (add `ingest`)
- Test: `tests/integration/test_context_service.py` (add cases)

**Interfaces:**
- Consumes: `render_requests` (not needed by `ingest` itself — only by a future `elicit`/`request` method outside this slice's required scope; `ingest` only needs `parse_requests`), `parse_requests` (Task 6).
- Produces: `ContextService.ingest(doc_id: str, template: Template) -> list[str]` — reads `context/_requests.md` (raises `FileNotFoundError` if absent), parses it, merges each known topic's new answer with its current on-disk value (`merged = {**current, **{k: v for k, v in new.items() if v}}` for field topics; for prose, the new value replaces the current value only if non-empty after `.strip()`, otherwise the prior value is kept), writes only topics that end up non-empty (prose: `str(value).strip()` truthy; fields: `any(merged.values())`), regenerates the index once after all writes, and returns the list of topic ids it actually wrote (in the order `parse_requests` encountered them, restricted to known topics that were written).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_context_service.py
def test_ingest_writes_known_topics_and_regenerates_index(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    requests_text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): Ana\n"
        "- **Legajo** (`legajo`): 123\n"
        "\n"
        "## Introducción (`intro`) [prosa]\n"
        "\n"
        "<<<\n"
        "Texto nuevo.\n"
        ">>>\n"
    )
    service.context_repo.write_requests("alpha", requests_text)

    written = service.ingest("alpha", template)

    assert set(written) == {"alumno", "intro"}
    statuses = service.status("alpha", template)
    assert statuses[0].missing == []
    assert statuses[1].missing == []
    index_path = service.context_repo.workspace.doc_root("alpha") / "context" / "index.json"
    assert index_path.exists()


def test_ingest_merge_never_erases_existing_value(setup):
    service, template = setup
    service.set("alpha", template, "alumno", "Ana", field="nombre")
    service.set("alpha", template, "alumno", "123", field="legajo")
    requests_text = (
        "## Alumno (`alumno`)\n"
        "- **Nombre** (`nombre`): \n"  # empty answer must NOT erase "Ana"
        "- **Legajo** (`legajo`): \n"
        "\n"
    )
    service.context_repo.write_requests("alpha", requests_text)

    service.ingest("alpha", template)

    value = service.context_repo.read_topic("alpha", template.context_schema.topics[0])
    assert value == {"nombre": "Ana", "legajo": "123"}


def test_ingest_skips_unknown_topic(setup):
    service, template = setup
    service.context_repo.write_requests("alpha", "## Desconocido (`ghost`)\n- **X** (`x`): y\n")
    written = service.ingest("alpha", template)
    assert written == []


def test_ingest_raises_if_requests_file_absent(setup):
    service, template = setup
    with pytest.raises(FileNotFoundError):
        service.ingest("alpha", template)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_context_service.py -k ingest -v`
Expected: FAIL with `AttributeError: 'ContextService' object has no attribute 'ingest'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/application/context.py
from docs.infrastructure.persistence.context_markdown import parse_requests

# ... inside ContextService:
    def ingest(self, doc_id: str, template: Template) -> list[str]:
        self._require_document(doc_id)
        text = self.context_repo.read_requests(doc_id)
        if not text:
            raise FileNotFoundError(f"No pending requests file for document `{doc_id}`.")

        parsed = parse_requests(template.context_schema, text)
        topics_by_id = {t.id: t for t in template.context_schema.topics}
        written: list[str] = []

        for topic_id, new_value in parsed.items():
            topic = topics_by_id.get(topic_id)
            if topic is None:
                continue

            current = self.context_repo.read_topic(doc_id, topic)

            if is_prose_topic(topic):
                new_text = new_value if isinstance(new_value, str) else ""
                merged: str = new_text.strip() if new_text.strip() else (current if isinstance(current, str) else "")
                if str(merged).strip():
                    self.context_repo.write_topic(doc_id, topic, merged)
                    written.append(topic_id)
            else:
                current_fields = current if isinstance(current, dict) else {}
                new_fields = new_value if isinstance(new_value, dict) else {}
                merged_fields = {**current_fields, **{k: v for k, v in new_fields.items() if v}}
                if any(merged_fields.values()):
                    self.context_repo.write_topic(doc_id, topic, merged_fields)
                    written.append(topic_id)

        self.context_repo.regenerate_index(doc_id, template.context_schema, self.status(doc_id, template))
        return written
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_context_service.py -v`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/context.py tests/integration/test_context_service.py
git commit -m "feat(app): add ContextService.ingest with non-erasing merge"
```

---

## Full suite check (run after Task 7)

```bash
uv run pytest -W error -q
```

Expected: all tests pass, zero warnings.

---

## Self-Review

- **Spec coverage (6 legacy behaviors):**
  - `status` ✅ Task 5 (`ContextService.status`, backed by Task 1's `missing_fields`).
  - `elicit`-as-requests ✅ Task 6 (`render_requests` emits only pending topics, pre-fills known field values, supports `only_topic` filtering and the "nothing pending" sentinel).
  - `ingest` ✅ Task 7 (`ContextService.ingest`, non-erasing merge, unknown-topic skip, single index regen).
  - `set` ✅ Task 5 (validates topic/field, merges single field, ignores `field` for prose, regenerates index).
  - `show` ✅ Task 5 (raw read, no schema validation, `FileNotFoundError` on absence).
  - `rm` ✅ Task 5 (`ContextService.remove`, idempotent, regenerates index).
- **Placeholder scan:** no TBD/TODO; every code step shows complete code (no "same as Task N" elisions — `is_prose_topic`/`missing_fields`/`TopicStatus` are defined once in Task 1 and imported by name everywhere else).
- **Type consistency:** `Topic`/`Field`/`ContextSchema`/`Template` (Slice 1) used unchanged; `TopicStatus`, `is_prose_topic`, `missing_fields` (Task 1) imported consistently by the same names through Tasks 2, 5, 6, 7; `ContextRepository` Protocol gains methods incrementally (Tasks 3, 4, 6) and `JsonContextRepository` implements all of them by Task 7; `ContextService` constructor signature (`context_repo`, `document_repo`) fixed in Task 5 and never changed afterward.
- **Design decisions surfaced to the caller:**
  1. `ContextService` does not load templates itself — every method takes `template: Template` as a parameter (Task 5 rationale block), keeping the service free of a second `DocumentRepository.load_template` dependency.
  2. Index regeneration is orchestrated by `ContextService` (`set`, `remove`, `ingest`), not inside the repository's mutating methods — `regenerate_index` stays a standalone, callable-once-per-batch operation, which `ingest` exploits to avoid N index rewrites for N ingested topics.
  3. `show`'s legacy no-schema-validation quirk is served by a dedicated `read_topic_raw(doc_id, topic_id) -> str` Protocol method (Task 3) rather than reaching into adapter internals, so `application` depends only on the port — the dependency rule holds.
  4. Field-level `required` override (Task 1) is resolved via Pydantic v2's `model_fields_set` rather than by sentinel value, because `Field.required` defaults to `False` and cannot otherwise be distinguished from an explicit `False`.
