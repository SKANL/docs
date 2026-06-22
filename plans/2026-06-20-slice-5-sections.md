# Slice 5 — Sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the legacy section-file I/O layer that Slice 3's Self-Review explicitly deferred: discovering which section files exist on disk, reading their frontmatter + body, and orchestrating per-section review (`review_section_text`, already pure from Slice 3) into the document-level `review_document` (walks `sections_dir`, aggregates issues, applies two extra document-level strict-mode checks, then calls `review_cross_consistency`, also already pure from Slice 3). This slice does **not** re-implement any review logic — `review_section_contract`/`review_apa7_text`/`review_section_text`/`review_rules`/`review_cross_consistency` in `domain/rules.py` are untouched and reused exactly as Slice 3 left them. This slice's job is the missing I/O/orchestration shell around them: a `SectionRepository` port, a `JsonSectionRepository` adapter that lists/reads section files off disk (mirroring legacy `section_path_for`/`load_section_bodies`/`resolve_section_path`/`infer_section_id_from_path`), and a `ReviewService.review_document` that wires the port to the domain functions — replacing legacy `review_document` end-to-end.

**Architecture:** Pragmatic hexagonal, same shape as Slices 1–4. `domain/sections.py` is pure: it holds the section-id-inference helper (`infer_section_id_from_path`, a string-only function with no I/O) and stays free of `Path.read_text`/`Path.exists`. `domain/ports/section_repository.py` declares the `SectionRepository` Protocol the application layer depends on. `infrastructure/persistence/json_section_repository.py` implements that Protocol with real `pathlib` I/O against `<doc_root>/sections/`, reusing `domain/markdown_text.py`'s `split_frontmatter` for frontmatter/body separation (no new parsing logic). `application/review.py` holds `ReviewService`, which composes the port (to list/read section files) with the already-existing pure domain functions from `domain/rules.py` (`review_section_text`, `review_rules`, `review_cross_consistency`) — mirroring `ContextService`'s composition of `ContextRepository` + plain domain calls. Nothing in `domain/sections.py` imports from `application`, `infrastructure`, or `cli`.

**Tech Stack:** Python ≥3.11, Pydantic v2 (no new models needed — `Section`/`Template`/`SectionContract` already exist from Slices 1 and 3), pytest with `tmp_path` for adapter/integration tests (no test touches the real legacy file tree).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. `domain/sections.py` imports nothing from `application`, `infrastructure`, or `cli`.
- **Section file naming, confirmed from legacy source (`tesina_harness.py` line 595):** `section_path_for(config, section) = Path(config["paths"]["sections_dir"]) / f"{section['order']:03d}-{section['id']}.md"`. The adapter must reproduce this exact zero-padded-3-digit-order-then-id naming.
- **Section id inference, confirmed from legacy source (line 1502-1504):** `infer_section_id_from_path(path) = re.sub(r"^\d+-", "", path.stem)` — strips a leading run of digits and a single hyphen from the filename stem (without extension). Used as a fallback when frontmatter has no `section_id` key.
- **`load_section_bodies` ordering, confirmed from legacy source (line 1659-1667):** iterates `config["sections"]` sorted by `order`, skips sections whose file doesn't exist, and returns `{section_id: body}` (frontmatter stripped) only for sections that do exist — not all configured sections.
- **`review_document` orchestration, confirmed from legacy source (line 1670-1699):**
  1. Start with `review_rules(config, strict=strict).issues` (already ported, Slice 3).
  2. For each section (sorted by `order`): if `section["required"]` and the file doesn't exist → emit `structure.missing_section` error. Else if the file exists → read it, split frontmatter, collect `(section_id, body)` for cross-consistency, run `review_section` (now `review_section_text`, Slice 3) on it, and **prefix every resulting issue message with `"{filename}: "`** (verbatim legacy behavior — issue messages from per-section review get the source filename prepended when surfaced at the document level; the per-section function itself does not do this).
  3. If `sections_dir` itself doesn't exist → emit `structure.missing_sections_dir` error (this check fires independently of the per-section loop and can coexist with missing-section errors).
  4. Join all collected section bodies with `"\n\n"`; if `strict` and the combined text contains the literal string `"PENDIENTE"` → emit `content.pending_not_allowed` error at the document level (distinct from the per-section check of the same code — legacy never deduplicates these, preserve as two independent emission paths).
  5. If `strict`: check that `["problema", "objetivo", "metodología", "resultados", "conclusiones"]` (lowercased) all appear somewhere in the lowercased combined text; if any are missing → emit one `coherence.missing_flow` error listing all missing terms.
  6. Finally, extend issues with `review_cross_consistency(config, section_bodies, strict=strict).issues` (already ported, Slice 3 — note legacy's `review_cross_consistency` returns `list[Issue]` directly per line 1712, the ported version in this repo's `domain/rules.py` returns a `ReviewResult`, so the service must read `.issues` off it, not append the `ReviewResult` itself).
  - This is a literal, line-by-line carry-over: no document-level check is skipped, none is added.
- **Out of scope for this slice (see Self-Review for the explicit judgment call):** legacy `build_section` (section scaffolding from a template) and `stamp_section` (provenance stamping). Both depend on `source_hash`/`rules_hash`/`contract_hash`/`prompt_hash`/`manifest_hash`/fact-ledger rendering, none of which are ported yet (confirmed absent from `domain/evidence.py` and Slice 4's Self-Review, which explicitly listed them as deferred to a future Pipeline slice). Scaffolding a new section file without that metadata would not be verbatim legacy parity — it would silently drop 5 of 9 frontmatter fields. Deferred, not silently dropped.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/domain/sections.py` — `infer_section_id_from_path`.
- `src/docs/domain/ports/section_repository.py` — `SectionRepository` Protocol.
- `src/docs/infrastructure/persistence/json_section_repository.py` — `JsonSectionRepository`.
- `src/docs/application/review.py` — `ReviewService`.
- `tests/unit/domain/test_sections.py`
- `tests/unit/infrastructure/test_json_section_repository.py`
- `tests/integration/test_review_service.py`

---

### Task 1: Pure section-id inference helper

**Files:**
- Create: `src/docs/domain/sections.py`
- Test: `tests/unit/domain/test_sections.py`

**Interfaces:**
- Consumes: nothing from other domain modules in this slice.
- Produces: `infer_section_id_from_path(path: Path) -> str`.

**Why this is its own pure function, not inlined in the adapter:** legacy `review_section` calls `infer_section_id_from_path(path)` as a fallback when a section file's frontmatter lacks a `section_id` key (line 1451: `metadata.get("section_id") or infer_section_id_from_path(path)`). It is pure string manipulation on `path.stem` — no filesystem access — so it belongs in `domain/`, consistent with how Slice 3 kept `requirement_present`/`citation_author_key` etc. as pure domain helpers rather than inlining them into the review orchestrator that consumes them.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_sections.py
from pathlib import Path

from docs.domain.sections import infer_section_id_from_path


def test_infer_section_id_strips_leading_digits_and_hyphen():
    path = Path("/repo/sections/001-introduccion.md")
    assert infer_section_id_from_path(path) == "introduccion"


def test_infer_section_id_strips_multi_digit_order():
    path = Path("/repo/sections/012-metodologia.md")
    assert infer_section_id_from_path(path) == "metodologia"


def test_infer_section_id_leaves_id_unchanged_when_no_leading_digits():
    path = Path("/repo/sections/referencias.md")
    assert infer_section_id_from_path(path) == "referencias"


def test_infer_section_id_only_strips_one_leading_digit_run():
    # Legacy regex `^\d+-` only matches a single leading run-of-digits-then-hyphen;
    # a section id that itself starts with digits after the order prefix is
    # preserved verbatim (no second strip pass).
    path = Path("/repo/sections/003-2024-resultados.md")
    assert infer_section_id_from_path(path) == "2024-resultados"


def test_infer_section_id_ignores_file_extension():
    path = Path("/repo/sections/005-conclusiones.md")
    assert infer_section_id_from_path(path) == "conclusiones"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.sections`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/sections.py
from __future__ import annotations

import re
from pathlib import Path

_LEADING_ORDER_RE = re.compile(r"^\d+-")


def infer_section_id_from_path(path: Path) -> str:
    return _LEADING_ORDER_RE.sub("", path.stem, count=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_sections.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/sections.py tests/unit/domain/test_sections.py
git commit -m "feat(domain): add infer_section_id_from_path pure helper"
```

---

### Task 2: SectionRepository port

**Files:**
- Create: `src/docs/domain/ports/section_repository.py`
- Test: none (a `Protocol` with no behavior has nothing to unit test on its own — same precedent as Slice 4 Task 2's `EvidenceRepository` and Slice 1 Task 5's `DocumentRepository`).

**Interfaces:**
- Consumes: nothing (pure interface declaration).
- Produces: `SectionRepository` Protocol with methods mirroring exactly what `JsonSectionRepository` (Task 3) must implement to let `ReviewService.review_document` (Task 4) replace legacy `review_document` end-to-end:
  - `section_path(doc_id: str, order: int, section_id: str) -> Path` — builds (without requiring existence) the `{order:03d}-{section_id}.md` path under the document's `sections/` directory.
  - `sections_dir_exists(doc_id: str) -> bool` — whether the document's `sections/` directory itself exists.
  - `section_exists(doc_id: str, order: int, section_id: str) -> bool`.
  - `read_section(doc_id: str, order: int, section_id: str) -> tuple[dict, str]` — returns `(metadata, body)` via frontmatter splitting; raises `FileNotFoundError` if the file is absent (callers must check `section_exists` first, mirroring legacy's existence-check-then-read pattern at `review_document`'s call sites).

This Protocol is intentionally scoped to read-only discovery/access (no `write_section`, no scaffolding methods) because section scaffolding (`build_section`/`stamp_section`) is out of scope for this slice — see Global Constraints and Self-Review. A future Pipeline slice that ports `build_section` can extend this same Protocol with write methods without touching the read-side contract this slice establishes.

- [ ] **Step 1: Write the failing test**

This task introduces only a `Protocol` (an interface declaration), which is structural typing with no runtime behavior of its own to assert against — there is nothing to make fail or pass independently of an implementation. Skip directly to Step 3; Task 3's adapter test will be the first test that actually exercises this Protocol's shape.

- [ ] **Step 2: Run test to verify it fails**

N/A — no test file in this task (see Step 1 rationale).

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/section_repository.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SectionRepository(Protocol):
    def section_path(self, doc_id: str, order: int, section_id: str) -> Path: ...
    def sections_dir_exists(self, doc_id: str) -> bool: ...
    def section_exists(self, doc_id: str, order: int, section_id: str) -> bool: ...
    def read_section(self, doc_id: str, order: int, section_id: str) -> tuple[dict, str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

N/A — no test in this task. Sanity-check the module imports cleanly:

Run: `uv run python -c "from docs.domain.ports.section_repository import SectionRepository; print(SectionRepository)"`
Expected: prints the Protocol class, no import error.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/section_repository.py
git commit -m "feat(domain): add SectionRepository port for section file discovery/read I/O"
```

---

### Task 3: JsonSectionRepository adapter

**Files:**
- Create: `src/docs/infrastructure/persistence/json_section_repository.py`
- Test: `tests/unit/infrastructure/test_json_section_repository.py`

**Interfaces:**
- Consumes: `SectionRepository` (Task 2, structurally — Python `Protocol`s are not subclassed, just satisfied); `Workspace` (Slice 1, for `doc_root(doc_id)`); `split_frontmatter` (Slice 2/3, `domain/markdown_text.py` — reused, not reimplemented).
- Produces: `JsonSectionRepository` class implementing every method of `SectionRepository`.

**Sections directory location, confirmed by pattern parity with `JsonContextRepository` (Slice 2 Task 3, `infrastructure/persistence/json_context_repository.py`):** that adapter places context files at `workspace.doc_root(doc_id) / "context"`. Legacy's `sections_dir` is a project-level config path (`config["paths"]["sections_dir"]`), but this repo's per-document workspace layout (one `documents_dir/<doc_id>/` root per document, established in Slice 1) means the equivalent per-document location is `workspace.doc_root(doc_id) / "sections"` — same placement convention as `context/`, not a new structural decision.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_json_section_repository.py
from pathlib import Path

import pytest

from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def repo(workspace: Workspace) -> JsonSectionRepository:
    return JsonSectionRepository(workspace)


def test_section_path_uses_zero_padded_order_and_id(workspace: Workspace, repo: JsonSectionRepository):
    path = repo.section_path("doc-1", 3, "introduccion")
    assert path == workspace.doc_root("doc-1") / "sections" / "003-introduccion.md"


def test_section_path_pads_multi_digit_order(workspace: Workspace, repo: JsonSectionRepository):
    path = repo.section_path("doc-1", 12, "metodologia")
    assert path.name == "012-metodologia.md"


def test_sections_dir_exists_false_when_absent(repo: JsonSectionRepository):
    assert repo.sections_dir_exists("doc-1") is False


def test_sections_dir_exists_true_when_present(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    assert repo.sections_dir_exists("doc-1") is True


def test_section_exists_false_when_file_absent(repo: JsonSectionRepository):
    assert repo.section_exists("doc-1", 1, "introduccion") is False


def test_section_exists_true_when_file_present(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text("# Introducción\n", encoding="utf-8")
    assert repo.section_exists("doc-1", 1, "introduccion") is True


def test_read_section_splits_frontmatter_and_body(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    raw = (
        '---\n{"section_id": "introduccion", "schema": 3}\n---\n'
        "# Introducción\n\nTexto.\n"
    )
    (sections_dir / "001-introduccion.md").write_text(raw, encoding="utf-8")
    metadata, body = repo.read_section("doc-1", 1, "introduccion")
    assert metadata == {"section_id": "introduccion", "schema": 3}
    assert body == "# Introducción\n\nTexto.\n"


def test_read_section_returns_empty_metadata_when_no_frontmatter(workspace: Workspace, repo: JsonSectionRepository):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "002-objetivos.md").write_text("# Objetivos\n\nTexto.\n", encoding="utf-8")
    metadata, body = repo.read_section("doc-1", 2, "objetivos")
    assert metadata == {}
    assert body == "# Objetivos\n\nTexto.\n"


def test_read_section_raises_file_not_found_when_missing(repo: JsonSectionRepository):
    with pytest.raises(FileNotFoundError):
        repo.read_section("doc-1", 9, "missing")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_json_section_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.json_section_repository`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/infrastructure/persistence/json_section_repository.py
from __future__ import annotations

from pathlib import Path

from docs.domain.markdown_text import split_frontmatter
from docs.domain.workspace import Workspace


class JsonSectionRepository:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def _sections_dir(self, doc_id: str) -> Path:
        return self.workspace.doc_root(doc_id) / "sections"

    def section_path(self, doc_id: str, order: int, section_id: str) -> Path:
        return self._sections_dir(doc_id) / f"{order:03d}-{section_id}.md"

    def sections_dir_exists(self, doc_id: str) -> bool:
        return self._sections_dir(doc_id).exists()

    def section_exists(self, doc_id: str, order: int, section_id: str) -> bool:
        return self.section_path(doc_id, order, section_id).exists()

    def read_section(self, doc_id: str, order: int, section_id: str) -> tuple[dict, str]:
        path = self.section_path(doc_id, order, section_id)
        if not path.exists():
            raise FileNotFoundError(f"Section file does not exist: {path}")
        raw_text = path.read_text(encoding="utf-8")
        return split_frontmatter(raw_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_json_section_repository.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/json_section_repository.py tests/unit/infrastructure/test_json_section_repository.py
git commit -m "feat(infrastructure): add JsonSectionRepository for section file discovery/read I/O"
```

---

### Task 4: ReviewService.review_document

**Files:**
- Create: `src/docs/application/review.py`
- Test: `tests/integration/test_review_service.py`

**Interfaces:**
- Consumes: `SectionRepository` (Task 2); `infer_section_id_from_path` (Task 1, used as the metadata-missing fallback — though in practice every section written by this codebase's own writers sets `section_id` in frontmatter, the fallback is preserved for parity with externally-authored/legacy section files); `review_section_text`, `review_rules`, `review_cross_consistency` (Slice 3, `domain/rules.py` — reused, not reimplemented); `Issue`, `ReviewResult` (Slice 3, `domain/review.py`); `Template`, `Section` (Slice 1/3, `domain/models/template.py`).
- Produces: `ReviewService` class with `review_document(self, doc_id: str, template: Template, strict: bool = False, **review_section_text_kwargs) -> ReviewResult`.

**Documented split from legacy `review_document(config, strict)`:** legacy's `config` bundles `sections` (list with `order`/`id`/`required`/`title`), `section_contracts`, `normative`/`privacy` overrides, and `strict_policy` all into one dict read by both `review_rules` and `review_section`. This repo's ported `review_rules`/`review_section_text` (Slice 3) already take a typed `Template` plus explicit keyword arguments (`excluded_terms`, `is_policy_file`, `first_person_patterns`, `subjective_terms`, `secret_patterns`, `scope_term`, `scope_focus`) instead of reading them off a raw dict — `ReviewService.review_document` simply forwards whatever normative-policy kwargs the caller supplies through to each `review_section_text` call, exactly as `EvidenceService.build_rules` (Slice 4) forwards `config` fields by key rather than re-deriving them. This service does not introduce new normative-policy resolution logic.

**Exact orchestration steps (verbatim from legacy `review_document`, `tesina_harness.py` lines 1670–1699), now expressed via the port:**

1. `issues: list[Issue] = []`; start with `review_rules(template, manifest_exists, manifest_size, strict=strict).issues` (caller supplies `manifest_exists`/`manifest_size` — same caller-resolves-I/O-facts pattern Slice 3 already established for `review_rules`; this service does not compute them itself).
2. `section_bodies: dict[str, str] = {}`; `combined_body: list[str] = []`.
3. For each `section` in `sorted(template.sections, key=lambda s: s.order)`:
   - If `section.required` and `not self.repository.section_exists(doc_id, section.order, section.id)` → append `Issue("error", f"Sección requerida faltante: \`{section.id}\`.", code="structure.missing_section")`.
   - Elif `self.repository.section_exists(doc_id, section.order, section.id)`:
     - `metadata, body = self.repository.read_section(doc_id, section.order, section.id)`.
     - `combined_body.append(body)`; `section_bodies[section.id] = body`.
     - `section_id = metadata.get("section_id") or infer_section_id_from_path(self.repository.section_path(doc_id, section.order, section.id))`.
     - `contract = template.section_contracts.get(section_id, SectionContract())`.
     - `section_issues = review_section_text(body, metadata, section_id, contract, template, strict, **review_section_text_kwargs)`.
     - For each issue in `section_issues`: append `Issue(issue.severity, f"{self.repository.section_path(doc_id, section.order, section.id).name}: {issue.message}", code=issue.code)` — **the filename-prefix happens here, at the document level, not inside `review_section_text`** (verbatim legacy: `review_section` itself never prefixes its own messages; only `review_document`'s aggregation loop does).
4. If `not self.repository.sections_dir_exists(doc_id)` → append `Issue("error", f"No existe directorio de secciones: {sections_dir}", code="structure.missing_sections_dir")` (uses `self.repository.section_path(doc_id, 0, "").parent` as the directory path for the message — see Step 3 code for the exact expression).
5. `combined = "\n\n".join(combined_body)`.
6. If `strict` and `"PENDIENTE" in combined` → append `Issue("error", "El documento contiene PENDIENTE en modo estricto.", code="content.pending_not_allowed")`.
7. If `strict`: `required_flow_terms = ["problema", "objetivo", "metodología", "resultados", "conclusiones"]`; `missing_flow = [t for t in required_flow_terms if t not in combined.lower()]`; if `missing_flow` → append one `Issue("error", f"No se detecta coherencia global mínima; faltan términos de flujo: {', '.join(missing_flow)}.", code="coherence.missing_flow")`.
8. `issues.extend(review_cross_consistency(template, section_bodies, strict=strict).issues)` — note the ported `review_cross_consistency` (Slice 3) returns a `ReviewResult`, unlike legacy's bare `list[Issue]`, so `.issues` must be read off it here.
9. Return `ReviewResult(issues)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_review_service.py
from pathlib import Path

import pytest

from docs.domain.models.template import Section, SectionContract, Template
from docs.domain.workspace import Workspace
from docs.application.review import ReviewService
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> ReviewService:
    return ReviewService(JsonSectionRepository(workspace))


def _template(**overrides) -> Template:
    defaults = dict(
        type="tesina",
        title="Tesina",
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="referencias", title="Referencias", order=2, required=False),
        ],
        section_contracts={},
    )
    defaults.update(overrides)
    return Template(**defaults)


def _write_section(workspace: Workspace, doc_id: str, order: int, section_id: str, body: str, metadata: dict | None = None) -> Path:
    sections_dir = workspace.doc_root(doc_id) / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    path = sections_dir / f"{order:03d}-{section_id}.md"
    if metadata is not None:
        import json

        text = "---\n" + json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n---\n" + body
    else:
        text = body
    path.write_text(text, encoding="utf-8")
    return path


def test_review_document_flags_missing_required_section(workspace: Workspace, service: ReviewService):
    template = _template()
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_section" in codes


def test_review_document_flags_missing_sections_dir(workspace: Workspace, service: ReviewService):
    template = _template(sections=[])
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_sections_dir" in codes


def test_review_document_prefixes_section_issue_messages_with_filename(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="Sin titulo principal.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    title_issues = [i for i in result.issues if i.code == "structure.missing_title"]
    assert len(title_issues) == 1
    assert title_issues[0].message.startswith("001-introduccion.md: ")


def test_review_document_strict_flags_pendiente_at_document_level(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nPENDIENTE: completar.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=True,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "content.pending_not_allowed" in codes


def test_review_document_strict_flags_missing_flow_terms(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto sin terminos de flujo.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=True,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    flow_issues = [i for i in result.issues if i.code == "coherence.missing_flow"]
    assert len(flow_issues) == 1
    assert "problema" in flow_issues[0].message


def test_review_document_skips_optional_missing_section_without_error(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[Section(id="referencias", title="Referencias", order=2, required=False)]
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_section" not in codes


def test_review_document_includes_cross_consistency_issues(workspace: Workspace, service: ReviewService):
    template = _template(
        sections=[
            Section(id="introduccion", title="Introducción", order=1, required=True),
            Section(id="referencias", title="Referencias", order=2, required=False),
        ]
    )
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nComo señala Pérez (2020), el sistema funciona.\n",
        metadata={"section_id": "introduccion"},
    )
    _write_section(
        workspace, "doc-1", 2, "referencias",
        body="# Referencias\n\n(sin referencias)\n",
        metadata={"section_id": "referencias"},
    )
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=True,
        manifest_size=10,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "coherence.citation_without_global_reference" in codes


def test_review_document_includes_rules_issues_when_manifest_missing(workspace: Workspace, service: ReviewService):
    template = _template(sections=[])
    result = service.review_document(
        "doc-1",
        template,
        strict=False,
        manifest_exists=False,
        manifest_size=0,
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    messages = [issue.message for issue in result.issues]
    assert any("manual-rules.json" in message for message in messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_review_service.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.application.review`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/review.py
from __future__ import annotations

from docs.domain.models.template import SectionContract, Template
from docs.domain.ports.section_repository import SectionRepository
from docs.domain.review import Issue, ReviewResult
from docs.domain.rules import review_cross_consistency, review_rules, review_section_text
from docs.domain.sections import infer_section_id_from_path

_REQUIRED_FLOW_TERMS = ["problema", "objetivo", "metodología", "resultados", "conclusiones"]


class ReviewService:
    def __init__(self, repository: SectionRepository) -> None:
        self.repository = repository

    def review_document(
        self,
        doc_id: str,
        template: Template,
        strict: bool = False,
        *,
        manifest_exists: bool,
        manifest_size: int,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> ReviewResult:
        issues: list[Issue] = list(
            review_rules(template, manifest_exists, manifest_size, strict=strict).issues
        )

        section_bodies: dict[str, str] = {}
        combined_body: list[str] = []

        for section in sorted(template.sections, key=lambda item: item.order):
            exists = self.repository.section_exists(doc_id, section.order, section.id)
            if section.required and not exists:
                issues.append(
                    Issue(
                        "error",
                        f"Sección requerida faltante: `{section.id}`.",
                        code="structure.missing_section",
                    )
                )
            elif exists:
                metadata, body = self.repository.read_section(doc_id, section.order, section.id)
                combined_body.append(body)
                section_bodies[section.id] = body

                section_path = self.repository.section_path(doc_id, section.order, section.id)
                section_id = metadata.get("section_id") or infer_section_id_from_path(section_path)
                contract = template.section_contracts.get(section_id, SectionContract())

                section_issues = review_section_text(
                    body,
                    metadata,
                    section_id,
                    contract,
                    template,
                    strict,
                    excluded_terms=excluded_terms,
                    is_policy_file=is_policy_file,
                    first_person_patterns=first_person_patterns,
                    subjective_terms=subjective_terms,
                    secret_patterns=secret_patterns,
                    scope_term=scope_term,
                    scope_focus=scope_focus,
                )
                for issue in section_issues:
                    issues.append(
                        Issue(issue.severity, f"{section_path.name}: {issue.message}", code=issue.code)
                    )

        if not self.repository.sections_dir_exists(doc_id):
            sections_dir = self.repository.section_path(doc_id, 0, "").parent
            issues.append(
                Issue(
                    "error",
                    f"No existe directorio de secciones: {sections_dir}",
                    code="structure.missing_sections_dir",
                )
            )

        combined = "\n\n".join(combined_body)
        if strict and "PENDIENTE" in combined:
            issues.append(
                Issue(
                    "error",
                    "El documento contiene PENDIENTE en modo estricto.",
                    code="content.pending_not_allowed",
                )
            )

        if strict:
            missing_flow = [term for term in _REQUIRED_FLOW_TERMS if term not in combined.lower()]
            if missing_flow:
                issues.append(
                    Issue(
                        "error",
                        "No se detecta coherencia global mínima; faltan términos de flujo: "
                        f"{', '.join(missing_flow)}.",
                        code="coherence.missing_flow",
                    )
                )

        issues.extend(
            review_cross_consistency(template, section_bodies, strict=strict).issues
        )

        return ReviewResult(issues)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_review_service.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/review.py tests/integration/test_review_service.py
git commit -m "feat(application): add ReviewService.review_document replacing legacy review_document"
```

---

## Full suite check (run after Task 4)

```bash
uv run pytest -W error -q
```

Expected: all tests pass (261 from Slices 1–4 plus this slice's 5 + 9 + 8 = 22 new tests → 283 total), zero warnings.

---

## Self-Review

- **Spec coverage (legacy section-file I/O deferred from Slice 3):**
  - Section path naming (`{order:03d}-{section_id}.md`) ✅ Task 3 (`JsonSectionRepository.section_path`) — exact zero-padding and ordering.
  - Section id inference from filename (`infer_section_id_from_path`) ✅ Task 1 (pure) — exact regex (`^\d+-`, single leading run only).
  - Section existence/discovery (`sections_dir_exists`, `section_exists`) ✅ Task 2 (port) + Task 3 (adapter).
  - Section frontmatter/body read (`read_section`, equivalent to legacy reading + `split_frontmatter`) ✅ Task 3 — reuses Slice 2/3's `split_frontmatter`, no new parsing logic.
  - `review_document` orchestrator (walks sections, aggregates `review_section_text` issues with filename prefix, two extra document-level strict checks, calls `review_cross_consistency`) ✅ Task 4 — every step from legacy lines 1670–1699 ported line-by-line, including the filename-prefix happening at the aggregation site (not inside the per-section function) and the two independent `PENDIENTE`-in-strict checks (per-section via `review_section_text`'s own check, document-level via Task 4 Step 6) being preserved as non-deduplicated, exactly as legacy never deduplicates them.
- **Judgment call — does `review_document` belong in this slice?** Yes, included as Task 4. Rationale: the per-document orchestrator's *only* missing dependency was the section-file-discovery/read I/O this slice's Tasks 1–3 build — its three logic dependencies (`review_rules`, `review_section_text`, `review_cross_consistency`) were already fully ported and pure as of Slice 3. Deferring `review_document` to a separate slice would mean building the exact same `SectionRepository`/`JsonSectionRepository` either twice (once now for "just reading," once later for "now also reviewing") or building it now but leaving its only real consumer unwritten — both worse than finishing the I/O-to-orchestration story in one slice now that all the pure logic it depends on already exists. This mirrors Slice 4's own shape: `EvidenceService.build_rules` was the service task that consumed a freshly-built repository in the same slice, not a separate one.
- **Judgment call — `build_section`/`stamp_section` excluded.** Confirmed via direct legacy read (`tesina_harness.py` lines 1157–1207, 3324–3339) that `build_section` requires `source_hash`, `manifest_hash`, `rules_hash`, `contract_hash`, `prompt_hash`, and fact-ledger rendering (`render_fact_ledger`) — none of which exist anywhere in the ported domain/application/infrastructure layers (confirmed by grep; Slice 4's own Self-Review explicitly named `rules_hash`/`contract_hash`/`prompt_hash`/`source_hash` as "used elsewhere, likely future Pipeline slice" and out of scope). Porting `build_section` now would mean either (a) silently dropping 5 of 9 frontmatter metadata fields — not verbatim parity, a real behavior change — or (b) building all five hashing functions as a side-quest inside a slice titled "Sections," which is scope creep into what is really a "Pipeline manifest hashing" concern. Deferred explicitly to a future slice once those hash functions exist; not silently dropped.
- **Placeholder scan:** no TBD/TODO/elisions; every Step 1/Step 3 across all 4 tasks shows complete, runnable code. Task 2 has no Step 1/Step 2 test code by design (a bare `Protocol` declaration has no independently-testable behavior) — explicitly justified, not a skipped step, consistent with Slice 4 Task 2's identical precedent.
- **Type consistency:** `infer_section_id_from_path` (Task 1) is consumed only by `ReviewService` (Task 4) as a fallback path, exactly mirroring its sole legacy call site inside `review_section`. `SectionRepository` (Task 2) is implemented by `JsonSectionRepository` (Task 3) and consumed only by `ReviewService` (Task 4) — one direction of dependency throughout (`application → domain` + `application → port`; `infrastructure → port` via structural typing; `infrastructure → domain` for `split_frontmatter` reuse), no task reaches back into an earlier task's internals.
- **Test count verification:** Task 1 code block has 5 `def test_` functions (verified by direct count of the Step 1 block above). Task 3 code block has 9 `def test_` functions. Task 4 code block has 8 `def test_` functions. 5 + 9 + 8 = 22, matching the "Full suite check" section's stated total of 283 (261 + 22). This count was re-verified by re-reading each Step 1 code block after writing it, in response to the recurring prose/code-count documentation bug flagged in Slices 3 and 4's progress logs.
