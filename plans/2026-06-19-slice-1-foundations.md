# Slice 1 — Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the typed core of the new harness — value objects, an injectable workspace, a document repository port with a JSON adapter, and document CRUD use cases — replacing the legacy global-state foundation.

**Architecture:** Pragmatic hexagonal. The `domain` layer is pure (typed value objects, slug rules, the repository *port*). The `infrastructure` layer implements the port over the filesystem with Pydantic parsing at the boundary. The `application` layer exposes a `DocumentService` use case. No global mutable state: a `Workspace` value object is injected.

**Tech Stack:** Python ≥3.11, Pydantic v2 (boundary models), pytest. (Typer CLI wiring lands in a later slice.)

## Global Constraints

- Python requires-python: `>=3.11` (already set in `pyproject.toml`).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. The `domain` package imports nothing from `application`, `infrastructure`, `cli`, or `python-docx`/`subprocess`.
- On-disk parity (must match legacy byte-for-byte after normalization):
  - `registry.json` = `{"schema": 1, "active": "<id>", "documents": [...]}`, written with `json.dumps(..., ensure_ascii=False, indent=2, sort_keys=True)`.
  - `document.json` keys = `id, title, template, project, structure, overrides`, same dump options.
  - Slug pattern = `^[a-z0-9][a-z0-9-]*$`.
- No global mutable module state; inject `Workspace`.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/__init__.py` — package marker.
- `src/docs/domain/__init__.py`
- `src/docs/domain/models/result.py` — `Severity`, `Issue`, `ReviewResult`.
- `src/docs/domain/models/template.py` — `Field`, `Topic`, `Section`, `SectionContract`, `Template`.
- `src/docs/domain/models/document.py` — `Document`, `DocumentPaths`, `DocumentSummary`.
- `src/docs/domain/workspace.py` — `Workspace` value object.
- `src/docs/domain/slug.py` — `validate_slug`, `InvalidSlugError`.
- `src/docs/domain/ports/document_repository.py` — `DocumentRepository` Protocol + `DocumentNotFoundError`, `DocumentExistsError`.
- `src/docs/infrastructure/persistence/json_repository.py` — `JsonDocumentRepository`.
- `src/docs/application/documents.py` — `DocumentService`.
- `tests/unit/...` mirrors the tree; `tests/integration/test_json_repository.py` and `tests/integration/test_document_service.py` use a temp workspace.
- `tests/fixtures/templates/reporte-estadia-tic.json` + `documento-generico.json` — copied verbatim from the legacy `templates/`.

---

### Task 1: Result value objects

**Files:**
- Create: `src/docs/domain/models/result.py`
- Test: `tests/unit/domain/models/test_result.py`

**Interfaces:**
- Produces: `Severity` (str enum: `ERROR="error"`, `WARNING="warning"`); `Issue(severity: Severity, message: str, code: str = "")` with `.to_dict()`; `ReviewResult(issues: list[Issue])` with `.passed: bool` (True iff no `ERROR`) and `.to_dict()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/models/test_result.py
from docs.domain.models.result import Severity, Issue, ReviewResult


def test_review_passes_when_no_errors():
    result = ReviewResult(issues=[Issue(Severity.WARNING, "soft", code="x")])
    assert result.passed is True


def test_review_fails_on_any_error():
    result = ReviewResult(issues=[Issue(Severity.ERROR, "bad", code="y")])
    assert result.passed is False


def test_issue_to_dict_matches_legacy_shape():
    assert Issue(Severity.ERROR, "m", code="c").to_dict() == {
        "severity": "error", "message": "m", "code": "c",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/models/test_result.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.models.result`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/models/result.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: Severity
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity.value, "message": self.message, "code": self.code}


@dataclass(frozen=True)
class ReviewResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity is Severity.ERROR for issue in self.issues)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": [issue.to_dict() for issue in self.issues]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/models/test_result.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/models/result.py tests/unit/domain/models/test_result.py
git commit -m "feat(domain): add result value objects (Issue, ReviewResult, Severity)"
```

---

### Task 2: Slug validation

**Files:**
- Create: `src/docs/domain/slug.py`
- Test: `tests/unit/domain/test_slug.py`

**Interfaces:**
- Produces: `InvalidSlugError(ValueError)`; `validate_slug(doc_id: str) -> None` (raises on invalid). Pattern `^[a-z0-9][a-z0-9-]*$`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_slug.py
import pytest
from docs.domain.slug import validate_slug, InvalidSlugError


@pytest.mark.parametrize("good", ["a", "mi-proyecto", "doc1", "2026-tesis"])
def test_accepts_valid_slugs(good):
    validate_slug(good)  # does not raise


@pytest.mark.parametrize("bad", ["", "-leading", "UPPER", "with space", "under_score", "accént"])
def test_rejects_invalid_slugs(bad):
    with pytest.raises(InvalidSlugError):
        validate_slug(bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_slug.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.slug`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/slug.py
from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class InvalidSlugError(ValueError):
    pass


def validate_slug(doc_id: str) -> None:
    if not _SLUG_RE.match(doc_id):
        raise InvalidSlugError(
            f"Invalid id: `{doc_id}`. Use lowercase letters, digits, and hyphens (e.g. `my-project`)."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_slug.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/slug.py tests/unit/domain/test_slug.py
git commit -m "feat(domain): add slug validation"
```

---

### Task 3: Template models (Pydantic boundary)

**Files:**
- Create: `src/docs/domain/models/template.py`
- Create: `tests/fixtures/templates/reporte-estadia-tic.json` (copy verbatim from `old-se-debe-migrar/tesina/harness/templates/reporte-estadia-tic.json`)
- Create: `tests/fixtures/templates/documento-generico.json` (copy verbatim)
- Test: `tests/unit/domain/models/test_template.py`

**Interfaces:**
- Produces:
  - `Field(key: str, label: str, required: bool = False, sensitive: bool = False)`
  - `Topic(id: str, title: str, required: bool = False, multiline: bool = False, consumed_by: list[str] = [], fields: list[Field] = [], prompt: str = "")`
  - `Section(id: str, title: str, order: int = 0, required: bool = False, optional: bool = False)`
  - `SectionContract(...)` — minimal now: `title: str`, `required_content: list[str] = []`, `evidence_required: bool = False`, `apa_required: bool = False`, `pending_allowed_in_draft: bool = False`, plus `extra="allow"`.
  - `Template(type: str, title: str, project_defaults: dict = {}, structure: list[dict] = [], sections: list[Section] = [], section_contracts: dict[str, SectionContract] = {}, context_schema: ContextSchema, ...)` with `model_config = ConfigDict(extra="allow")` and `Template.from_json(text: str) -> Template`.
- Note: `extra="allow"` is intentional for this slice. Each later slice that *owns* a sub-config (normative, format, apa7…) tightens its sub-model to `extra="forbid"`. Do not model those fields here.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/models/test_template.py
from pathlib import Path
from docs.domain.models.template import Template

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "templates"


def _load(name: str) -> Template:
    return Template.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_parses_sections_and_contracts():
    template = _load("reporte-estadia-tic")
    ids = {s.id for s in template.sections}
    assert "introduccion" in ids
    assert template.section_contracts["resumen"].required_content


def test_parses_context_schema_topics_and_fields():
    template = _load("reporte-estadia-tic")
    alumno = next(t for t in template.context_schema.topics if t.id == "alumno")
    assert alumno.required is True
    assert any(f.key == "nombre" and f.required for f in alumno.fields)
    assert "introduccion" in alumno.consumed_by


def test_both_templates_load():
    assert _load("reporte-estadia-tic").type == "reporte-estadia-tic"
    assert _load("documento-generico").type == "documento-generico"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/models/test_template.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.models.template`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/models/template.py
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Field(BaseModel):
    model_config = ConfigDict(extra="allow")
    key: str
    label: str
    required: bool = False
    sensitive: bool = False


class Topic(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    required: bool = False
    multiline: bool = False
    consumed_by: list[str] = []
    fields: list[Field] = []
    prompt: str = ""


class ContextSchema(BaseModel):
    model_config = ConfigDict(extra="allow")
    topics: list[Topic] = []


class Section(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    order: int = 0
    required: bool = False
    optional: bool = False


class SectionContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    required_content: list[str] = []
    evidence_required: bool = False
    apa_required: bool = False
    pending_allowed_in_draft: bool = False


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    project_defaults: dict = {}
    structure: list[dict] = []
    sections: list[Section] = []
    section_contracts: dict[str, SectionContract] = {}
    context_schema: ContextSchema = ContextSchema()

    @classmethod
    def from_json(cls, text: str) -> "Template":
        return cls.model_validate_json(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/models/test_template.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/models/template.py tests/unit/domain/models/test_template.py tests/fixtures/templates/
git commit -m "feat(domain): add typed Template models with Pydantic boundary parsing"
```

---

### Task 4: Document model + Workspace value object

**Files:**
- Create: `src/docs/domain/models/document.py`
- Create: `src/docs/domain/workspace.py`
- Test: `tests/unit/domain/test_workspace.py`

**Interfaces:**
- Produces:
  - `Workspace(documents_dir: Path, templates_dir: Path)` (frozen dataclass) with properties `registry_path -> Path` (= `documents_dir / "registry.json"`) and method `doc_root(doc_id: str) -> Path` (= `documents_dir / doc_id`).
  - `Document(id: str, title: str, template: str, project: dict = {}, structure: list[dict] = [], overrides: dict = {})` (Pydantic, `extra="allow"`) with `to_json() -> str` (dumps with `indent=2, ensure_ascii=False, sort_keys=True`).
  - `DocumentSummary(id: str, title: str, template: str, created_at: str)` (Pydantic).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_workspace.py
from pathlib import Path
from docs.domain.workspace import Workspace
from docs.domain.models.document import Document


def test_workspace_derives_registry_and_doc_root():
    ws = Workspace(documents_dir=Path("/w/documents"), templates_dir=Path("/w/templates"))
    assert ws.registry_path == Path("/w/documents/registry.json")
    assert ws.doc_root("alpha") == Path("/w/documents/alpha")


def test_document_to_json_is_sorted_and_unicode():
    doc = Document(id="a", title="Área", template="documento-generico")
    text = doc.to_json()
    assert text.index('"id"') < text.index('"title"')  # sort_keys
    assert "Área" in text  # ensure_ascii=False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_workspace.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.workspace`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/workspace.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    documents_dir: Path
    templates_dir: Path

    @property
    def registry_path(self) -> Path:
        return self.documents_dir / "registry.json"

    def doc_root(self, doc_id: str) -> Path:
        return self.documents_dir / doc_id
```

```python
# src/docs/domain/models/document.py
from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict


class Document(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    template: str
    project: dict = {}
    structure: list[dict] = []
    overrides: dict = {}

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(), ensure_ascii=False, indent=2, sort_keys=True
        )


class DocumentSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    template: str
    created_at: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_workspace.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/workspace.py src/docs/domain/models/document.py tests/unit/domain/test_workspace.py
git commit -m "feat(domain): add Workspace value object and Document model"
```

---

### Task 5: DocumentRepository port + JSON adapter

**Files:**
- Create: `src/docs/domain/ports/document_repository.py`
- Create: `src/docs/infrastructure/persistence/json_repository.py`
- Test: `tests/integration/test_json_repository.py`

**Interfaces:**
- Consumes: `Workspace`, `Document`, `DocumentSummary`, `Template` (Task 3/4).
- Produces:
  - Exceptions `DocumentNotFoundError(Exception)`, `DocumentExistsError(Exception)`.
  - `DocumentRepository` Protocol: `load_registry() -> Registry`, `save_registry(Registry) -> None`, `active_id() -> str`, `set_active(str) -> None`, `register(summary: DocumentSummary) -> None`, `read_document(doc_id: str) -> Document`, `write_document(Document) -> None`, `exists(doc_id: str) -> bool`, `load_template(name: str) -> Template`, `list_templates() -> list[str]`.
  - `Registry(schema: int = 1, active: str = "", documents: list[DocumentSummary] = [])` Pydantic model with `to_json()` (sorted, unicode, indent 2).
  - `JsonDocumentRepository(workspace: Workspace)` implementing the port over the filesystem.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_json_repository.py
import shutil
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.domain.models.document import Document, DocumentSummary
from docs.infrastructure.persistence.json_repository import (
    JsonDocumentRepository, DocumentNotFoundError,
)

LEGACY_TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


@pytest.fixture
def repo(tmp_path: Path) -> JsonDocumentRepository:
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("reporte-estadia-tic", "documento-generico"):
        shutil.copy(LEGACY_TEMPLATES / f"{name}.json", templates / f"{name}.json")
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=templates)
    return JsonDocumentRepository(ws)


def test_registry_defaults_when_absent(repo):
    registry = repo.load_registry()
    assert registry.schema == 1 and registry.active == "" and registry.documents == []


def test_register_sets_active_and_sorts(repo):
    repo.register(DocumentSummary(id="beta", title="B", template="documento-generico", created_at="t"))
    repo.register(DocumentSummary(id="alpha", title="A", template="documento-generico", created_at="t"))
    registry = repo.load_registry()
    assert [d.id for d in registry.documents] == ["alpha", "beta"]
    assert registry.active == "alpha"


def test_registry_file_format_matches_legacy(repo):
    repo.register(DocumentSummary(id="alpha", title="A", template="documento-generico", created_at="t"))
    text = repo.workspace.registry_path.read_text(encoding="utf-8")
    assert text.startswith("{\n  \"active\": \"alpha\",")  # sort_keys + indent 2


def test_write_then_read_document_roundtrip(repo):
    repo.write_document(Document(id="alpha", title="A", template="documento-generico"))
    loaded = repo.read_document("alpha")
    assert loaded.id == "alpha" and loaded.template == "documento-generico"


def test_read_missing_document_raises(repo):
    with pytest.raises(DocumentNotFoundError):
        repo.read_document("ghost")


def test_list_templates(repo):
    assert sorted(repo.list_templates()) == ["documento-generico", "reporte-estadia-tic"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_json_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.json_repository`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/document_repository.py
from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import Template


class DocumentNotFoundError(Exception):
    pass


class DocumentExistsError(Exception):
    pass


class Registry(BaseModel):
    model_config = ConfigDict(extra="allow")
    schema: int = 1
    active: str = ""
    documents: list[DocumentSummary] = []

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), ensure_ascii=False, indent=2, sort_keys=True)


class DocumentRepository(Protocol):
    def load_registry(self) -> Registry: ...
    def save_registry(self, registry: Registry) -> None: ...
    def active_id(self) -> str: ...
    def set_active(self, doc_id: str) -> None: ...
    def register(self, summary: DocumentSummary) -> None: ...
    def read_document(self, doc_id: str) -> Document: ...
    def write_document(self, document: Document) -> None: ...
    def exists(self, doc_id: str) -> bool: ...
    def load_template(self, name: str) -> Template: ...
    def list_templates(self) -> list[str]: ...
```

```python
# src/docs/infrastructure/persistence/json_repository.py
from __future__ import annotations

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.models.template import Template
from docs.domain.ports.document_repository import (
    DocumentExistsError, DocumentNotFoundError, Registry,
)
from docs.domain.workspace import Workspace


class JsonDocumentRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    # registry -----------------------------------------------------------------
    def load_registry(self) -> Registry:
        path = self.workspace.registry_path
        if path.exists():
            try:
                return Registry.model_validate_json(path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return Registry()

    def save_registry(self, registry: Registry) -> None:
        path = self.workspace.registry_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(registry.to_json(), encoding="utf-8")

    def active_id(self) -> str:
        return self.load_registry().active

    def set_active(self, doc_id: str) -> None:
        registry = self.load_registry()
        if doc_id and doc_id not in {d.id for d in registry.documents}:
            raise DocumentNotFoundError(f"Unknown document: {doc_id}.")
        registry.active = doc_id
        self.save_registry(registry)

    def register(self, summary: DocumentSummary) -> None:
        registry = self.load_registry()
        documents = [d for d in registry.documents if d.id != summary.id]
        documents.append(summary)
        registry.documents = sorted(documents, key=lambda d: d.id)
        registry.active = summary.id
        self.save_registry(registry)

    # documents ----------------------------------------------------------------
    def _document_json(self, doc_id: str):
        return self.workspace.doc_root(doc_id) / "document.json"

    def exists(self, doc_id: str) -> bool:
        return self.workspace.doc_root(doc_id).exists()

    def read_document(self, doc_id: str) -> Document:
        path = self._document_json(doc_id)
        if not path.exists():
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist ({path}).")
        return Document.model_validate_json(path.read_text(encoding="utf-8"))

    def write_document(self, document: Document) -> None:
        path = self._document_json(document.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document.to_json(), encoding="utf-8")

    # templates ----------------------------------------------------------------
    def load_template(self, name: str) -> Template:
        path = self.workspace.templates_dir / f"{name}.json"
        if not path.exists():
            known = ", ".join(self.list_templates()) or "(none)"
            raise FileNotFoundError(f"Unknown template: {name}. Available: {known}")
        return Template.from_json(path.read_text(encoding="utf-8"))

    def list_templates(self) -> list[str]:
        directory = self.workspace.templates_dir
        if not directory.exists():
            return []
        return [p.stem for p in sorted(directory.glob("*.json"))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_json_repository.py -v`
Expected: PASS (6 passed). If `test_registry_file_format_matches_legacy` fails, inspect the dump and align `sort_keys`/indent — do not change the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/document_repository.py src/docs/infrastructure/persistence/json_repository.py tests/integration/test_json_repository.py
git commit -m "feat(infra): add DocumentRepository port and JSON adapter"
```

---

### Task 6: DocumentService — create

**Files:**
- Create: `src/docs/application/documents.py`
- Test: `tests/integration/test_document_service.py`

**Interfaces:**
- Consumes: `DocumentRepository` (port), `validate_slug`, `Document`, `DocumentSummary`, `Template`.
- Produces: `DocumentService(repository: DocumentRepository, clock: Callable[[], str] = ...)` with `create(doc_id: str, template_name: str, title: str = "") -> Document`. Behavior parity with legacy `create_document`:
  - validate slug; load template (raises if unknown); raise `DocumentExistsError` if `repository.exists(doc_id)`;
  - create the workspace subdirs `context, assets, sections, output/draft, output/final, output/qa, runs, corrections/inbox`;
  - build `Document(id, title=title or template.title or doc_id, template, project=template.project_defaults, structure=template.structure, overrides={})`;
  - `write_document`; `register(DocumentSummary(... created_at=clock()))`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_document_service.py
import shutil
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.domain.ports.document_repository import DocumentExistsError
from docs.domain.slug import InvalidSlugError
from docs.application.documents import DocumentService

LEGACY_TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "templates"


@pytest.fixture
def service(tmp_path: Path) -> DocumentService:
    templates = tmp_path / "templates"
    templates.mkdir()
    for name in ("reporte-estadia-tic", "documento-generico"):
        shutil.copy(LEGACY_TEMPLATES / f"{name}.json", templates / f"{name}.json")
    ws = Workspace(documents_dir=tmp_path / "documents", templates_dir=templates)
    return DocumentService(JsonDocumentRepository(ws), clock=lambda: "2026-06-19T00:00:00")


def test_create_builds_workspace_and_sets_active(service):
    doc = service.create("alpha", "reporte-estadia-tic")
    ws = service.repository.workspace
    for sub in ("context", "assets", "sections", "output/draft", "runs", "corrections/inbox"):
        assert (ws.doc_root("alpha") / sub).is_dir()
    assert doc.template == "reporte-estadia-tic"
    assert service.repository.active_id() == "alpha"


def test_create_rejects_invalid_slug(service):
    with pytest.raises(InvalidSlugError):
        service.create("Bad Slug", "documento-generico")


def test_create_twice_raises(service):
    service.create("alpha", "documento-generico")
    with pytest.raises(DocumentExistsError):
        service.create("alpha", "documento-generico")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_document_service.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.application.documents`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/documents.py
from __future__ import annotations

from datetime import datetime
from typing import Callable

from docs.domain.models.document import Document, DocumentSummary
from docs.domain.ports.document_repository import (
    DocumentExistsError, DocumentRepository,
)
from docs.domain.slug import validate_slug

_SUBDIRS = (
    "context", "assets", "sections",
    "output/draft", "output/final", "output/qa",
    "runs", "corrections/inbox",
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        clock: Callable[[], str] = _now,
    ) -> None:
        self.repository = repository
        self._clock = clock

    def create(self, doc_id: str, template_name: str, title: str = "") -> Document:
        validate_slug(doc_id)
        template = self.repository.load_template(template_name)
        if self.repository.exists(doc_id):
            raise DocumentExistsError(f"Document `{doc_id}` already exists.")
        doc_root = self.repository.workspace.doc_root(doc_id)
        for sub in _SUBDIRS:
            (doc_root / sub).mkdir(parents=True, exist_ok=True)
        document = Document(
            id=doc_id,
            title=title or template.title or doc_id,
            template=template_name,
            project=dict(template.project_defaults),
            structure=list(template.structure),
            overrides={},
        )
        self.repository.write_document(document)
        self.repository.register(
            DocumentSummary(
                id=doc_id, title=document.title,
                template=template_name, created_at=self._clock(),
            )
        )
        return document
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_document_service.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/documents.py tests/integration/test_document_service.py
git commit -m "feat(app): add DocumentService.create"
```

---

### Task 7: DocumentService — list / current / use

**Files:**
- Modify: `src/docs/application/documents.py`
- Test: `tests/integration/test_document_service.py` (add cases)

**Interfaces:**
- Produces on `DocumentService`:
  - `list() -> list[DocumentSummary]` (from registry, already id-sorted).
  - `current() -> str` (active id; `""` if none).
  - `use(doc_id: str) -> None` (delegates to `repository.set_active`; raises `DocumentNotFoundError` for unknown id).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_document_service.py
from docs.domain.ports.document_repository import DocumentNotFoundError


def test_list_and_current_and_use(service):
    service.create("alpha", "documento-generico")
    service.create("beta", "documento-generico")
    assert [d.id for d in service.list()] == ["alpha", "beta"]
    assert service.current() == "beta"
    service.use("alpha")
    assert service.current() == "alpha"


def test_use_unknown_raises(service):
    with pytest.raises(DocumentNotFoundError):
        service.use("ghost")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_document_service.py -k "list_and_current or use_unknown" -v`
Expected: FAIL with `AttributeError: 'DocumentService' object has no attribute 'list'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add these methods to DocumentService in src/docs/application/documents.py
    def list(self) -> list[DocumentSummary]:
        return self.repository.load_registry().documents

    def current(self) -> str:
        return self.repository.active_id()

    def use(self, doc_id: str) -> None:
        self.repository.set_active(doc_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_document_service.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/documents.py tests/integration/test_document_service.py
git commit -m "feat(app): add DocumentService list/current/use"
```

---

### Task 8: DocumentService — rename / delete

**Files:**
- Modify: `src/docs/application/documents.py`
- Modify: `src/docs/infrastructure/persistence/json_repository.py` (add `move`, `remove`, `path_guard`)
- Modify: `src/docs/domain/ports/document_repository.py` (add `move`, `remove` to Protocol)
- Test: `tests/integration/test_document_service.py` (add cases)

**Interfaces:**
- Consumes: existing repository methods.
- Produces:
  - Repository additions: `move(old_id: str, new_id: str) -> None` (renames the doc dir, rewrites `document.json` `id`, updates registry entry + active), `remove(doc_id: str) -> None` (deletes the doc dir guarded under `documents_dir`, drops from registry, repoints active to first remaining or `""`).
  - `DocumentService.rename(doc_id: str, new_id: str) -> None` (validate slug, raise `DocumentExistsError` if target exists, else `repository.move`).
  - `DocumentService.delete(doc_id: str) -> None` (raise `DocumentNotFoundError` if absent, else `repository.remove`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/integration/test_document_service.py
def test_rename_moves_dir_and_updates_registry(service):
    service.create("alpha", "documento-generico")
    service.rename("alpha", "gamma")
    ws = service.repository.workspace
    assert ws.doc_root("gamma").exists()
    assert not ws.doc_root("alpha").exists()
    assert service.repository.read_document("gamma").id == "gamma"
    assert service.current() == "gamma"


def test_delete_removes_and_repoints_active(service):
    service.create("alpha", "documento-generico")
    service.create("beta", "documento-generico")
    service.delete("beta")
    assert not service.repository.workspace.doc_root("beta").exists()
    assert service.current() == "alpha"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_document_service.py -k "rename or delete" -v`
Expected: FAIL with `AttributeError: 'DocumentService' object has no attribute 'rename'`.

- [ ] **Step 3: Write minimal implementation**

Add to the Protocol in `document_repository.py`:

```python
    def move(self, old_id: str, new_id: str) -> None: ...
    def remove(self, doc_id: str) -> None: ...
```

Add to `JsonDocumentRepository`:

```python
    def move(self, old_id: str, new_id: str) -> None:
        src = self.workspace.doc_root(old_id)
        dst = self.workspace.doc_root(new_id)
        if not src.exists():
            raise DocumentNotFoundError(f"Document `{old_id}` does not exist.")
        if dst.exists():
            raise DocumentExistsError(f"Document `{new_id}` already exists.")
        src.rename(dst)
        document = self.read_document(new_id)
        document.id = new_id
        self.write_document(document)
        registry = self.load_registry()
        for summary in registry.documents:
            if summary.id == old_id:
                summary.id = new_id
        if registry.active == old_id:
            registry.active = new_id
        self.save_registry(registry)

    def remove(self, doc_id: str) -> None:
        import shutil

        doc_root = self.workspace.doc_root(doc_id)
        if not doc_root.exists():
            raise DocumentNotFoundError(f"Document `{doc_id}` does not exist.")
        if self.workspace.documents_dir.resolve() not in doc_root.resolve().parents:
            raise ValueError(f"Refusing to delete outside workspace: {doc_root}")
        shutil.rmtree(doc_root)
        registry = self.load_registry()
        registry.documents = [d for d in registry.documents if d.id != doc_id]
        if registry.active == doc_id:
            registry.active = registry.documents[0].id if registry.documents else ""
        self.save_registry(registry)
```

Add to `DocumentService`:

```python
    def rename(self, doc_id: str, new_id: str) -> None:
        validate_slug(new_id)
        self.repository.move(doc_id, new_id)

    def delete(self, doc_id: str) -> None:
        self.repository.remove(doc_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_document_service.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/documents.py src/docs/infrastructure/persistence/json_repository.py src/docs/domain/ports/document_repository.py tests/integration/test_document_service.py
git commit -m "feat(app): add DocumentService rename/delete with workspace-guarded removal"
```

---

## Project Setup (do once, before Task 1)

- [ ] Add dependencies and pytest config to `pyproject.toml`, then create the package skeleton.

```bash
cd docs
uv add pydantic
uv add --dev pytest
```

Append to `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/docs"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Create empty `__init__.py` in every new `src/docs/...` package dir and a `tests/conftest.py` (empty). Verify the harness runs:

```bash
uv run pytest -q
```

Expected: `no tests ran` (until Task 1) — confirms collection works.

---

## Self-Review

- **Spec coverage (Slice 1 scope):** typed models ✅ (Tasks 1,3,4); kill global state ✅ (Workspace injection, Task 4); ports isolate boundaries ✅ (Task 5 repository port); doc CRUD ✅ (Tasks 6–8); on-disk parity ✅ (registry/document dump options asserted, Tasks 4–5). Slices 2–10 are out of scope for this plan and get their own.
- **Placeholder scan:** no TBD/TODO; every code step shows full code.
- **Type consistency:** `DocumentService.repository` exposed (used by tests via `service.repository.workspace`); `Registry`, `DocumentSummary`, `Document`, `Template` names consistent across tasks; `move`/`remove` added to both Protocol and adapter in Task 8.
- **Parity note:** legacy used a module-level mutable `register_doc`/`set_active`; new code threads the same semantics through the injected repository. `created_at` is non-deterministic in production but injected via `clock` in tests.
