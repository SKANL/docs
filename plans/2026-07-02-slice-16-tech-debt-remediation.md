# Slice 16 — Technical Debt Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 5 findings of the post-migration technical-debt audit (DIP violations, two duplicated/divergent CLI helpers, an unencapsulated 7-parameter normative-settings bundle, and 4 SRP-violating god methods) without changing any observable CLI behavior.

**Architecture:** Every fix stays inside the hexagon the 15 prior slices built: new ports go in `domain/ports/`, new adapters in `infrastructure/`, application services gain constructor-injected collaborators instead of importing infrastructure directly, and `cli/` keeps calling exactly one application-service method per command. No new module, layer, or directory pattern is introduced — every new file mirrors an existing sibling (e.g. `domain/ports/tool_resolver_port.py` mirrors `domain/ports/docx_audit_port.py`).

**Tech Stack:** Python 3.11, `pytest` (test runner, invoked via `rtk pytest -q`), `pydantic` (unrelated to this slice), `python-docx` (Tasks 9–10 touch its call sites only, no version change), stdlib `dataclasses` (new: `NormativeSettings`).

## Global Constraints

- The 743 tests passing today (verify with `cd docs && rtk proxy uv run pytest`) must keep passing at the end of **every** task, and the total test count must only increase — RED→GREEN per task, never "make the refactor and hope nothing broke."
- Hexagonal boundary is preserved: `domain/` imports nothing from `application/` or `infrastructure/`; `application/` imports `infrastructure/` **only** through a `Protocol` in `domain/ports/`.
- No new third-party dependency. `NormativeSettings` uses stdlib `dataclasses`, matching `Workspace` (`domain/workspace.py:7`, `@dataclass(frozen=True)`) and `ResolvedContext` (`cli/_shared.py:36`).
- All Spanish user-facing strings (`Issue.message`, `Check` reasons, CLI print output) are copied **verbatim** — zero rewording, zero retranslation — from their current source lines.
- Every task is independently committable and leaves `rtk pytest -q` green. Run the full suite before Step 5 of every task, not just the file(s) touched in that task.
- `PipelineService.__init__` (`application/pipeline.py:31-45`, 12 constructor params) is explicitly **out of scope** — already evaluated and accepted as a legitimate composition-root, not a god object.

## Overview / Scope

This slice closes 5 findings from a technical-debt audit run against the codebase after Slice 15 (CLI surface) shipped. Each finding was re-verified against the current source (via `codegraph_explore`, not assumed from the audit) immediately before this plan was written:

1. **DIP violations (3 files)** — `application/context.py:9`, `application/doctor.py:15-16`, and `application/docx_assembly.py:12` import concrete functions from `infrastructure/` instead of depending on a `domain/ports/` abstraction. Tasks 1–2.
2. **`_context_confirmed_lines` duplicated** between `cli/main.py:162-176` and `application/pipeline.py:100-118` (byte-identical bodies). Task 3.
3. **`_rules_manifest_state` duplicated with a real behavioral divergence** — `cli/main.py:156-159` calls `Path.stat()` directly (bypassing the `EvidenceRepository` port, untestable and inconsistent with the rest of the codebase); `application/pipeline.py:94-98` correctly goes through `evidence_repository.file_exists`/`file_size`. Task 4.
4. **A 7-parameter "normative settings" bundle repeated across 5 signatures** — `domain/rules.py:176-190` (`review_section_text`), `application/review.py:25-39` (`review_document`) and `:125-138` (`review_section`), `application/context_pack.py:42-55` (`pack_context`) and `:161-175` (`pack_context_document`) — despite `resolve_normative_settings()` already existing in `domain/normative.py:50-67` to assemble those 7 values from `config`. Tasks 5–8.
5. **4 SRP-violating god methods/functions**: `_build_main_document` (`infrastructure/docx/python_docx_assembly_adapter.py:370-454`, ~85 lines / 6 responsibilities / 4 nesting levels), `PythonDocxAuditAdapter.audit` (`infrastructure/docx/python_docx_audit_adapter.py:47-159`, ~112 lines mixing raw-XML regex + `python-docx` object checks), `review_section_text` (`domain/rules.py:176-277`, ~102 lines / 9 distinct validations — closed together with Task 5 since both touch the same function body), and `review_rules` (`domain/rules.py:280-343`, 9 unrelated configuration checks). Tasks 5, 9, 10, 11.

### Out of Scope

The `NotImplementedError` raised by `PipelineService._stage_callables`'s `stage_build_sections` closure (`application/pipeline.py:154-159`, mirrored by the CLI's `build-section` command per Slice 15 Judgment call 3) is **not** touched by this slice. It is a genuinely unmodeled feature — a draft renderer plus `prompts_dir`-scoped prompt-hashing that Slices 6, 8, and 14 each deliberately deferred — not a tech-debt cleanup. Closing it means designing new domain concepts (a renderer abstraction, a hashing strategy), which belongs in its own slice starting from `superpowers:brainstorming`, not a remediation pass. Recommendation: **Slice 17**.

### Judgment calls resolved before writing task code

1. **`NormativeSettings` is introduced leaf-first (rules.py → review.py → context_pack.py → normative.py's return type), not root-first.** `resolve_normative_settings(config)` is called from 6 sites total (`application/pipeline.py:161-172` `stage_pack_context`, `:174-181` `stage_review_document`, `:250-256` `verify_all`; `cli/main.py:196-206` `pack_context` command, `:227-228` `review_section` command, `:241-245` `review_document` command). Changing its return type to `NormativeSettings` before the 5 downstream signatures accept the dataclass would break all 6 `**normative` dict-spreads simultaneously against functions that still expect 7 loose kwargs. Changing leaf-first instead means each of Tasks 5–7 only touches its own direct callers and can wrap the still-dict-returning `resolve_normative_settings(config)` result as `NormativeSettings(**resolve_normative_settings(config))` at the 6 pipeline/CLI call sites — a deliberately temporary shape, fully removed in Task 8 once `resolve_normative_settings` itself returns `NormativeSettings`. This keeps every task's diff small, single-responsibility, and green, at the cost of touching `pipeline.py`/`cli/main.py` more than once across Tasks 5–8. Accepted: matches the plan's "each task independently committable" constraint better than one giant 5-file task.
2. **Pandoc/LibreOffice executable resolution gets one new port (`ToolResolverPort`), not two, and not a method bolted onto `DocxAssemblyPort`.** `doctor.py` needs *both* `resolve_pandoc_executable` and `resolve_libreoffice_executable` (finding 1's second violation) but has no existing docx-adapter dependency to attach a method to; `docx_assembly.py` needs only pandoc resolution but already depends on `DocxAssemblyPort` (assembly, not tool discovery — attaching `resolve_pandoc` there would conflate "assemble a docx" with "find a binary on PATH", the same SRP concern finding 5 is about). Decision: one small `ToolResolverPort` Protocol (`resolve_pandoc`, `resolve_libreoffice`), one adapter (`SystemToolResolverAdapter`) that wraps the two already-correct free functions (`resolve_pandoc_executable` in `python_docx_assembly_adapter.py:19-30`, `resolve_libreoffice_executable` in `libreoffice_qa_adapter.py:12-23` — both stay exactly as-is, only their **direct import by application-layer code** is the violation), injected into both `DoctorService` and `DocxAssemblyService`.
3. **`ContextMarkdownPort` wraps only `render_requests`/`parse_requests`, not `render_topic`/`parse_topic`.** `application/context.py:9` imports `parse_requests, render_requests` from `infrastructure/persistence/context_markdown.py` — that is the DIP violation (finding 1's first violation). `render_topic`/`parse_topic` (same file, lines 19-40) are called exclusively from `JsonContextRepository` (`infrastructure/persistence/json_context_repository.py`), an infrastructure class calling infrastructure code — not a violation, out of scope.
4. **Duplicate-consolidation direction is "delete the CLI copy, promote `PipelineService`'s private method to public"** — not "extract both into a new shared module." `PipelineService` already legitimately owns both `_rules_manifest_state` and `_context_confirmed_lines` as internal stage-plumbing; the CLI's copies exist only because Slice 15 (Judgment call 1) deliberately deferred building a shared config-assembly layer and each command inlined what it needed. Now that `PipelineService` is constructed once per CLI invocation via `Deps.pipeline` (`cli/_shared.py:89-93`) and already carries the right collaborator (`evidence_repository`, injected at `pipeline.py:35`), the CLI can simply call through it. This is also how finding 3's bug gets fixed for free: the CLI's `Path.stat()`-direct copy is deleted, not "made to match" — there is only one implementation left, and it is the one that already goes through the port.
5. **God-method splits stay as private methods on the same class** (`_configure_preliminary_pagination`, `_check_table_borders`, etc.), not free functions or a new collaborator class. This matches the codebase's existing convention for adapter-internal decomposition — `PythonDocxAssemblyAdapter` already has `_cover_base_document`, `_sections_index`; `DocxAssemblyService` already has `_sections_index`, `_resolve_cover_asset_path`, `_resolve_embed_paths` (all private methods, all directly unit-tested — see `test_docx_assembly_service.py`'s `_resolve_cover_asset_path` test section). Introducing a new collaborator class per finding would be over-engineering for what the codebase already treats as "one class's internal decomposition."

---

### Task 1: DIP fix — `ContextMarkdownPort`

**Files:**
- Create: `src/docs/domain/ports/context_markdown_port.py`
- Modify: `src/docs/infrastructure/persistence/context_markdown.py` (append adapter class at end of file, no changes to existing functions)
- Modify: `src/docs/application/context.py:9,12-16,74-117` (constructor + 2 call sites)
- Modify: `src/docs/cli/_shared.py:12,25,88` (import + wiring)
- Test: `tests/integration/test_context_service.py` (fixture + new DIP-proof test)

**Interfaces:**
- Consumes: `docs.domain.context.TopicStatus` (existing), `docs.domain.models.template.ContextSchema` (existing), the existing module-level `render_requests(schema, statuses_with_values, only_topic="") -> str` and `parse_requests(schema, text) -> dict[str, str | dict[str, str]]` in `context_markdown.py` (both unchanged).
- Produces: `ContextMarkdownPort` Protocol (2 methods, signatures below) consumed by `ContextService.__init__`; `ContextMarkdownAdapter` class implementing it, consumed by `Deps.__init__`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_context_service.py` already imports `Document`, `DocumentSummary`, `ContextSchema`, `Field`, `Template`, `Topic`, `Workspace`, `JsonContextRepository`, `JsonDocumentRepository`, and `ContextService` (lines 5-11), defines a `_template()` free function (lines 14-32, a `documento-generico` template with an `alumno` topic and an `intro` prose topic), and a single `setup` fixture (lines 35-49) that registers document `"alpha"` and returns `(service, _template())`. Add this test using that exact convention (do not invent a `workspace`/`template` fixture pair that doesn't exist in this file):

```python
def test_write_requests_file_delegates_to_injected_context_markdown_port(setup):
    class _RecordingContextMarkdown:
        def __init__(self):
            self.render_calls = []

        def render_requests(self, schema, statuses_with_values, only_topic=""):
            self.render_calls.append((schema, only_topic))
            return "# rendered by fake\n"

        def parse_requests(self, schema, text):
            raise AssertionError("not exercised by this test")

    service, template = setup
    fake_markdown = _RecordingContextMarkdown()
    service_with_fake = ContextService(service.context_repo, service.document_repo, fake_markdown)

    path = service_with_fake.write_requests_file("alpha", template)

    assert fake_markdown.render_calls == [(template.context_schema, "")]
    assert path.read_text(encoding="utf-8") == "# rendered by fake\n"
```

This constructs a **second** `ContextService` instance reusing the same `context_repo`/`document_repo` the `setup` fixture already wired up (so `"alpha"` is already a registered, existing document), injecting the fake in place of the real adapter — proving both that the constructor accepts a 3rd argument and that `write_requests_file` actually delegates to it rather than calling the infrastructure functions directly.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_context_service.py::test_write_requests_file_delegates_to_injected_context_markdown_port`
Expected: FAIL with `TypeError: ContextService.__init__() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Write minimal implementation**

Create `src/docs/domain/ports/context_markdown_port.py`:

```python
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
```

Append to the end of `src/docs/infrastructure/persistence/context_markdown.py` (after the existing `parse_requests` function, which ends at line 116; `TopicStatus` and `ContextSchema` are already imported at the top of this file at line 5-6, no new imports needed):

```python


class ContextMarkdownAdapter:
    """Adapts the module-level render_requests/parse_requests to
    ContextMarkdownPort so application/context.py depends on the port
    instead of importing this infrastructure module directly (Slice 16
    tech-debt remediation, finding 1)."""

    def render_requests(
        self,
        schema: ContextSchema,
        statuses_with_values: list[tuple[TopicStatus, str | dict[str, str]]],
        only_topic: str = "",
    ) -> str:
        return render_requests(schema, statuses_with_values, only_topic=only_topic)

    def parse_requests(self, schema: ContextSchema, text: str) -> dict[str, str | dict[str, str]]:
        return parse_requests(schema, text)
```

In `src/docs/application/context.py`, replace line 9:

```python
from docs.infrastructure.persistence.context_markdown import parse_requests, render_requests
```

with:

```python
from docs.domain.ports.context_markdown_port import ContextMarkdownPort
```

Replace lines 12-15 (`class ContextService` constructor):

```python
class ContextService:
    def __init__(self, context_repo: ContextRepository, document_repo: DocumentRepository) -> None:
        self.context_repo = context_repo
        self.document_repo = document_repo
```

with:

```python
class ContextService:
    def __init__(
        self,
        context_repo: ContextRepository,
        document_repo: DocumentRepository,
        context_markdown: ContextMarkdownPort,
    ) -> None:
        self.context_repo = context_repo
        self.document_repo = document_repo
        self.context_markdown = context_markdown
```

In the `ingest` method, replace line 80:

```python
        parsed = parse_requests(template.context_schema, text)
```

with:

```python
        parsed = self.context_markdown.parse_requests(template.context_schema, text)
```

In the `write_requests_file` method, replace line 116:

```python
        text = render_requests(template.context_schema, pairs, only_topic=only_topic)
```

with:

```python
        text = self.context_markdown.render_requests(template.context_schema, pairs, only_topic=only_topic)
```

In `src/docs/cli/_shared.py`, add the import after line 12 (`from docs.application.context import ContextService`):

```python
from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter
```

Replace line 88:

```python
        self.context = ContextService(context_repo, document_repo)
```

with:

```python
        self.context = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
```

In `tests/integration/test_context_service.py`, update the `setup` fixture's `ContextService` construction at line 48 from:

```python
    service = ContextService(context_repo, document_repo)
```

to:

```python
    service = ContextService(context_repo, document_repo, ContextMarkdownAdapter())
```

and add `from docs.infrastructure.persistence.context_markdown import ContextMarkdownAdapter` next to the file's existing imports (after line 10, `from docs.infrastructure.persistence.json_repository import JsonDocumentRepository`).

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_context_service.py`
Expected: PASS (all existing tests in the file plus the new one — the `service` fixture change means every existing test in this file exercises the fix)

Then run the full suite: `rtk pytest -q` — expected 744+ passed, 0 failed (743 baseline + 1 new test).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/context_markdown_port.py src/docs/infrastructure/persistence/context_markdown.py src/docs/application/context.py src/docs/cli/_shared.py tests/integration/test_context_service.py
git commit -m "fix(context): depend on ContextMarkdownPort instead of importing infrastructure directly"
```

---

### Task 2: DIP fix — `ToolResolverPort`

**Files:**
- Create: `src/docs/domain/ports/tool_resolver_port.py`
- Create: `src/docs/infrastructure/docx/tool_resolver_adapter.py`
- Modify: `src/docs/application/doctor.py:15-16,19-22,81,83`
- Modify: `src/docs/application/docx_assembly.py:12,15-18,60`
- Modify: `src/docs/cli/_shared.py:75,72` (wiring)
- Test: `tests/integration/test_doctor_service.py:23-26` (`_service` helper), `tests/integration/test_docx_assembly_service.py:44-46` (`service` fixture), `tests/integration/test_pipeline_service.py:46,49` (`_service` helper)

**Interfaces:**
- Consumes: existing `resolve_pandoc_executable(paths: dict[str, Any]) -> str | None` (`infrastructure/docx/python_docx_assembly_adapter.py:19-30`, unchanged) and `resolve_libreoffice_executable(paths: dict[str, Any]) -> str | None` (`infrastructure/docx/libreoffice_qa_adapter.py:12-23`, unchanged).
- Produces: `ToolResolverPort` Protocol (`resolve_pandoc`, `resolve_libreoffice`) consumed by `DoctorService.__init__` and `DocxAssemblyService.__init__`; `SystemToolResolverAdapter` implementing it, consumed by `Deps.__init__`.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_doctor_service.py` (after the existing `_service` helper at line 23-26):

```python
def test_run_doctor_uses_injected_tool_resolver_not_shutil_which(tmp_path, monkeypatch):
    class _FakeToolResolver:
        def resolve_pandoc(self, paths):
            return "/fake/pandoc"

        def resolve_libreoffice(self, paths):
            return None

    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    service = DoctorService(JsonEvidenceRepository(), asset_service, _FakeToolResolver())
    config = _config(tmp_path)

    result = service.run_doctor("doc-1", config)

    pandoc_check = next(c for c in result.checks if c.name == "pandoc")
    libreoffice_check = next(c for c in result.checks if c.name == "libreoffice")
    assert pandoc_check.ok is True
    assert pandoc_check.detail == "/fake/pandoc"
    assert libreoffice_check.ok is False
```

Verified against `domain/doctor.py:7-20`: `Check` is a `@dataclass` with fields `name: str`, `ok: bool`, `detail: str`, `required: bool = True` (not `passed` — `passed` is a `@property` on `DoctorResult`, computed as `all(check.ok for check in self.checks if check.required)`); `DoctorResult` is a `@dataclass` with field `checks: list[Check]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_doctor_service.py::test_run_doctor_uses_injected_tool_resolver_not_shutil_which`
Expected: FAIL with `TypeError: DoctorService.__init__() takes 3 positional arguments but 4 were given`

- [ ] **Step 3: Write minimal implementation**

Create `src/docs/domain/ports/tool_resolver_port.py`:

```python
from __future__ import annotations

from typing import Any, Protocol


class ToolResolverPort(Protocol):
    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None: ...
    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None: ...
```

Create `src/docs/infrastructure/docx/tool_resolver_adapter.py`:

```python
# src/docs/infrastructure/docx/tool_resolver_adapter.py
from __future__ import annotations

from typing import Any

from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


class SystemToolResolverAdapter:
    """Wraps the two already-correct free functions that resolve build/QA
    tool executables from PATH or config fallbacks, so DoctorService and
    DocxAssemblyService depend on ToolResolverPort instead of importing
    infrastructure directly (Slice 16 tech-debt remediation, finding 1)."""

    def resolve_pandoc(self, paths: dict[str, Any]) -> str | None:
        return resolve_pandoc_executable(paths)

    def resolve_libreoffice(self, paths: dict[str, Any]) -> str | None:
        return resolve_libreoffice_executable(paths)
```

In `src/docs/application/doctor.py`, replace lines 15-16:

```python
from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable
```

with:

```python
from docs.domain.ports.tool_resolver_port import ToolResolverPort
```

Replace lines 19-22 (constructor):

```python
class DoctorService:
    def __init__(self, evidence_repository: EvidenceRepository, asset_service: AssetService) -> None:
        self.evidence_repository = evidence_repository
        self.asset_service = asset_service
```

with:

```python
class DoctorService:
    def __init__(
        self,
        evidence_repository: EvidenceRepository,
        asset_service: AssetService,
        tool_resolver: ToolResolverPort,
    ) -> None:
        self.evidence_repository = evidence_repository
        self.asset_service = asset_service
        self.tool_resolver = tool_resolver
```

Replace lines 81 and 83:

```python
        pandoc = resolve_pandoc_executable(config.get("paths", {}))
```

```python
        libreoffice = resolve_libreoffice_executable(config.get("paths", {}))
```

with:

```python
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
```

```python
        libreoffice = self.tool_resolver.resolve_libreoffice(config.get("paths", {}))
```

In `src/docs/application/docx_assembly.py`, replace line 12:

```python
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable
```

with:

```python
from docs.domain.ports.tool_resolver_port import ToolResolverPort
```

Replace lines 15-18 (constructor):

```python
class DocxAssemblyService:
    def __init__(self, port: DocxAssemblyPort, asset_service: AssetService) -> None:
        self.port = port
        self.asset_service = asset_service
```

with:

```python
class DocxAssemblyService:
    def __init__(self, port: DocxAssemblyPort, asset_service: AssetService, tool_resolver: ToolResolverPort) -> None:
        self.port = port
        self.asset_service = asset_service
        self.tool_resolver = tool_resolver
```

Replace line 60:

```python
        pandoc = resolve_pandoc_executable(config.get("paths", {}))
```

with:

```python
        pandoc = self.tool_resolver.resolve_pandoc(config.get("paths", {}))
```

In `src/docs/cli/_shared.py`, add the import after line 27 (`from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter`):

```python
from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter
```

In `Deps.__init__`, add a shared instance right before line 72 (`docx_assembly_service = DocxAssemblyService(...)`):

```python
        tool_resolver = SystemToolResolverAdapter()
```

Replace line 72:

```python
        docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
```

with:

```python
        docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service, tool_resolver)
```

Replace line 75:

```python
        doctor_service = DoctorService(evidence_repo, asset_service)
```

with:

```python
        doctor_service = DoctorService(evidence_repo, asset_service, tool_resolver)
```

In `tests/integration/test_doctor_service.py`, update the `_service` helper (lines 23-26) from:

```python
def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    return DoctorService(JsonEvidenceRepository(), asset_service)
```

to:

```python
def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    return DoctorService(JsonEvidenceRepository(), asset_service, SystemToolResolverAdapter())
```

and add `from docs.infrastructure.docx.tool_resolver_adapter import SystemToolResolverAdapter` to its imports.

In `tests/integration/test_docx_assembly_service.py`, update the `service` fixture (lines 44-46) from:

```python
@pytest.fixture
def service(asset_service: AssetService) -> DocxAssemblyService:
    return DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
```

to:

```python
@pytest.fixture
def service(asset_service: AssetService) -> DocxAssemblyService:
    return DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())
```

and add the same import.

In `tests/integration/test_pipeline_service.py`, update the `_service` helper: replace line 46 `docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)` with `docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service, SystemToolResolverAdapter())`, and replace line 49 `doctor_service = DoctorService(evidence_repo, asset_service)` with `doctor_service = DoctorService(evidence_repo, asset_service, SystemToolResolverAdapter())`; add the same import.

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_doctor_service.py tests/integration/test_docx_assembly_service.py tests/integration/test_pipeline_service.py`
Expected: PASS

Then run the full suite: `rtk pytest -q` — expected 745+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/tool_resolver_port.py src/docs/infrastructure/docx/tool_resolver_adapter.py src/docs/application/doctor.py src/docs/application/docx_assembly.py src/docs/cli/_shared.py tests/integration/test_doctor_service.py tests/integration/test_docx_assembly_service.py tests/integration/test_pipeline_service.py
git commit -m "fix(doctor,docx_assembly): depend on ToolResolverPort instead of importing infrastructure directly"
```

---

### Task 3: Consolidate `_context_confirmed_lines`

**Files:**
- Modify: `src/docs/application/pipeline.py:100-118,150`
- Modify: `src/docs/cli/main.py:145-176`
- Test: `tests/integration/test_pipeline_service.py`

**Interfaces:**
- Consumes: `Template.context_schema.topics` (existing), `ContextRepository.read_topic(doc_id, topic)` (existing port method).
- Produces: `PipelineService.context_confirmed_lines(doc_id: str, template: Template) -> list[str]` (renamed from private `_context_confirmed_lines`, same body, now the single implementation) consumed by `PipelineService._stage_callables`'s `stage_build_ledger` closure and by `cli/main.py`'s `build_ledger` command.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_pipeline_service.py` (this is a genuinely new direct test — today `_context_confirmed_lines` has no direct test, only indirect coverage via `stage_build_ledger`):

```python
def test_context_confirmed_lines_skips_sensitive_fields_and_includes_regular_ones(tmp_path):
    from docs.domain.models.template import Field, Template, Topic

    service, workspace = _service(tmp_path)
    template = Template(
        type="tesina",
        title="Tesina",
        context_schema={
            "topics": [
                Topic(
                    id="alumno",
                    title="Alumno",
                    fields=[
                        Field(key="nombre", label="Nombre", required=True),
                        Field(key="curp", label="CURP", required=False, sensitive=True),
                    ],
                )
            ]
        },
    )
    service.context_repository.write_topic("doc-1", template.context_schema.topics[0], {"nombre": "Ada", "curp": "AAAA000101HDFRRD01"})

    lines = service.context_confirmed_lines("doc-1", template)

    assert lines == ["Nombre: Ada"]
```

Verified against `domain/models/template.py:6-11` (`class Field(BaseModel)`, fields `key: str`, `label: str`, `required: bool = False`, `sensitive: bool = False`) and `:14-22` (`class Topic(BaseModel)`, fields `id: str`, `title: str`, `fields: list[Field] = []`, among others) — the class is named `Field`, not `ContextField`.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py::test_context_confirmed_lines_skips_sensitive_fields_and_includes_regular_ones`
Expected: FAIL with `AttributeError: 'PipelineService' object has no attribute 'context_confirmed_lines'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/pipeline.py`, rename the method at lines 100-118 by removing the leading underscore (body unchanged):

```python
    def context_confirmed_lines(self, doc_id: str, template: Template) -> list[str]:
        # Legacy also routes sensitive topic fields into a separate
        # "dato_sensible" ledger bucket. EvidenceService.render_fact_ledger
        # (Slice 8) only accepts one confirmado-scoped list, so sensitive
        # fields are skipped here rather than mis-classified. See the plan's
        # "Risks and open judgment calls" (Judgment call 4).
        lines: list[str] = []
        for topic in template.context_schema.topics:
            values = self.context_repository.read_topic(doc_id, topic)
            if isinstance(values, dict):
                for field in topic.fields:
                    value = values.get(field.key, "")
                    if not value or field.sensitive:
                        continue
                    lines.append(f"{field.label}: {value}")
            elif isinstance(values, str) and values.strip():
                snippet = values.strip()[:160]
                lines.append(f"{topic.title or topic.id}: {snippet}")
        return lines
```

Update its one internal caller at line 150 (inside `_stage_callables`'s `stage_build_ledger` closure) from:

```python
            context_lines = self._context_confirmed_lines(doc_id, template)
```

to:

```python
            context_lines = self.context_confirmed_lines(doc_id, template)
```

In `src/docs/cli/main.py`, delete the duplicate function definition at lines 162-176:

```python
def _context_confirmed_lines(deps: Deps, doc_id: str, template) -> list[str]:
    # Mirrors PipelineService._context_confirmed_lines (Slice 14 JC4): sensitive
    # topic fields are skipped, not mis-classified.
    lines: list[str] = []
    for topic in template.context_schema.topics:
        values = deps.context_repository.read_topic(doc_id, topic)
        if isinstance(values, dict):
            for field in topic.fields:
                value = values.get(field.key, "")
                if not value or field.sensitive:
                    continue
                lines.append(f"{field.label}: {value}")
        elif isinstance(values, str) and values.strip():
            lines.append(f"{topic.title or topic.id}: {values.strip()[:160]}")
    return lines
```

Update the `build_ledger` command (line 151) from:

```python
    lines = _context_confirmed_lines(deps, resolved.doc_id, resolved.template)
```

to:

```python
    lines = deps.pipeline.context_confirmed_lines(resolved.doc_id, resolved.template)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py tests/integration/test_cli_collection.py`
Expected: PASS (includes the existing `test_build_ledger_writes_and_prints_path` CLI regression test)

Then run the full suite: `rtk pytest -q` — expected 746+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/pipeline.py src/docs/cli/main.py tests/integration/test_pipeline_service.py
git commit -m "refactor(cli,pipeline): consolidate duplicated _context_confirmed_lines into PipelineService"
```

---

### Task 4: Consolidate `_rules_manifest_state` (fix the `Path.stat()` divergence)

**Files:**
- Modify: `src/docs/application/pipeline.py:94-98` (plus the 3 internal call sites elsewhere in the file that reference it)
- Modify: `src/docs/cli/main.py:121-128,156-159,192-215,233-248`
- Test: `tests/integration/test_pipeline_service.py`, `tests/integration/test_cli_collection.py`

**Interfaces:**
- Consumes: `EvidenceRepository.file_exists(path: Path) -> bool` / `file_size(path: Path) -> int` (existing port methods, `domain/ports/evidence_repository.py:13-14`).
- Produces: `PipelineService.rules_manifest_state(config: dict[str, Any]) -> tuple[bool, int]` (renamed from private `_rules_manifest_state`, same body) consumed by `PipelineService._stage_callables`'s `stage_review_rules`/`stage_pack_context`/`stage_review_document` closures, `verify_all`, and by `cli/main.py`'s `review_rules`, `pack_context`, `review_document` commands.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_pipeline_service.py`:

```python
def test_rules_manifest_state_goes_through_evidence_repository_not_direct_stat(tmp_path):
    service, workspace = _service(tmp_path)
    rules_path = tmp_path / "manual-rules.json"
    rules_path.write_text('{"schema": 1}', encoding="utf-8")
    config = {"paths": {"rules_manifest": str(rules_path)}}

    exists, size = service.rules_manifest_state(config)

    assert exists is True
    assert size == rules_path.stat().st_size


def test_rules_manifest_state_reports_absent_manifest(tmp_path):
    service, workspace = _service(tmp_path)
    config = {"paths": {"rules_manifest": str(tmp_path / "missing.json")}}

    exists, size = service.rules_manifest_state(config)

    assert exists is False
    assert size == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py::test_rules_manifest_state_goes_through_evidence_repository_not_direct_stat`
Expected: FAIL with `AttributeError: 'PipelineService' object has no attribute 'rules_manifest_state'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/pipeline.py`, rename the method at lines 94-98 by removing the leading underscore (body unchanged):

```python
    def rules_manifest_state(self, config: dict[str, Any]) -> tuple[bool, int]:
        rules_path = Path(config["paths"]["rules_manifest"])
        exists = self.evidence_repository.file_exists(rules_path)
        size = self.evidence_repository.file_size(rules_path) if exists else 0
        return exists, size
```

Update its 3 internal call sites (`stage_review_rules` inside `_stage_callables`, `stage_pack_context`, `stage_review_document`, and `verify_all`) — every occurrence of `self._rules_manifest_state(config)` in this file becomes `self.rules_manifest_state(config)`. There are 4 occurrences total in the file (one each in `stage_review_rules`, `stage_pack_context`, `stage_review_document`, `verify_all`); rename all 4.

In `src/docs/cli/main.py`, delete the buggy duplicate at lines 156-159:

```python
def _rules_manifest_state(deps: Deps, config: dict) -> tuple[bool, int]:
    rules_path = Path(config["paths"]["rules_manifest"])
    exists = rules_path.exists()
    return exists, (rules_path.stat().st_size if exists else 0)
```

Update the 3 CLI call sites. `review_rules` command, line 125:

```python
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
```

becomes:

```python
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)
```

`pack_context` command, line 197 — same replacement. `review_document` command, line 242 — same replacement.

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py tests/integration/test_cli_collection.py tests/integration/test_cli_section.py`
Expected: PASS (includes `test_review_rules_exit_1_when_manifest_missing_under_strict`, `test_review_rules_json_mode`, `test_pack_context_document_writes_a_pack`, `test_review_document_json_mode` regression tests, all previously exercising the buggy direct-`Path.stat()` path and now exercising the repository-backed one with identical observable output for real files)

Then run the full suite: `rtk pytest -q` — expected 748+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/pipeline.py src/docs/cli/main.py tests/integration/test_pipeline_service.py
git commit -m "fix(cli,pipeline): consolidate divergent _rules_manifest_state on the EvidenceRepository-backed implementation"
```

---

### Task 5: `NormativeSettings` value object + `review_section_text` refactor + SRP split

**Files:**
- Modify: `src/docs/domain/normative.py:1-3,50-67` (add dataclass, no change to `resolve_normative_settings` yet)
- Modify: `src/docs/domain/rules.py:1-18,176-277` (signature change + split into 9 pure check functions)
- Modify: `src/docs/application/review.py:1-10,67-81,152-166` (internal-only adaptation, public signatures unchanged)
- Test: `tests/unit/domain/test_rules.py:210-237` (`_call` helper), `tests/unit/domain/test_rules.py` (new direct test for one extracted check function)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `NormativeSettings` frozen dataclass (`domain/normative.py`) with fields `excluded_terms: dict[str, str]`, `is_policy_file: bool`, `first_person_patterns: list[str]`, `subjective_terms: list[str]`, `secret_patterns: list[str]`, `scope_term: str = ""`, `scope_focus: str = ""` — consumed by Tasks 6, 7, 8. `review_section_text(text, metadata, section_id, contract, template, strict, *, normative: NormativeSettings) -> list[Issue]` (new external signature) consumed by `application/review.py`.

- [ ] **Step 1: Write the failing test**

In `tests/unit/domain/test_rules.py`, add (near the top, after the `SectionContract`/`Template` imports at line 210-211):

```python
from docs.domain.normative import NormativeSettings


def test_normative_settings_is_a_frozen_dataclass_with_expected_defaults():
    settings = NormativeSettings(
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
    )
    assert settings.scope_term == ""
    assert settings.scope_focus == ""
    with pytest.raises(Exception):
        settings.scope_term = "changed"  # frozen dataclass raises FrozenInstanceError
```

`tests/unit/domain/test_rules.py` does not currently import `pytest` anywhere (verified: its only top-level imports are `from docs.domain.models.template import SectionContract, StrictPolicyBlock` and `from docs.domain.rules import requirement_present, review_apa7_text, review_section_contract` at lines 1-2). Add `import pytest` as the file's first line.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/unit/domain/test_rules.py::test_normative_settings_is_a_frozen_dataclass_with_expected_defaults`
Expected: FAIL with `ImportError: cannot import name 'NormativeSettings' from 'docs.domain.normative'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/domain/normative.py`, add `from dataclasses import dataclass` to the imports (replace lines 1-3):

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
```

Add the dataclass immediately before `resolve_normative_settings` (before line 50):

```python
@dataclass(frozen=True)
class NormativeSettings:
    """Bundles the 7 normative kwargs review_section_text/review_document/
    review_section/pack_context(_document) each required loose before Slice
    16. Built by resolve_normative_settings(config); downstream code passes
    the whole object instead of unpacking 7 parameters at every call site
    (Slice 16 tech-debt remediation, finding 4)."""

    excluded_terms: dict[str, str]
    is_policy_file: bool
    first_person_patterns: list[str]
    subjective_terms: list[str]
    secret_patterns: list[str]
    scope_term: str = ""
    scope_focus: str = ""
```

`resolve_normative_settings` itself is **not** touched in this task — it still returns a `dict[str, Any]` (Task 8 changes its return type).

In `src/docs/domain/rules.py`, add the import after line 16 (`from docs.domain.models.template import ...`):

```python
from docs.domain.normative import NormativeSettings
```

Replace `review_section_text`'s signature and body (lines 176-277) with the signature change plus a 9-way SRP split. First, the 9 new private pure functions (insert immediately before `review_section_text`, i.e. before the current line 176):

```python
def _check_excluded_terms(lowered: str, is_policy_file: bool, excluded_terms: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
    if not is_policy_file:
        for term, reason in excluded_terms.items():
            if term in lowered:
                issues.append(
                    Issue(
                        "error",
                        f"Contiene apartado excluido: `{term}`. {reason}".strip(),
                        code="scope.excluded_section",
                    )
                )
    return issues


def _check_first_person(lowered: str, first_person_patterns: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for pattern in first_person_patterns:
        if re.search(pattern, lowered):
            issues.append(
                Issue(
                    "error",
                    f"Contiene primera persona o voz no permitida: patrón `{pattern}`.",
                    code="voice.first_person",
                )
            )
    return issues


def _check_subjective_terms(lowered: str, subjective_terms: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for term in subjective_terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            issues.append(
                Issue(
                    "warning",
                    f"Contiene término subjetivo sin evidencia automática: `{term}`.",
                    code="voice.subjective_term",
                )
            )
    return issues


def _check_secret_patterns(text: str, secret_patterns: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for pattern in secret_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(
                Issue(
                    "error",
                    f"Contiene posible secreto, credencial o dato sensible: patrón `{pattern}`.",
                    code="privacy.sensitive_data",
                )
            )
    return issues


def _check_scope_delimitation(lowered: str, scope_term: str, scope_focus: str) -> list[Issue]:
    if scope_term and scope_focus and scope_term in lowered and scope_focus not in lowered:
        return [
            Issue(
                "warning",
                f"Menciona `{scope_term}` sin delimitar el alcance a `{scope_focus}`.",
                code="scope.undelimited_ecosystem",
            )
        ]
    return []


def _check_title(text: str, is_policy_file: bool) -> list[Issue]:
    if not is_policy_file and not _TITLE_RE.search(text):
        return [Issue("error", "La sección no tiene título principal Markdown.", code="structure.missing_title")]
    return []


def _check_contract_dispatch(
    text: str, section_id: str, contract: SectionContract, strict_policy: StrictPolicyBlock, strict: bool, is_policy_file: bool
) -> list[Issue]:
    if contract != SectionContract() and not is_policy_file:
        return review_section_contract(text, section_id, contract, strict_policy, strict)
    return []


def _check_pending_marker(lowered: str, is_policy_file: bool, strict_policy: StrictPolicyBlock, contract: SectionContract) -> list[Issue]:
    pending_allowed = strict_policy.allow_pending and contract.pending_allowed_in_draft
    if not is_policy_file and "pendiente" in lowered and not pending_allowed:
        return [
            Issue(
                "error",
                "Contiene PENDIENTE en modo estricto o en una sección que no permite pendientes.",
                code="content.pending_not_allowed",
            )
        ]
    return []


def _check_results_evidence(lowered: str) -> list[Issue]:
    if _RESULTS_RE.search(lowered) and "pendiente" not in lowered and not _RESULTS_EVIDENCE_RE.search(lowered):
        return [
            Issue(
                "warning",
                "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                code="evidence.results_without_evidence",
            )
        ]
    return []
```

Then replace `review_section_text` itself (was lines 176-277) with:

```python
def review_section_text(
    text: str,
    metadata: dict,
    section_id: str,
    contract: SectionContract,
    template: Template,
    strict: bool,
    *,
    normative: NormativeSettings,
) -> list[Issue]:
    lowered = text.lower()
    strict_policy = template.strict_policy.strict if strict else template.strict_policy.draft
    issues: list[Issue] = []

    issues.extend(_check_excluded_terms(lowered, normative.is_policy_file, normative.excluded_terms))
    issues.extend(_check_first_person(lowered, normative.first_person_patterns))
    issues.extend(_check_subjective_terms(lowered, normative.subjective_terms))
    issues.extend(_check_secret_patterns(text, normative.secret_patterns))
    issues.extend(_check_scope_delimitation(lowered, normative.scope_term, normative.scope_focus))
    issues.extend(_check_title(text, normative.is_policy_file))
    issues.extend(_check_contract_dispatch(text, section_id, contract, strict_policy, strict, normative.is_policy_file))
    issues.extend(_check_pending_marker(lowered, normative.is_policy_file, strict_policy, contract))
    issues.extend(review_apa7_text(text, template.apa7.enabled, strict_policy))
    issues.extend(_check_results_evidence(lowered))

    return issues
```

In `tests/unit/domain/test_rules.py`, update the `_call` helper (lines 218-237) from:

```python
def _call(text, contract=None, template=None, strict=False, **kwargs):
    defaults = dict(
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
        scope_term="",
        scope_focus="",
    )
    defaults.update(kwargs)
    return review_section_text(
        text,
        {},
        "intro",
        contract or SectionContract(),
        template or _template(),
        strict,
        **defaults,
    )
```

to:

```python
def _call(text, contract=None, template=None, strict=False, **kwargs):
    defaults = dict(
        excluded_terms={},
        is_policy_file=False,
        first_person_patterns=[],
        subjective_terms=[],
        secret_patterns=[],
        scope_term="",
        scope_focus="",
    )
    defaults.update(kwargs)
    return review_section_text(
        text,
        {},
        "intro",
        contract or SectionContract(),
        template or _template(),
        strict,
        normative=NormativeSettings(**defaults),
    )
```

Every one of the file's existing `test_review_section_text_*` tests (lines 240-365, all calling `_call(...)`) keeps working unchanged since `_call`'s own external interface (positional `text` + `**kwargs`) is untouched — only its internal construction of the `review_section_text` call changed.

In `src/docs/application/review.py`, add the import after line 6 (`from docs.domain.models.template import ...`):

```python
from docs.domain.normative import NormativeSettings
```

`review_document`'s public signature (lines 25-39) is **unchanged** in this task. Inside its body, replace the `review_section_text` call (lines 67-81):

```python
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
```

with:

```python
                normative = NormativeSettings(
                    excluded_terms=excluded_terms,
                    is_policy_file=is_policy_file,
                    first_person_patterns=first_person_patterns,
                    subjective_terms=subjective_terms,
                    secret_patterns=secret_patterns,
                    scope_term=scope_term,
                    scope_focus=scope_focus,
                )
                section_issues = review_section_text(
                    body, metadata, section_id, contract, template, strict, normative=normative,
                )
```

`review_section`'s public signature (lines 125-138) is **unchanged**. Inside its body, replace the `review_section_text` call (lines 152-166) with the same pattern:

```python
        normative = NormativeSettings(
            excluded_terms=excluded_terms,
            is_policy_file=is_policy_file,
            first_person_patterns=first_person_patterns,
            subjective_terms=subjective_terms,
            secret_patterns=secret_patterns,
            scope_term=scope_term,
            scope_focus=scope_focus,
        )
        issues = review_section_text(
            body, metadata, resolved_section_id, contract, template, strict, normative=normative,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/unit/domain/test_rules.py tests/integration/test_review_service.py`
Expected: PASS — `test_normative_settings_is_a_frozen_dataclass_with_expected_defaults` passes, all `test_review_section_text_*` characterization tests pass unchanged (proving the split is behavior-preserving), and `test_review_service.py` passes unchanged (proving `review.py`'s public signature is genuinely untouched by this task).

Then run the full suite: `rtk pytest -q` — expected 749+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/normative.py src/docs/domain/rules.py src/docs/application/review.py tests/unit/domain/test_rules.py
git commit -m "refactor(rules): introduce NormativeSettings and split review_section_text into 9 pure checks"
```

---

### Task 6: `application/review.py` — accept `NormativeSettings`

**Files:**
- Modify: `src/docs/application/review.py:25-39,41-43,125-138`
- Modify: `src/docs/application/context_pack.py:126-138,210-223` (internal-only adaptation, public signatures unchanged)
- Modify: `src/docs/application/pipeline.py:174-181,251-257` (2 direct call sites)
- Modify: `src/docs/cli/main.py:12,218-230,233-248` (2 direct call sites)
- Test: `tests/integration/test_review_service.py` (11 call sites, all identical normative values — see helper below)

**Interfaces:**
- Consumes: `NormativeSettings` (Task 5).
- Produces: `ReviewService.review_document(doc_id, template, strict=False, *, manifest_exists, manifest_size, normative: NormativeSettings) -> ReviewResult` and `ReviewService.review_section(doc_id, template, section_id, strict=False, *, normative: NormativeSettings) -> ReviewResult` (both external signatures changed from 7 loose kwargs to 1) consumed by `application/context_pack.py`, `application/pipeline.py`, `cli/main.py`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_review_service.py` today has **11 call sites** (8 `service.review_document(...)`, 3 `service.review_section(...)`), every single one passing the identical 5 values `excluded_terms={}, is_policy_file=False, first_person_patterns=[], subjective_terms=[], secret_patterns=[]`. Add a module-level constant right after the existing `_template` helper (after line 35):

```python
from docs.domain.normative import NormativeSettings

_NORMATIVE = NormativeSettings(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)
```

Then change **one** call site first (the RED step) — `test_review_document_flags_missing_required_section` (lines 54-65) — from:

```python
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
```

to:

```python
    result = service.review_document(
        "doc-1", template, strict=False, manifest_exists=True, manifest_size=10, normative=_NORMATIVE,
    )
```

Leave the other 10 call sites untouched for now — they still pass loose kwargs, which still works against the current signature, so the suite is still green except for this one new-style call.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_review_service.py::test_review_document_flags_missing_required_section`
Expected: FAIL with `TypeError: ReviewService.review_document() got an unexpected keyword argument 'normative'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/review.py`, replace `review_document`'s signature (lines 25-39):

```python
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
```

with:

```python
    def review_document(
        self,
        doc_id: str,
        template: Template,
        strict: bool = False,
        *,
        manifest_exists: bool,
        manifest_size: int,
        normative: NormativeSettings,
    ) -> ReviewResult:
```

Update the body's `review_section_text` call site added in Task 5 to read straight from `normative` instead of rebuilding it (this replaces the `NormativeSettings(...)` construction Task 5 added, since the caller now supplies it directly):

```python
                section_issues = review_section_text(
                    body, metadata, section_id, contract, template, strict, normative=normative,
                )
```

Replace `review_section`'s signature (lines 125-138):

```python
    def review_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        strict: bool = False,
        *,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> ReviewResult:
```

with:

```python
    def review_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        strict: bool = False,
        *,
        normative: NormativeSettings,
    ) -> ReviewResult:
```

and its body's `review_section_text` call likewise reads `normative` directly:

```python
        issues = review_section_text(
            body, metadata, resolved_section_id, contract, template, strict, normative=normative,
        )
```

Now fix the 4 other callers of these two methods so the suite goes green again.

In `src/docs/application/context_pack.py`, `pack_context`'s call to `review_service.review_section` (lines 126-138):

```python
            review = self.review_service.review_section(
                doc_id,
                template,
                section_id,
                strict=False,
                excluded_terms=excluded_terms,
                is_policy_file=is_policy_file,
                first_person_patterns=first_person_patterns,
                subjective_terms=subjective_terms,
                secret_patterns=secret_patterns,
                scope_term=scope_term,
                scope_focus=scope_focus,
            )
```

becomes (`pack_context`'s own external signature is unchanged in this task — it still receives the 7 loose kwargs and rebuilds `NormativeSettings` internally, until Task 7):

```python
            from docs.domain.normative import NormativeSettings

            normative = NormativeSettings(
                excluded_terms=excluded_terms,
                is_policy_file=is_policy_file,
                first_person_patterns=first_person_patterns,
                subjective_terms=subjective_terms,
                secret_patterns=secret_patterns,
                scope_term=scope_term,
                scope_focus=scope_focus,
            )
            review = self.review_service.review_section(doc_id, template, section_id, strict=False, normative=normative)
```

Move that `from docs.domain.normative import NormativeSettings` to the file's top-level imports (after line 10, `from docs.application.review import ReviewService`) instead of inlining it inside the method — keep the import block clean.

`pack_context_document`'s call to `review_service.review_document` (lines 210-223) becomes the same pattern:

```python
        normative = NormativeSettings(
            excluded_terms=excluded_terms,
            is_policy_file=is_policy_file,
            first_person_patterns=first_person_patterns,
            subjective_terms=subjective_terms,
            secret_patterns=secret_patterns,
            scope_term=scope_term,
            scope_focus=scope_focus,
        )
        review = self.review_service.review_document(
            doc_id, template, strict=False, manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )
```

In `src/docs/application/pipeline.py`, `stage_review_document` (inside `_stage_callables`, lines 174-181):

```python
        def stage_review_document() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            result = self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            )
            return result.passed, result.to_markdown()
```

becomes:

```python
        def stage_review_document() -> tuple[bool, str]:
            normative = NormativeSettings(**resolve_normative_settings(config))
            manifest_exists, manifest_size = self.rules_manifest_state(config)
            result = self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            )
            return result.passed, result.to_markdown()
```

(note this also picks up Task 4's `rules_manifest_state` rename — if Task 4 already ran, `self._rules_manifest_state` no longer exists, so this line must read `self.rules_manifest_state`).

`verify_all` (lines 251-257):

```python
        normative = resolve_normative_settings(config)
        issues.extend(
            self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            ).issues
        )
```

becomes:

```python
        normative = NormativeSettings(**resolve_normative_settings(config))
        issues.extend(
            self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            ).issues
        )
```

Add `from docs.domain.normative import NormativeSettings, resolve_normative_settings` to `pipeline.py`'s imports, replacing the existing line 18 (`from docs.domain.normative import resolve_normative_settings`).

In `src/docs/cli/main.py`, replace line 12's import:

```python
from docs.domain.normative import resolve_normative_settings
```

with:

```python
from docs.domain.normative import NormativeSettings, resolve_normative_settings
```

`review_section` command (lines 218-230):

```python
    normative = resolve_normative_settings(resolved.config)
    result = deps.review.review_section(resolved.doc_id, resolved.template, section, strict=strict, **normative)
```

becomes:

```python
    normative = NormativeSettings(**resolve_normative_settings(resolved.config))
    result = deps.review.review_section(resolved.doc_id, resolved.template, section, strict=strict, normative=normative)
```

`review_document` command (lines 233-248):

```python
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
    result = deps.review.review_document(
        resolved.doc_id, resolved.template, strict=strict,
        manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
    )
```

becomes (also picking up Task 4's CLI-side rename):

```python
    normative = NormativeSettings(**resolve_normative_settings(resolved.config))
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)
    result = deps.review.review_document(
        resolved.doc_id, resolved.template, strict=strict,
        manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
    )
```

Finally, in `tests/integration/test_review_service.py`, apply the `normative=_NORMATIVE` transform (introduced in Step 1 for one call site) to the remaining **10** call sites — every one uses the identical 5 values, so every one becomes a straight `normative=_NORMATIVE` replacement of its trailing 5-line kwarg block:

- `test_review_document_flags_missing_sections_dir` (lines 72-83): `manifest_exists=True, manifest_size=10, normative=_NORMATIVE,`
- `test_review_document_prefixes_section_issue_messages_with_filename` (lines 97-108): same
- `test_review_document_strict_flags_pendiente_at_document_level` (lines 123-134), `strict=True`: `manifest_exists=True, manifest_size=10, normative=_NORMATIVE,`
- `test_review_document_strict_flags_missing_flow_terms` (lines 148-159), `strict=True`: same
- `test_review_document_skips_optional_missing_section_without_error` (lines 169-180): same
- `test_review_document_includes_cross_consistency_issues` (lines 202-213): same
- `test_review_document_includes_rules_issues_when_manifest_missing` (lines 220-231), note `manifest_exists=False, manifest_size=0`: `manifest_exists=False, manifest_size=0, normative=_NORMATIVE,`
- `test_review_section_flags_issues_for_section_with_problems` (lines 245-255): `service.review_section("doc-1", template, "introduccion", strict=False, normative=_NORMATIVE)`
- `test_review_section_no_issues_for_clean_section` (lines 269-279): same pattern
- `test_review_section_raises_when_section_file_missing` (lines 286-296): `service.review_section("doc-1", template, "introduccion", strict=False, normative=_NORMATIVE)`
- `test_review_section_raises_when_section_id_unknown` (lines 302-312): `service.review_section("doc-1", template, "no-existe", strict=False, normative=_NORMATIVE)`

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_review_service.py tests/integration/test_context_pack_service.py tests/integration/test_pipeline_service.py tests/integration/test_cli_section.py`
Expected: PASS — all 11 rewritten `test_review_service.py` call sites pass, `context_pack.py`'s unchanged public tests pass (its internal adaptation is invisible from outside), `pipeline.py`'s `verify_all`/pipeline stage tests pass, CLI `review-section`/`review-document` integration tests pass.

Then run the full suite: `rtk pytest -q` — expected 749+ passed, 0 failed (no new tests added this task, pure refactor).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/review.py src/docs/application/context_pack.py src/docs/application/pipeline.py src/docs/cli/main.py tests/integration/test_review_service.py
git commit -m "refactor(review): ReviewService.review_document/review_section accept NormativeSettings"
```

---

### Task 7: `application/context_pack.py` — accept `NormativeSettings`

**Files:**
- Modify: `src/docs/application/context_pack.py:1-14,42-56,126-138,161-176,210-223`
- Modify: `src/docs/application/pipeline.py:161-172`
- Modify: `src/docs/cli/main.py:192-215`
- Test: `tests/integration/test_context_pack_service.py:14-30,71-235`

**Interfaces:**
- Consumes: `NormativeSettings` (Task 5), `ReviewService.review_document`/`review_section` now accepting `normative=` directly (Task 6).
- Produces: `ContextPackService.pack_context(doc_id, template, section_id, config, *, normative: NormativeSettings) -> Path` (signature reduced from 11 params to 5) and `ContextPackService.pack_context_document(doc_id, template, config, *, manifest_exists, manifest_size, normative: NormativeSettings) -> Path` (reduced from 12 params to 6), consumed by `application/pipeline.py`, `cli/main.py`.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_context_pack_service.py` already centralizes its normative kwargs in two module-level dict constants (`_REVIEW_KWARGS` at lines 14-20, `_REVIEW_DOCUMENT_KWARGS` at lines 22-30). Change **one** call site first (the RED step) — `test_pack_context_includes_required_content_checklist` (lines 71-76) — from:

```python
def test_pack_context_includes_required_content_checklist(tmp_path, workspace, service):
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), **_REVIEW_KWARGS
    )
```

to:

```python
def test_pack_context_includes_required_content_checklist(tmp_path, workspace, service):
    out_path = service.pack_context(
        "doc-1", _template(), "introduccion", _config(tmp_path), normative=_NORMATIVE
    )
```

(this references a `_NORMATIVE` constant that does not exist yet — added in Step 3 below, deliberately deferred so this step is a true RED against the current `pack_context` signature).

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_context_pack_service.py::test_pack_context_includes_required_content_checklist`
Expected: FAIL with `TypeError: ContextPackService.pack_context() got an unexpected keyword argument 'normative'` (or a `NameError` for `_NORMATIVE` if the module-level constant addition from Step 3 is done before this run — run Step 2 strictly before adding `_NORMATIVE`, so the failure is unambiguous)

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/context_pack.py`, add the import after line 10 (`from docs.application.review import ReviewService`):

```python
from docs.domain.normative import NormativeSettings
```

Replace `pack_context`'s signature (lines 42-56):

```python
    def pack_context(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        config: dict[str, Any],
        *,
        excluded_terms: dict[str, str],
        is_policy_file: bool,
        first_person_patterns: list[str],
        subjective_terms: list[str],
        secret_patterns: list[str],
        scope_term: str = "",
        scope_focus: str = "",
    ) -> Path:
```

with:

```python
    def pack_context(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        config: dict[str, Any],
        *,
        normative: NormativeSettings,
    ) -> Path:
```

Replace its body's call to `review_service.review_section` (the `NormativeSettings(...)` construction Task 6 added at lines 126-138) with a direct pass-through:

```python
            review = self.review_service.review_section(doc_id, template, section_id, strict=False, normative=normative)
```

Replace `pack_context_document`'s signature (lines 161-176):

```python
    def pack_context_document(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
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
    ) -> Path:
```

with:

```python
    def pack_context_document(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        *,
        manifest_exists: bool,
        manifest_size: int,
        normative: NormativeSettings,
    ) -> Path:
```

Replace its body's call to `review_service.review_document` (Task 6's `NormativeSettings(...)` construction at lines 210-223) with a direct pass-through:

```python
        review = self.review_service.review_document(
            doc_id, template, strict=False, manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )
```

Now fix the 2 callers.

In `src/docs/application/pipeline.py`, `stage_pack_context` (inside `_stage_callables`, lines 161-172):

```python
        def stage_pack_context() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            paths = [
                str(self.context_pack_service.pack_context(doc_id, template, section.id, config, **normative))
                for section in template.sections
            ]
            self.context_pack_service.pack_context_document(
                doc_id, template, config,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            )
            return True, f"{len(paths)} context packs + 1 documento"
```

becomes:

```python
        def stage_pack_context() -> tuple[bool, str]:
            normative = NormativeSettings(**resolve_normative_settings(config))
            manifest_exists, manifest_size = self.rules_manifest_state(config)
            paths = [
                str(self.context_pack_service.pack_context(doc_id, template, section.id, config, normative=normative))
                for section in template.sections
            ]
            self.context_pack_service.pack_context_document(
                doc_id, template, config,
                manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
            )
            return True, f"{len(paths)} context packs + 1 documento"
```

In `src/docs/cli/main.py`, `pack_context` command (lines 192-215):

```python
@app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)

    def pack_one(sid: str) -> Path:
        return deps.context_pack.pack_context(resolved.doc_id, resolved.template, sid, resolved.config, **normative)

    def pack_document() -> Path:
        return deps.context_pack.pack_context_document(
            resolved.doc_id, resolved.template, resolved.config,
            manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
        )
```

becomes:

```python
@app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = NormativeSettings(**resolve_normative_settings(resolved.config))
    manifest_exists, manifest_size = deps.pipeline.rules_manifest_state(resolved.config)

    def pack_one(sid: str) -> Path:
        return deps.context_pack.pack_context(resolved.doc_id, resolved.template, sid, resolved.config, normative=normative)

    def pack_document() -> Path:
        return deps.context_pack.pack_context_document(
            resolved.doc_id, resolved.template, resolved.config,
            manifest_exists=manifest_exists, manifest_size=manifest_size, normative=normative,
        )
```

Finally, in `tests/integration/test_context_pack_service.py`, replace the two module-level constants (lines 14-30):

```python
_REVIEW_KWARGS = dict(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)

_REVIEW_DOCUMENT_KWARGS = dict(
    manifest_exists=True,
    manifest_size=10,
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)
```

with:

```python
from docs.domain.normative import NormativeSettings

_NORMATIVE = NormativeSettings(
    excluded_terms={},
    is_policy_file=False,
    first_person_patterns=[],
    subjective_terms=[],
    secret_patterns=[],
)

_REVIEW_DOCUMENT_KWARGS = dict(manifest_exists=True, manifest_size=10, normative=_NORMATIVE)
```

(place the `from docs.domain.normative import NormativeSettings` import with the file's other imports at the top, not inline). Then replace every remaining `**_REVIEW_KWARGS` occurrence in the file with `normative=_NORMATIVE` — the file has 10 such occurrences across `pack_context` calls: lines 73, 81, 91, 107, 120, 133, 141, 151, 160, 182 (the one at line 73 was already converted in Step 1). The 5 `**_REVIEW_DOCUMENT_KWARGS` occurrences at lines 190, 206, 215, 226, 233 (`pack_context_document` calls) are left as `**_REVIEW_DOCUMENT_KWARGS` unchanged — the dict spread still works because the dict's 3rd key is now literally `normative`.

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_context_pack_service.py tests/integration/test_pipeline_service.py tests/integration/test_cli_section.py`
Expected: PASS

Then run the full suite: `rtk pytest -q` — expected 749+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/context_pack.py src/docs/application/pipeline.py src/docs/cli/main.py tests/integration/test_context_pack_service.py
git commit -m "refactor(context_pack): pack_context/pack_context_document accept NormativeSettings"
```

---

### Task 8: `resolve_normative_settings` returns `NormativeSettings` — final cleanup

**Files:**
- Modify: `src/docs/domain/normative.py:50-67`
- Modify: `src/docs/application/pipeline.py:161-172,174-181,250-256`
- Modify: `src/docs/cli/main.py:196-206,227-228,241-245`
- Test: `tests/unit/domain/test_normative.py` (create if it does not exist — check first)

**Interfaces:**
- Consumes: `NormativeSettings` (Task 5), the now-`normative=`-accepting signatures of `ReviewService` (Task 6) and `ContextPackService` (Task 7).
- Produces: `resolve_normative_settings(config: dict[str, Any]) -> NormativeSettings` (return type changed from `dict[str, Any]`) — this is the final state finding 4 asked for: all 5 originally-listed signatures plus the function that feeds them now speak `NormativeSettings` exclusively, with zero remaining `**dict`-spread or double-wrap anywhere in the codebase.

- [ ] **Step 1: Write the failing test**

Check whether `tests/unit/domain/test_normative.py` already exists (`ls tests/unit/domain/`). If it does, add the test there; if not, create it. Add:

```python
# tests/unit/domain/test_normative.py
from docs.domain.normative import NormativeSettings, resolve_normative_settings


def test_resolve_normative_settings_returns_normative_settings_instance():
    config = {"normative": {}, "privacy": {}}
    result = resolve_normative_settings(config)
    assert isinstance(result, NormativeSettings)
    assert result.is_policy_file is False
    assert result.scope_term == ""


def test_resolve_normative_settings_reads_overrides_from_config():
    config = {
        "normative": {
            "excluded_front_matter": {"anexo": "excluido"},
            "first_person_patterns": [r"\bnosotros\b"],
            "subjective_terms": ["genial"],
            "scope_term": "aws",
            "scope_focus": "backend",
        },
        "privacy": {"forbidden_in_body_patterns": [r"\bsecreto-interno\b"]},
    }
    result = resolve_normative_settings(config)
    assert result.excluded_terms == {"anexo": "excluido"}
    assert result.first_person_patterns == [r"\bnosotros\b"]
    assert result.subjective_terms == ["genial"]
    assert result.scope_term == "aws"
    assert result.scope_focus == "backend"
    assert r"\bsecreto-interno\b" in result.secret_patterns
```

If the file already existed with other tests, keep them — only add these two.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/unit/domain/test_normative.py::test_resolve_normative_settings_returns_normative_settings_instance`
Expected: FAIL with `AssertionError: assert False` (`isinstance(result, NormativeSettings)` is `False` because `resolve_normative_settings` still returns a plain `dict`)

- [ ] **Step 3: Write minimal implementation**

In `src/docs/domain/normative.py`, replace `resolve_normative_settings` (lines 50-67):

```python
def resolve_normative_settings(config: dict[str, Any]) -> dict[str, Any]:
    """Extrae las kwargs normativas que review_section_text/review_document/
    pack_context(_document) requieren, con los mismos defaults que legacy
    review_section (1455-1458, 1473, 1477-1478). is_policy_file no se
    resuelve aquí: en este código base siempre es False en este punto de
    llamada (confirmado en la revisión previa a la ejecución de Slice 5)."""
    normative = config.get("normative", {})
    excluded = normative.get("excluded_front_matter", EXCLUDED_FRONT_MATTER)
    excluded_terms = excluded if isinstance(excluded, dict) else {term: "" for term in excluded}
    return {
        "excluded_terms": excluded_terms,
        "is_policy_file": False,
        "first_person_patterns": normative.get("first_person_patterns", FIRST_PERSON_PATTERNS),
        "subjective_terms": normative.get("subjective_terms", SUBJECTIVE_TERMS),
        "secret_patterns": SECRET_PATTERNS + list(config.get("privacy", {}).get("forbidden_in_body_patterns", [])),
        "scope_term": normative.get("scope_term", ""),
        "scope_focus": normative.get("scope_focus", ""),
    }
```

with:

```python
def resolve_normative_settings(config: dict[str, Any]) -> NormativeSettings:
    """Extrae las kwargs normativas que review_section_text/review_document/
    pack_context(_document) requieren, con los mismos defaults que legacy
    review_section (1455-1458, 1473, 1477-1478). is_policy_file no se
    resuelve aquí: en este código base siempre es False en este punto de
    llamada (confirmado en la revisión previa a la ejecución de Slice 5)."""
    normative = config.get("normative", {})
    excluded = normative.get("excluded_front_matter", EXCLUDED_FRONT_MATTER)
    excluded_terms = excluded if isinstance(excluded, dict) else {term: "" for term in excluded}
    return NormativeSettings(
        excluded_terms=excluded_terms,
        is_policy_file=False,
        first_person_patterns=normative.get("first_person_patterns", FIRST_PERSON_PATTERNS),
        subjective_terms=normative.get("subjective_terms", SUBJECTIVE_TERMS),
        secret_patterns=SECRET_PATTERNS + list(config.get("privacy", {}).get("forbidden_in_body_patterns", [])),
        scope_term=normative.get("scope_term", ""),
        scope_focus=normative.get("scope_focus", ""),
    )
```

Now remove the now-redundant `NormativeSettings(**resolve_normative_settings(...))` double-wrap at all 6 call sites introduced in Tasks 6–7.

In `src/docs/application/pipeline.py`, `stage_pack_context`:

```python
            normative = NormativeSettings(**resolve_normative_settings(config))
```

becomes:

```python
            normative = resolve_normative_settings(config)
```

`stage_review_document`: same replacement. `verify_all`: same replacement (3 occurrences total in this file).

In `src/docs/cli/main.py`, `pack_context` command:

```python
    normative = NormativeSettings(**resolve_normative_settings(resolved.config))
```

becomes:

```python
    normative = resolve_normative_settings(resolved.config)
```

`review_section` command: same replacement. `review_document` command: same replacement (3 occurrences total in this file). Since `NormativeSettings` is no longer directly referenced in `cli/main.py` after this cleanup, revert its import back to just `resolve_normative_settings`:

```python
from docs.domain.normative import resolve_normative_settings
```

In `src/docs/application/pipeline.py`, likewise revert the import back to:

```python
from docs.domain.normative import resolve_normative_settings
```

(check the file first — if `NormativeSettings` ends up unused after this cleanup, `ruff`/flake8-style unused-import lint would flag it; since this project has no lint gate configured in `pyproject.toml` per Global Constraints research, this is a cleanliness step, not a required-to-pass-CI step, but do it anyway for a clean diff).

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/unit/domain/test_normative.py tests/integration/test_pipeline_service.py tests/integration/test_cli_core.py tests/integration/test_cli_section.py tests/integration/test_cli_collection.py`
Expected: PASS

Then run the full suite: `rtk pytest -q` — expected 751+ passed, 0 failed. This is the last task in the finding-4 chain: grep-verify with `rtk grep -n "NormativeSettings(\*\*resolve_normative_settings" src/` — expected **zero** matches, confirming the temporary double-wrap introduced in Tasks 6–7 is fully gone.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/normative.py src/docs/application/pipeline.py src/docs/cli/main.py tests/unit/domain/test_normative.py
git commit -m "refactor(normative): resolve_normative_settings returns NormativeSettings directly"
```

---

### Task 9: Split `_build_main_document` (SRP)

**Files:**
- Modify: `src/docs/infrastructure/docx/python_docx_assembly_adapter.py:370-454`
- Test: `tests/unit/infrastructure/test_python_docx_assembly_adapter.py` (create if it does not exist under this exact path — check `tests/integration/test_docx_assembly_service.py` first, which tests `DocxAssemblyService`, the application-layer wrapper, not this adapter directly; if no adapter-level unit test file exists yet, create one)

**Interfaces:**
- Consumes: nothing new.
- Produces: 4 new private methods on `PythonDocxAssemblyAdapter` — `_configure_preliminary_pagination(cover, sections_part, config) -> None`, `_render_leading_parts(cover, config, leading) -> None`, `_transfer_body_paragraphs(cover, body, sections_part, config) -> None`, `_transfer_body_tables(cover, body) -> None` — consumed only by `_build_main_document` itself (all still private, matching the class's existing `_cover_base_document`/`_sections_index` convention).

- [ ] **Step 1: Write the failing test**

Check first whether `tests/unit/infrastructure/test_python_docx_assembly_adapter.py` exists (`ls tests/unit/infrastructure/`). Create it if absent:

```python
# tests/unit/infrastructure/test_python_docx_assembly_adapter.py
from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter


def test_transfer_body_tables_copies_cell_text_into_new_table():
    adapter = PythonDocxAssemblyAdapter()
    cover = Document()
    body = Document()
    table = body.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "a"
    table.cell(0, 1).text = "b"
    table.cell(1, 0).text = "c"
    table.cell(1, 1).text = "d"

    adapter._transfer_body_tables(cover, body)

    assert len(cover.tables) == 1
    new_table = cover.tables[0]
    assert new_table.cell(0, 0).text == "a"
    assert new_table.cell(1, 1).text == "d"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/unit/infrastructure/test_python_docx_assembly_adapter.py::test_transfer_body_tables_copies_cell_text_into_new_table`
Expected: FAIL with `AttributeError: 'PythonDocxAssemblyAdapter' object has no attribute '_transfer_body_tables'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`, replace `_build_main_document` (lines 370-454) with the orchestrator plus 4 extracted methods:

```python
    def _build_main_document(self, config: dict[str, Any], body_docx: Path, cover_asset_path: Path | None):
        from docx import Document

        parts = structure_parts(config)
        sections_index = self._sections_index(parts)
        sections_part = parts[sections_index] if sections_index < len(parts) else {"type": "sections"}
        leading = parts[:sections_index]

        has_cover_from_asset_part = any(p.get("type") == "cover_from_asset" for p in leading)
        cover = self._cover_base_document(config, cover_asset_path, has_cover_from_asset_part)
        body = Document(str(body_docx))

        self._configure_preliminary_pagination(cover, sections_part, config)
        self._render_leading_parts(cover, config, leading)
        self._transfer_body_paragraphs(cover, body, sections_part, config)
        self._transfer_body_tables(cover, body)

        return cover

    def _configure_preliminary_pagination(self, cover: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.enum.section import WD_SECTION_START

        prelim_pag = sections_part.get("preliminary_pagination", {})
        prelim_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
        if prelim_pag:
            configure_roman_preliminary_section(prelim_section, config, int(prelim_pag.get("start", 2)))
            if prelim_pag.get("format"):
                set_section_page_number_start(
                    prelim_section, int(prelim_pag.get("start", 2)), prelim_pag["format"]
                )
        else:
            configure_unnumbered_section(prelim_section, config)

    def _render_leading_parts(self, cover: Any, config: dict[str, Any], leading: list[dict[str, Any]]) -> None:
        from docx.enum.text import WD_BREAK

        for part in leading:
            kind = part.get("type")
            if kind in {"cover_from_template", "cover_from_asset", "embed_docx", "sections"}:
                continue
            if kind == "blank_page":
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            elif kind in {"fixed_text_page", "toc"}:
                if kind == "toc":
                    cover.add_paragraph("[[TOC]]")
                else:
                    add_fixed_text_page(cover, resolve_part_text(config, part))
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def _transfer_body_paragraphs(self, cover: Any, body: Any, sections_part: dict[str, Any], config: dict[str, Any]) -> None:
        from docx.enum.section import WD_SECTION_START
        from docx.enum.text import WD_BREAK
        from docx.shared import Pt, RGBColor

        restart_id = sections_part.get("body_restart_section", "")
        restart_heading = ""
        if restart_id:
            section = next((s for s in config.get("sections", []) if s.get("id") == restart_id), None)
            restart_heading = normalize_heading(section["title"] if section else restart_id)
        body_pag = sections_part.get("body_pagination", {"format": "decimal", "start": 1})

        body_heading_seen = False
        restart_started = False
        for paragraph in body.paragraphs:
            style_name = safe_style_name(cover, paragraph.style.name if paragraph.style else None)
            is_list = paragraph_has_numbering(paragraph)
            if is_list:
                style_name = safe_style_name(cover, "List Bullet") or style_name
            paragraph_text = paragraph.text.strip()
            is_heading_1 = style_name == "Heading 1"
            is_restart = is_heading_1 and restart_heading and normalize_heading(paragraph_text) == restart_heading
            if is_restart and not restart_started:
                numbered_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
                configure_numbered_body_section(numbered_section, config)
                set_section_page_number_start(
                    numbered_section, int(body_pag.get("start", 1)), body_pag.get("format", "decimal")
                )
                restart_started = True
            elif is_heading_1 and body_heading_seen:
                cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            new_paragraph = cover.add_paragraph(style=style_name)
            apply_normative_paragraph_format(new_paragraph, style_name, paragraph_text, is_list=is_list)
            if is_heading_1:
                body_heading_seen = True
            for run in paragraph.runs:
                new_run = new_paragraph.add_run(run.text)
                new_run.bold = run.bold
                new_run.italic = run.italic
                new_run.underline = run.underline
                new_run.font.name = "Times New Roman"
                new_run.font.size = Pt(12)
                new_run.font.color.rgb = RGBColor(0, 0, 0)

    def _transfer_body_tables(self, cover: Any, body: Any) -> None:
        for table in body.tables:
            new_table = cover.add_table(rows=len(table.rows), cols=len(table.columns))
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    new_table.cell(row_idx, col_idx).text = cell.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/unit/infrastructure/test_python_docx_assembly_adapter.py tests/integration/test_docx_assembly_service.py tests/integration/test_python_docx_assembly_adapter.py`
Expected: PASS — the new direct test passes, and every existing `DocxAssemblyService`/`PythonDocxAssemblyAdapter` integration test passes unchanged (proving the split is byte-for-byte behavior-preserving: same `.docx` output for the same inputs).

Then run the full suite: `rtk pytest -q` — expected 752+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/docx/python_docx_assembly_adapter.py tests/unit/infrastructure/test_python_docx_assembly_adapter.py
git commit -m "refactor(docx_assembly_adapter): split _build_main_document into 4 focused private methods"
```

---

### Task 10: Split `PythonDocxAuditAdapter.audit` (SRP)

**Files:**
- Modify: `src/docs/infrastructure/docx/python_docx_audit_adapter.py:1-11,47-159`
- Test: `tests/integration/test_python_docx_audit_adapter.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: 7 new private methods on `PythonDocxAuditAdapter` — `_check_body_restart_pagination`, `_check_fixed_text_pages_present`, `_check_pagination_markers`, `_check_non_cover_margins`, `_check_heading_style`, `_check_table_borders`, `_check_figure_captions`, `_check_strict_paragraph_formatting` — consumed only by `audit()` itself.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_python_docx_audit_adapter.py` (check the file's existing imports/fixtures first — it presumably already builds `.docx` fixtures via `python-docx` for the existing `audit()`-level tests; reuse that same fixture-construction style):

```python
def test_check_table_borders_flags_vertical_borders_and_shading():
    from docx import Document

    adapter = PythonDocxAuditAdapter()
    document = Document()
    table = document.add_table(rows=1, cols=2)
    # Inject a vertical-border XML fragment directly, mirroring how
    # table_has_vertical_borders_or_shading (already tested elsewhere in this
    # file) is exercised — a plain python-docx table has no borders by default.
    from docx.oxml.ns import qn

    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.makeelement(qn("w:tblBorders"), {})
    left = borders.makeelement(qn("w:left"), {qn("w:val"): "single"})
    borders.append(left)
    tbl_pr.append(borders)

    issues = adapter._check_table_borders(document)

    assert any("bordes verticales" in i.message for i in issues)
```

If the file already has a fixture/helper that constructs a table with vertical borders for the existing whole-`audit()` test of this same rule, reuse that helper instead of duplicating the XML-injection code above — check for a function like `_table_with_vertical_border(document)` or similar in the file first via `rtk grep -n "vertical" tests/integration/test_python_docx_audit_adapter.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_python_docx_audit_adapter.py::test_check_table_borders_flags_vertical_borders_and_shading`
Expected: FAIL with `AttributeError: 'PythonDocxAuditAdapter' object has no attribute '_check_table_borders'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/infrastructure/docx/python_docx_audit_adapter.py`, replace `audit` (lines 47-159) with the orchestrator plus 8 extracted methods:

```python
    def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]:
        from docx import Document

        document = Document(str(docx_path))
        issues: list[Issue] = []
        headings = [(p.style.name if p.style else "", p.text.strip()) for p in document.paragraphs if p.text.strip()]
        heading_texts = [text for style, text in headings if style.startswith("Heading")]

        parts = structure_parts(config)
        sections_part = next((p for p in parts if p.get("type") == "sections"), {})
        fixed_texts = [resolve_part_text(config, p) for p in parts if p.get("type") == "fixed_text_page"]
        prelim_pag = sections_part.get("preliminary_pagination", {})
        body_pag = sections_part.get("body_pagination", {})
        restart_id = sections_part.get("body_restart_section", "")
        restart_title = ""
        if restart_id:
            section = next((s for s in config.get("sections", []) if s.get("id") == restart_id), None)
            restart_title = section["title"] if section else restart_id

        issues.extend(self._check_body_restart_pagination(document, heading_texts, restart_id, restart_title, strict))

        if strict:
            docx_xml = self.read_xml(docx_path, "word/document.xml")
            footer_xml = "\n".join(self.read_xml(docx_path, name) for name in self.list_parts(docx_path, "word/footer"))
            issues.extend(self._check_fixed_text_pages_present(docx_xml, fixed_texts))
            issues.extend(self._check_pagination_markers(docx_xml, footer_xml, prelim_pag, body_pag))
            issues.extend(self._check_non_cover_margins(document, config))

        issues.extend(self._check_heading_style(headings))
        issues.extend(self._check_table_borders(document))

        body_start = 0
        for i, paragraph in enumerate(document.paragraphs):
            if paragraph.style and paragraph.style.name == "Heading 1":
                body_start = i
                break
        issues.extend(self._check_figure_captions(document, body_start))

        if strict:
            issues.extend(self._check_strict_paragraph_formatting(document, body_start))

        return issues

    def _check_body_restart_pagination(
        self, document: Any, heading_texts: list[str], restart_id: str, restart_title: str, strict: bool
    ) -> list[Issue]:
        issues: list[Issue] = []
        if strict and restart_id and len(document.sections) < 2:
            issues.append(Issue("error", "El DOCX no tiene secciones suficientes para el reinicio de paginación del cuerpo."))
        if strict and restart_title and not any(normalize_heading(restart_title) in normalize_heading(text) for text in heading_texts):
            issues.append(Issue("warning", f"No se detectó el título `{restart_title}`; no puede verificarse el reinicio de paginación."))
        return issues

    def _check_fixed_text_pages_present(self, docx_xml: str, fixed_texts: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for fixed_text in fixed_texts:
            if fixed_text and fixed_text not in docx_xml:
                issues.append(Issue("error", "No se encontró una página de texto fijo declarada en la estructura."))
        return issues

    def _check_pagination_markers(
        self, docx_xml: str, footer_xml: str, prelim_pag: dict[str, Any], body_pag: dict[str, Any]
    ) -> list[Issue]:
        issues: list[Issue] = []
        paginated = 0
        if prelim_pag.get("format"):
            paginated += 1
            start = prelim_pag.get("start", 2)
            fmt = prelim_pag["format"]
            if not re.search(
                rf"<w:pgNumType\b[^>]*w:start=\"{start}\"[^>]*w:fmt=\"{fmt}\"|<w:pgNumType\b[^>]*w:fmt=\"{fmt}\"[^>]*w:start=\"{start}\"",
                docx_xml,
            ):
                issues.append(Issue("error", "No se detectó la paginación de preliminares declarada en la estructura."))
        if body_pag.get("format"):
            paginated += 1
            if not re.search(rf"<w:pgNumType\b[^>]*w:start=\"{body_pag.get('start', 1)}\"", docx_xml):
                issues.append(Issue("error", "La sección del cuerpo no reinicia la paginación según la estructura."))
        if paginated:
            if "PAGE" not in footer_xml:
                issues.append(Issue("error", "No se encontró campo PAGE en el pie de página de las secciones numeradas."))
            if 'w:jc w:val="right"' not in footer_xml:
                issues.append(Issue("error", "El campo de paginación no está alineado a la derecha."))
            if footer_xml.count("PAGE") < paginated:
                issues.append(Issue("error", "Faltan campos PAGE para las secciones paginadas declaradas."))
        return issues

    def _check_non_cover_margins(self, document: Any, config: dict[str, Any]) -> list[Issue]:
        issues: list[Issue] = []
        expected_margins = non_cover_margin_emu(config)
        if expected_margins:
            for section_index, section in enumerate(document.sections):
                if section_index == 0:
                    continue
                actual_margins = _section_margin_emu(section)
                if not margins_match(actual_margins, expected_margins):
                    issues.append(
                        Issue("error", f"La sección {section_index + 1} no conserva márgenes de 2.5 cm en todos los lados.")
                    )
                    break
        return issues

    def _check_heading_style(self, headings: list[tuple[str, str]]) -> list[Issue]:
        issues: list[Issue] = []
        for style, text in headings:
            if style == "Heading 1" and text != text.upper():
                issues.append(Issue("warning", f"Título de primer orden no está en mayúsculas sostenidas: `{text}`."))
            if style == "Heading 1" and re.match(r"^\d+(\.\d+)*\s+", text):
                issues.append(Issue("warning", f"Título de primer orden parece numerado manualmente: `{text}`."))
        return issues

    def _check_table_borders(self, document: Any) -> list[Issue]:
        issues: list[Issue] = []
        for idx, table in enumerate(document.tables, start=1):
            if table_has_vertical_borders_or_shading(table):
                issues.append(
                    Issue("error", f"Tabla {idx} contiene bordes verticales o sombreado; el manual exige sólo líneas horizontales sin colores.")
                )
        return issues

    def _check_figure_captions(self, document: Any, body_start: int) -> list[Issue]:
        issues: list[Issue] = []
        image_paragraphs = [
            i
            for i, p in enumerate(document.paragraphs[body_start:], start=body_start)
            if "<w:drawing" in p._p.xml or "<w:pict" in p._p.xml
        ]
        for paragraph_index in image_paragraphs:
            next_text = ""
            if paragraph_index + 1 < len(document.paragraphs):
                next_text = document.paragraphs[paragraph_index + 1].text.strip()
            if not re.match(r"^Figura\s+\d+\.", next_text, re.IGNORECASE):
                issues.append(Issue("warning", "Figura detectada sin caption inferior con patrón `Figura N.`."))
        return issues

    def _check_strict_paragraph_formatting(self, document: Any, body_start: int) -> list[Issue]:
        from docx.shared import Cm, Pt

        issues: list[Issue] = []
        for paragraph in document.paragraphs[body_start:]:
            text = paragraph.text.strip()
            style_name = paragraph.style.name if paragraph.style else ""
            if not text or style_name == "Heading 1":
                continue
            paragraph_format = paragraph.paragraph_format
            if paragraph_format.line_spacing != 1.5:
                issues.append(Issue("error", f"Párrafo sin interlineado 1.5: `{text[:60]}`."))
                break
            if paragraph_format.space_after != Pt(18):
                issues.append(Issue("error", f"Párrafo sin espacio posterior de 18 pt: `{text[:60]}`."))
                break
            if style_name.startswith("List") or paragraph_has_numbering(paragraph):
                if paragraph_format.first_line_indent not in {None, 0}:
                    issues.append(Issue("error", f"Lista con sangría inicial no permitida: `{text[:60]}`."))
                    break
                continue
            if paragraph_format.first_line_indent is None or abs(paragraph_format.first_line_indent - Cm(1.25)) > 10000:
                issues.append(Issue("error", f"Párrafo ordinario sin sangría inicial de 1.25 cm: `{text[:60]}`."))
                break
        return issues
```

Note the original method-level `from docx.shared import Cm, Pt` (previously line 49, at the top of `audit()`) is dropped from `audit()` itself since neither symbol is used there anymore — `Pt`/`Cm` now live only inside `_check_strict_paragraph_formatting`, the only method that uses them.

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_python_docx_audit_adapter.py tests/integration/test_format_audit_service.py tests/integration/test_qa_service.py tests/integration/test_pipeline_service.py`
Expected: PASS — the new direct test passes, and every existing whole-`audit()` test (all 4 files depend on this adapter transitively) passes unchanged.

Then run the full suite: `rtk pytest -q` — expected 753+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/docx/python_docx_audit_adapter.py tests/integration/test_python_docx_audit_adapter.py
git commit -m "refactor(docx_audit_adapter): split audit() into 8 focused per-check private methods"
```

---

### Task 11: Split `review_rules` (SRP)

**Files:**
- Modify: `src/docs/domain/rules.py:280-343`
- Test: `tests/unit/domain/test_rules.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: 8 new private pure functions — `_check_manifest_state`, `_check_missing_section_contracts`, `_check_extracted_dir_policy`, `_check_source_priority_excludes_extracted`, `_check_apa7_enabled`, `_check_preliminaries_pagination`, `_check_margins_and_cover_policy`, `_check_margin_advisor_override_active`, `_check_section_contracts_content` — consumed only by `review_rules` itself.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/domain/test_rules.py` (near the existing `test_review_rules_*` tests, after line 368's `from docs.domain.rules import review_rules`):

```python
from docs.domain.rules import _check_apa7_enabled


def test_check_apa7_enabled_flags_when_disabled():
    template = Template.model_validate({"type": "x", "title": "X", "apa7": {"enabled": False}, **_valid_extra()})
    issues = _check_apa7_enabled(template)
    assert len(issues) == 1
    assert issues[0].message == "APA 7 debe estar habilitado."


def test_check_apa7_enabled_no_issues_when_enabled():
    template = _valid_template()
    assert _check_apa7_enabled(template) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/unit/domain/test_rules.py::test_check_apa7_enabled_flags_when_disabled`
Expected: FAIL with `ImportError: cannot import name '_check_apa7_enabled' from 'docs.domain.rules'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/domain/rules.py`, replace `review_rules` (lines 280-343) with the orchestrator plus 9 extracted functions:

```python
def _check_manifest_state(manifest_exists: bool, manifest_size: int, strict: bool) -> list[Issue]:
    issues: list[Issue] = []
    if not manifest_exists:
        issues.append(Issue("error" if strict else "warning", "No existe manual-rules.json; ejecuta `build-rules`."))
    elif manifest_size == 0:
        issues.append(Issue("error", "manual-rules.json existe pero está vacío."))
    return issues


def _check_missing_section_contracts(template: Template) -> list[Issue]:
    section_ids = {s.id for s in template.sections}
    contract_ids = set(template.section_contracts)
    missing_contracts = sorted(section_ids - contract_ids)
    if missing_contracts:
        return [Issue("error", f"Faltan contratos de sección: {', '.join(missing_contracts)}.")]
    return []


def _check_extracted_dir_policy(extra: dict[str, Any]) -> list[Issue]:
    paths = extra.get("paths", {}) or {}
    if paths.get("extracted_dir_policy") != "rules_traceability_only":
        return [Issue("error", "La política de extracted debe ser `rules_traceability_only`.")]
    return []


def _check_source_priority_excludes_extracted(extra: dict[str, Any]) -> list[Issue]:
    project = extra.get("project", {}) or {}
    if any("tesina/extracted" in source for source in project.get("source_priority", [])):
        return [Issue("error", "`tesina/extracted` no debe aparecer en source_priority como fuente activa.")]
    return []


def _check_apa7_enabled(template: Template) -> list[Issue]:
    if not template.apa7.enabled:
        return [Issue("error", "APA 7 debe estar habilitado.")]
    return []


def _check_preliminaries_pagination(extra: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    preliminaries = extra.get("preliminaries", {}) or {}
    if not preliminaries.get("roman_pagination", {}).get("enabled"):
        issues.append(Issue("error", "La paginación romana de preliminares debe estar habilitada."))
    if preliminaries.get("body_pagination_start", {}).get("section_id") != "introduccion":
        issues.append(Issue("error", "La paginación arábiga debe iniciar en INTRODUCCIÓN."))
    return issues


def _check_margins_and_cover_policy(extra: dict[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    margin_contract = (extra.get("format", {}) or {}).get("page_margins_cm", {}) or {}
    non_cover_margins = margin_contract.get("non_cover", {}) or {}
    bad_margins = [
        key
        for key in _MARGIN_KEYS
        if not isinstance(non_cover_margins.get(key), (int, float))
        or abs(float(non_cover_margins.get(key)) - _EXPECTED_MARGIN_CM) > _MARGIN_TOLERANCE
    ]
    if margin_contract.get("cover_policy") != "preserve_template":
        issues.append(Issue("error", "La portada debe conservar el formato y márgenes de la plantilla (`preserve_template`)."))
    if bad_margins:
        issues.append(Issue("error", "El contrato de layout debe fijar márgenes de 2.5 cm en toda sección no-portada."))
    return issues


def _check_margin_advisor_override_active(extra: dict[str, Any]) -> list[Issue]:
    active_overrides = {
        item.get("id") for item in extra.get("advisor_overrides", []) if item.get("status") == "active"
    }
    if "margins-2-5cm-non-cover" not in active_overrides:
        return [Issue("error", "Falta el advisor_override activo para márgenes de 2.5 cm excepto portada.")]
    return []


def _check_section_contracts_content(template: Template) -> list[Issue]:
    issues: list[Issue] = []
    for section_id, contract in template.section_contracts.items():
        if not contract.required_content:
            issues.append(Issue("error", f"El contrato `{section_id}` no define contenido obligatorio."))
        # Duplicates the document-level APA gate above when both fire — this is
        # real legacy behavior (review_rules never deduplicates), preserve it.
        if contract.apa_required and not template.apa7.enabled:
            issues.append(Issue("error", f"El contrato `{section_id}` requiere APA pero APA 7 está deshabilitado."))
    return issues


def review_rules(
    template: Template, manifest_exists: bool, manifest_size: int, strict: bool = False
) -> ReviewResult:
    extra = template.model_extra or {}
    issues: list[Issue] = []
    issues.extend(_check_manifest_state(manifest_exists, manifest_size, strict))
    issues.extend(_check_missing_section_contracts(template))
    issues.extend(_check_extracted_dir_policy(extra))
    issues.extend(_check_source_priority_excludes_extracted(extra))
    issues.extend(_check_apa7_enabled(template))
    issues.extend(_check_preliminaries_pagination(extra))
    issues.extend(_check_margins_and_cover_policy(extra))
    issues.extend(_check_margin_advisor_override_active(extra))
    issues.extend(_check_section_contracts_content(template))
    return ReviewResult(issues)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/unit/domain/test_rules.py`
Expected: PASS — the 2 new direct tests pass, and all 18 existing `test_review_rules_*` characterization tests (lines 393-527) pass unchanged, proving the split preserves the exact original issue set and ordering for every scenario, including the intentionally-duplicated APA gate (`test_review_rules_contract_apa_required_but_apa7_disabled_duplicates_document_level_issue`).

Then run the full suite: `rtk pytest -q` — expected 755+ passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "refactor(rules): split review_rules into 9 focused per-check pure functions"
```
