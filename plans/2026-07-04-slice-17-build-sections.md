# Slice 17 — `build-sections` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the last migration gap — `build-section`/`build-sections` — by adding `source_hash`/`prompt_hash` to `EvidenceService`, wiring the already-implemented pure scaffold renderer into a new `PipelineService.build_section` orchestration method, and pointing the two existing stub call sites (`stage_build_sections`, CLI `build-section`) at it.

**Architecture:** Zero new services, zero new ports, zero new constructor wiring. Two existing application services (`EvidenceService`, `PipelineService`) gain methods; one existing domain module (`domain/evidence.py`) gains two pure payload-builder functions. The pure markdown-scaffold renderer (`render_section_draft` and its three helpers) already exists, fully implemented and unit-tested, in `domain/section_rendering.py` — this plan imports it, it does not recreate it (see Judgment call 1).

**Tech Stack:** Python 3.11, `pytest` (via `rtk pytest -q` / `rtk proxy uv run pytest -q`), `pydantic` (unchanged), stdlib `dataclasses` and `hashlib`/`json` (all already in use, no new dependency).

## Global Constraints

- Byte-for-byte behavioral parity with the legacy scaffold text, PENDIENTE markers, and hash payload shapes (confirmed with the user in the design phase: faithful port, not a redesign).
- The 757 tests passing today (verified via `cd docs && rtk proxy uv run pytest -q` immediately before writing this plan: `757 passed, 7 skipped`) must keep passing at the end of **every** task, and the total test count must only increase — RED→GREEN per task.
- Hexagonal boundary preserved: `domain/` imports nothing from `application/` or `infrastructure/`; this slice adds no new `infrastructure/` code at all, so the application→port→adapter rule is not exercised, but must not be violated either.
- Zero new services, zero new ports, zero new constructor wiring for `PipelineService.__init__` or `EvidenceService.__init__`. Every task extends an existing class's public surface or adds pure functions to an existing domain module.
- No new third-party dependency.
- `ReviewService.build_section`'s existing signature (`src/docs/application/review.py:156-169`) is not touched — it is correct and tested as-is.
- All Spanish user-facing strings (PENDIENTE markers, disclaimer text, section titles) are copied **verbatim** — zero rewording — matching what `domain/section_rendering.py` already produces (itself already a verbatim port of `tesina_harness.py:1311-1396`).
- Every task is independently committable and leaves `rtk pytest -q` green. Run the full suite before Step 5 of every task, not just the file(s) touched in that task.

## Overview / Scope

This slice closes the one deliberate, explicitly-documented gap left open across Slices 6, 8, 14, and 15: `build-section`/`stage_build_sections` (`PipelineService`'s pipeline stage that renders each section's initial draft and stamps it with content hashes). Re-reading the current source with `codegraph_explore` (not re-trusting the "unmodeled" label carried forward by three prior slices) turned up two important facts that change the shape of this plan versus the approved design doc (`docs/specs/2026-07-04-slice-17-build-sections-design.md`):

1. **The pure scaffold renderer is already fully implemented and unit-tested.** `render_section_draft`, `render_toc_section`, `render_contract_scaffold`, `_summarize_context`, and `apply_keyword_bold` already exist in `src/docs/domain/section_rendering.py` (127 lines), with 24 passing unit tests in `tests/unit/domain/test_section_rendering.py` (241 lines) — verbatim behavioral parity with `tesina_harness.py:1311-1396` already achieved. **Zero external callers exist** (confirmed via `rg` across `src/`): the code is complete but unwired. This plan imports and wires it; it does not recreate it. See Judgment call 1.
2. **`source_hash` and `prompt_hash` are genuinely missing** — `EvidenceService` (`src/docs/application/evidence.py`) has `build_rules`, `rules_hash`, `contract_hash`, `manifest_hash`, `load_manifest_facts`, `render_fact_ledger` but no `source_hash`/`prompt_hash`. These are real, small additions (Tasks 1-2).

So the real remaining work is: 2 hash methods + their 2 domain payload-builder functions (Tasks 1-2), one parity-proof test for the already-shipped renderer (Task 3), one new orchestration method on `PipelineService` (Task 4), and rewiring the two existing stub call sites (Tasks 5-6).

### Judgment calls resolved before writing task code

1. **`render_section_draft` and its helpers stay in `domain/section_rendering.py`, not `domain/sections.py` as the approved design doc's Decision #2 specified.** Verified via direct `Read` of both files: `domain/sections.py` (68 lines) holds `infer_section_id_from_path`, `with_frontmatter`, `default_section_metadata`, `apply_stamp`, `generated_metadata_changed`, `section_by_id` — frontmatter/stamping concerns, no rendering. The renderer already lives, complete and tested, in the separate `domain/section_rendering.py` module, with a signature that differs slightly from the design doc's proposal: `render_section_draft(section_id: str, section_title: str, contract: SectionContract, context: dict[str, str], keyword_bold_terms: list[str]) -> str` (not `(section, contract, context, keyword_bold_terms)`). Recreating it in `domain/sections.py` would violate DRY and risk a second, diverging implementation. Decision: this plan treats `domain/section_rendering.py` as already-shipped production code (Task 3 adds one characterization test against it; no production code changes) and imports `render_section_draft` from it in Task 4.
2. **Per-section context is read via `ContextRepository.read_topic_raw(doc_id, topic.id)` guarded by `topic_exists(doc_id, topic.id)`, not `read_topic(doc_id, topic)` as the design doc's Decision #3 literally wrote.** This is a correctness fix, not a scope change — it still delivers Decision #3's actual intent (filter `Template.context_schema.topics` by `consumed_by`, never touch `context/index.json`). Hard evidence: `_summarize_context` (`domain/section_rendering.py:37-51`) regexes over **raw markdown table syntax** (`| **label** | value |`) via `_TABLE_ROW_RE`. `ContextRepository.read_topic` (`domain/ports/context_repository.py:11`) instead returns **already-parsed** values via `parse_topic` (`infrastructure/persistence/context_markdown.py:32-40`): a `dict[str, str]` of extracted field values for field-topics (which `_TABLE_ROW_RE.finditer(text)` cannot even accept — `text` would be a `dict`, not a `str`, raising `TypeError`), or a de-headinged prose string for prose-topics (which breaks `_summarize_context`'s heading-fallback branch, since the leading `# ` line it depends on has already been stripped by `parse_topic`, silently degrading the bullet's label from the real topic title to the bare topic id). Legacy's own `load_context_for` (`tesina_harness.py:734-746`) reads **raw** file text (`path.read_text(...)`) — this is exactly what `read_topic_raw` returns; `topic_exists` mirrors legacy's `if path.exists()` guard (`read_topic_raw` itself raises `FileNotFoundError` on a missing file, so the guard is required, not optional).
3. **No new port method for globbing.** `EvidenceRepository.list_manual_files(dir: Path) -> list[Path]` is, despite its name, directory-agnostic (`sorted(dir.glob("*.md"))`, confirmed at `infrastructure/persistence/json_evidence_repository.py:32-33`). Both new `EvidenceService` methods reuse it for their own directories (`context_dir`/`manual_dir` for `source_hash`, `prompts_dir` for `prompt_hash`) rather than adding a second, differently-named port method that would do the exact same thing (Global Constraint: zero new ports).
4. **Task 3 does not follow the RED→GREEN cycle in the literal sense.** There is no new production code to write — `render_contract_scaffold` already produces the correct output (Judgment call 1). The test is written to prove that, so Step 2 ("run to verify it fails") is replaced with "run to confirm it passes immediately," which is itself the parity proof this task exists to produce. Flagged explicitly rather than faked as a RED step that would never actually go red.

---

### Task 1: `domain/evidence.py` — `source_hash`/`prompt_hash` payload builders

**Files:**
- Modify: `src/docs/domain/evidence.py` (append after line 95, end of file)
- Test: `tests/unit/domain/test_evidence.py` (update import at line 2, append tests after line 165)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `SourceHashFileFact` (dataclass: `path: str`, `sha256: str`), `PromptHashFileFact` (dataclass: `name: str`, `sha256: str`), `build_source_hash_payload(files: list[SourceHashFileFact], config_sections: list[dict[str, Any]]) -> list[dict[str, Any]]`, `build_prompt_hash_payload(files: list[PromptHashFileFact]) -> list[dict[str, str]]` — all consumed by `EvidenceService.source_hash`/`prompt_hash` in Task 2.

- [ ] **Step 1: Write the failing test**

Update the import at the top of `tests/unit/domain/test_evidence.py` (currently line 2):

```python
from docs.domain.evidence import ManualFileFact, ManualHashFact, TraceabilityFact, build_manifest, build_rules_hash_payload
```

to:

```python
from docs.domain.evidence import (
    ManualFileFact,
    ManualHashFact,
    PromptHashFileFact,
    SourceHashFileFact,
    TraceabilityFact,
    build_manifest,
    build_prompt_hash_payload,
    build_rules_hash_payload,
    build_source_hash_payload,
)
```

Append at the end of the file (after line 165, the last line of `test_build_rules_hash_payload_preserves_manual_files_order`):

```python


def test_build_source_hash_payload_assembles_files_and_config_sections():
    fact = SourceHashFileFact(path="/repo/context/alumno.md", sha256="a" * 64)
    payload = build_source_hash_payload(files=[fact], config_sections=[{"id": "intro"}])
    assert payload == [
        {"path": fact.path, "sha256": fact.sha256},
        {"config_sections": [{"id": "intro"}]},
    ]


def test_build_source_hash_payload_empty_inputs():
    payload = build_source_hash_payload(files=[], config_sections=[])
    assert payload == [{"config_sections": []}]


def test_build_source_hash_payload_preserves_file_order():
    first = SourceHashFileFact(path="/repo/context/a.md", sha256="a" * 64)
    second = SourceHashFileFact(path="/repo/manual/b.md", sha256="b" * 64)
    payload = build_source_hash_payload(files=[first, second], config_sections=[])
    assert [entry["path"] for entry in payload[:2]] == [first.path, second.path]


def test_build_prompt_hash_payload_uses_bare_filename_under_path_key():
    # Legacy quirk (intentional, verbatim from tesina_harness.py:433-439): the
    # dict key is "path" but the value is the bare filename (path.name), not a
    # full path — prompts are hashed by filename only, unlike source_hash's files.
    fact = PromptHashFileFact(name="section-author.md", sha256="c" * 64)
    payload = build_prompt_hash_payload(files=[fact])
    assert payload == [{"path": "section-author.md", "sha256": fact.sha256}]


def test_build_prompt_hash_payload_empty_inputs():
    assert build_prompt_hash_payload(files=[]) == []


def test_build_prompt_hash_payload_preserves_order():
    first = PromptHashFileFact(name="a.md", sha256="a" * 64)
    second = PromptHashFileFact(name="b.md", sha256="b" * 64)
    payload = build_prompt_hash_payload(files=[first, second])
    assert [entry["path"] for entry in payload] == ["a.md", "b.md"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/unit/domain/test_evidence.py`
Expected: FAIL with `ImportError: cannot import name 'SourceHashFileFact' from 'docs.domain.evidence'`

- [ ] **Step 3: Write minimal implementation**

Append to the end of `src/docs/domain/evidence.py` (after line 95):

```python


@dataclass(frozen=True)
class SourceHashFileFact:
    path: str
    sha256: str


def build_source_hash_payload(
    files: list[SourceHashFileFact], config_sections: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [{"path": fact.path, "sha256": fact.sha256} for fact in files]
    payload.append({"config_sections": config_sections})
    return payload


@dataclass(frozen=True)
class PromptHashFileFact:
    name: str
    sha256: str


def build_prompt_hash_payload(files: list[PromptHashFileFact]) -> list[dict[str, str]]:
    # Legacy quirk (intentional, verbatim from tesina_harness.py:433-439): the
    # dict key is "path" but the value is the bare filename (path.name), not a
    # full path — prompts are hashed by filename only, unlike source_hash's files.
    return [{"path": fact.name, "sha256": fact.sha256} for fact in files]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/unit/domain/test_evidence.py`
Expected: PASS (17 existing + 6 new = 23 tests in this file)

Then run the full suite: `rtk pytest -q` — expected 763 passed, 7 skipped.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/evidence.py tests/unit/domain/test_evidence.py
git commit -m "feat(evidence): add source_hash/prompt_hash payload builders"
```

---

### Task 2: `application/evidence.py` — `EvidenceService.source_hash`/`prompt_hash`

**Files:**
- Modify: `src/docs/application/evidence.py:8` (import), insert new methods between lines 131 and 133
- Test: `tests/integration/test_evidence_service.py` (append after existing tests)

**Interfaces:**
- Consumes: `build_source_hash_payload`, `build_prompt_hash_payload`, `SourceHashFileFact`, `PromptHashFileFact` (Task 1); `EvidenceRepository.file_exists(path) -> bool`, `.list_manual_files(dir) -> list[Path]`, `.hash_file(path) -> str`, `.hash_json(value) -> str` (existing port methods, unchanged).
- Produces: `EvidenceService.source_hash(config: dict[str, Any]) -> str` and `EvidenceService.prompt_hash(config: dict[str, Any]) -> str`, consumed by `PipelineService.build_section` in Task 4.

- [ ] **Step 1: Write the failing test**

`tests/integration/test_evidence_service.py` already has a `service` fixture (lines 12-14) and a `_config(tmp_path, **overrides)` helper (lines 17-37) whose default `config["paths"]` includes `manual_dir` (created on disk), `extracted_dir`, `rules_manifest`. Append at the end of the file:

```python


def test_source_hash_hashes_context_and_manual_markdown_files_plus_config_sections(tmp_path: Path, service):
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    (context_dir / "alumno.md").write_text("# Alumno", encoding="utf-8")
    config = _config(tmp_path, paths={"context_dir": str(context_dir)}, sections=[{"id": "intro"}])
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Intro", encoding="utf-8")

    result = service.source_hash(config)

    context_file = context_dir / "alumno.md"
    manual_file = manual_dir / "00-intro.md"
    expected_payload = [
        {"path": context_file.resolve().as_posix(), "sha256": hashlib.sha256(context_file.read_bytes()).hexdigest()},
        {"path": manual_file.resolve().as_posix(), "sha256": hashlib.sha256(manual_file.read_bytes()).hexdigest()},
        {"config_sections": [{"id": "intro"}]},
    ]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_source_hash_skips_missing_context_dir_and_defaults_config_sections_to_empty(tmp_path: Path, service):
    config = _config(tmp_path, paths={"context_dir": str(tmp_path / "does-not-exist")})
    # manual_dir exists (from _config) but is empty; only the "config_sections"
    # sentinel entry survives, matching the "no sections in config" default.
    result = service.source_hash(config)
    expected_payload = [{"config_sections": []}]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_prompt_hash_hashes_markdown_files_under_prompts_dir(tmp_path: Path, service):
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "section-author.md").write_text("Eres un redactor.", encoding="utf-8")
    config = _config(tmp_path, paths={"prompts_dir": str(prompts_dir)})

    result = service.prompt_hash(config)

    prompt_file = prompts_dir / "section-author.md"
    expected_payload = [{"path": "section-author.md", "sha256": hashlib.sha256(prompt_file.read_bytes()).hexdigest()}]
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_prompt_hash_empty_payload_when_prompts_dir_missing(tmp_path: Path, service):
    config = _config(tmp_path, paths={"prompts_dir": str(tmp_path / "missing-prompts")})
    result = service.prompt_hash(config)
    expected = hashlib.sha256(json.dumps([], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_evidence_service.py::test_source_hash_hashes_context_and_manual_markdown_files_plus_config_sections`
Expected: FAIL with `AttributeError: 'EvidenceService' object has no attribute 'source_hash'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/evidence.py`, replace the import at line 8:

```python
from docs.domain.evidence import ManualFileFact, ManualHashFact, TraceabilityFact, build_manifest, build_rules_hash_payload
```

with:

```python
from docs.domain.evidence import (
    ManualFileFact,
    ManualHashFact,
    PromptHashFileFact,
    SourceHashFileFact,
    TraceabilityFact,
    build_manifest,
    build_prompt_hash_payload,
    build_rules_hash_payload,
    build_source_hash_payload,
)
```

Insert two new methods between `contract_hash` (ends at line 131) and `manifest_hash` (starts at line 133):

```python
    def source_hash(self, config: dict[str, Any]) -> str:
        relevant: list[Path] = []
        for key in ["context_dir", "manual_dir"]:
            value = config["paths"].get(key)
            if not value:
                continue
            root = Path(value)
            if self.repository.file_exists(root):
                relevant.extend(self.repository.list_manual_files(root))
        files = [
            SourceHashFileFact(path=path.resolve().as_posix(), sha256=self.repository.hash_file(path))
            for path in relevant
        ]
        payload = build_source_hash_payload(files, config.get("sections", []))
        return self.repository.hash_json(payload)

    def prompt_hash(self, config: dict[str, Any]) -> str:
        prompts_dir = Path(config["paths"]["prompts_dir"])
        files: list[PromptHashFileFact] = []
        if self.repository.file_exists(prompts_dir):
            files = [
                PromptHashFileFact(name=path.name, sha256=self.repository.hash_file(path))
                for path in self.repository.list_manual_files(prompts_dir)
            ]
        payload = build_prompt_hash_payload(files)
        return self.repository.hash_json(payload)

```

(This inserts immediately after `contract_hash`'s closing line — `return self.repository.hash_json(section_contracts.get(section_id, {}))` — and before `def manifest_hash(self, path_value: str | None) -> str:`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_evidence_service.py`
Expected: PASS (all existing tests plus the 4 new ones)

Then run the full suite: `rtk pytest -q` — expected 767 passed, 7 skipped.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/evidence.py tests/integration/test_evidence_service.py
git commit -m "feat(evidence): add EvidenceService.source_hash/prompt_hash"
```

---

### Task 3: Characterization test — `render_contract_scaffold` legacy parity

**Files:**
- Test only: `tests/unit/domain/test_section_rendering.py` (append after line 241, end of file)

**Interfaces:**
- Consumes: `render_contract_scaffold(section_title: str, contract: SectionContract, context: dict[str, str]) -> str` (`domain/section_rendering.py:54-86`, already implemented, unchanged by this task).
- Produces: nothing new — this is a parity-proof test, not new production surface.

- [ ] **Step 1: Write the test**

This is not a RED step in the usual sense (see Judgment call 4): `render_contract_scaffold` already produces this exact output. The test transcribes, line-by-line, what `tesina_harness.py:1342-1377`'s `render_contract_scaffold(config, section, context)` produces for a synthetic section that exercises every optional block (context, required_content, apa_required, references_list) simultaneously — the parity proof the design's Goal 1 requires.

Append to the end of `tests/unit/domain/test_section_rendering.py` (after line 241):

```python


class TestRenderContractScaffoldLegacyParity:
    def test_matches_legacy_render_contract_scaffold_byte_for_byte(self):
        # Transcribed line-by-line from tesina_harness.py:1342-1377's
        # render_contract_scaffold(config, section, context) for a synthetic
        # section exercising every optional block at once (context table row,
        # required_content PENDIENTEs, apa_required, references_list). This is
        # the parity proof Slice 17's design Goal 1 requires — it does not
        # exercise new code, it proves the already-shipped port is correct.
        contract = SectionContract(
            required_content=["alcance", "objetivo"],
            apa_required=True,
            references_list=True,
        )
        context = {"alumno": "| **Campo** | Información |\n| **Nombre** | Ana |\n"}

        body = render_contract_scaffold("Resultados", contract, context)

        expected = "\n".join(
            [
                "# Resultados",
                "",
                "_Borrador inicial generado por el arnés. Esta sección no debe "
                "considerarse lista hasta resolver todos los PENDIENTE con evidencia._",
                "",
                "## Contexto disponible",
                "",
                "- Nombre: Ana",
                "",
                "## Pendientes normativos",
                "",
                "- PENDIENTE: documentar alcance con evidencia del ledger, contexto o fuentes.",
                "- PENDIENTE: documentar objetivo con evidencia del ledger, contexto o fuentes.",
                "",
                "## Fuentes APA 7",
                "",
                "- PENDIENTE: agregar citas autor-fecha y referencias APA 7 realmente consultadas.",
                "",
                "PENDIENTE: ordenar alfabéticamente todas las fuentes citadas en el cuerpo conforme a APA 7.",
                "",
            ]
        )
        assert body == expected
```

- [ ] **Step 2: Run test to confirm it passes immediately**

Run: `rtk pytest -q tests/unit/domain/test_section_rendering.py::TestRenderContractScaffoldLegacyParity`
Expected: PASS immediately — `render_contract_scaffold` is already-shipped, already-correct code (Judgment call 1). A pass here is the parity proof itself, not a false-positive RED test masquerading as green.

- [ ] **Step 3: No implementation step**

There is no production code to write in this task — see Judgment call 4. If Step 2 had failed, that would mean `domain/section_rendering.py`'s existing implementation has drifted from legacy, which would need its own investigation (not expected; the file is covered by 24 passing unit tests already).

- [ ] **Step 4: Run the full suite**

Run: `rtk pytest -q` — expected 768 passed, 7 skipped.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/domain/test_section_rendering.py
git commit -m "test(section_rendering): add legacy parity characterization for render_contract_scaffold"
```

---

### Task 4: `PipelineService.build_section` — new public orchestration method

**Files:**
- Modify: `src/docs/application/pipeline.py:17` (import `SectionContract`), add import for `render_section_draft`, insert new method between lines 118 and 120
- Test: `tests/integration/test_pipeline_service.py` (insert after line 56, the end of the `_service` helper)

**Interfaces:**
- Consumes: `render_section_draft(section_id, section_title, contract, context, keyword_bold_terms) -> str` (`domain/section_rendering.py:89-100`, unchanged); `EvidenceService.source_hash/prompt_hash` (Task 2); `EvidenceService.rules_hash/contract_hash/manifest_hash` (existing, unchanged); `ContextRepository.topic_exists(doc_id, topic_id) -> bool` / `.read_topic_raw(doc_id, topic_id) -> str` (existing port methods, `domain/ports/context_repository.py:12,14`); `ReviewService.build_section(doc_id, template, section_id, body, *, source_hash, source_manifest_hash, code_evidence_manifest_hash, rules_hash, contract_hash, prompt_hash) -> Path` (existing, unchanged, `application/review.py:156-169`).
- Produces: `PipelineService.build_section(doc_id: str, template: Template, section_id: str, config: dict[str, Any]) -> Path`, consumed by `stage_build_sections` (Task 5) and the CLI `build-section` command (Task 6).

- [ ] **Step 1: Write the failing test**

Insert into `tests/integration/test_pipeline_service.py` immediately after the `_service` helper (after line 56, before `test_rules_manifest_state_goes_through_evidence_repository_not_direct_stat` at line 59):

```python


def test_build_section_renders_scaffold_gathers_six_hashes_and_writes_section_file(tmp_path: Path):
    from docs.domain.models.template import ContextSchema, Field, Section, SectionContract, Topic

    service, workspace = _service(tmp_path)
    topic = Topic(id="alumno", title="Alumno", consumed_by=["introduccion"], fields=[Field(key="nombre", label="Nombre")])
    template = Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract(required_content=["alcance"])},
        context_schema=ContextSchema(topics=[topic]),
    )
    service.context_repository.write_topic("doc-1", topic, {"nombre": "Ana"})
    config = {
        "paths": {
            "manual_dir": str(tmp_path / "manual"),
            "extracted_dir": str(tmp_path / "extracted"),
            "rules_manifest": str(tmp_path / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
            "prompts_dir": str(tmp_path / "prompts"),
            "source_manifest": str(tmp_path / "source-manifest.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence-manifest.json"),
        },
        "sections": [{"id": "introduccion"}],
        "section_contracts": {"introduccion": {"required_content": ["alcance"]}},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }

    path = service.build_section("doc-1", template, "introduccion", config)

    assert path.exists()
    raw = path.read_text(encoding="utf-8")
    assert "- Nombre: Ana" in raw
    assert "PENDIENTE: documentar alcance con evidencia del ledger, contexto o fuentes." in raw
    metadata = json.loads(raw.split("---\n")[1])
    assert metadata["section_id"] == "introduccion"
    assert len(metadata["source_hash"]) == 64
    assert len(metadata["prompt_hash"]) == 64
    assert len(metadata["rules_hash"]) == 64
    assert len(metadata["contract_hash"]) == 64
    assert metadata["source_manifest_hash"] == ""  # manifest never built -> manifest_hash("") sentinel
    assert metadata["code_evidence_manifest_hash"] == ""


def test_build_section_only_includes_context_topics_consumed_by_the_target_section(tmp_path: Path):
    from docs.domain.models.template import ContextSchema, Section, SectionContract, Topic

    service, workspace = _service(tmp_path)
    other_topic = Topic(id="otro", title="Otro", consumed_by=["otra-seccion"], multiline=True)
    template = Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract()},
        context_schema=ContextSchema(topics=[other_topic]),
    )
    service.context_repository.write_topic("doc-1", other_topic, "Texto no relacionado con introduccion.")
    config = {
        "paths": {
            "manual_dir": str(tmp_path / "manual"),
            "extracted_dir": str(tmp_path / "extracted"),
            "rules_manifest": str(tmp_path / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
            "prompts_dir": str(tmp_path / "prompts"),
            "source_manifest": str(tmp_path / "source-manifest.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence-manifest.json"),
        },
        "sections": [{"id": "introduccion"}],
        "section_contracts": {},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }

    path = service.build_section("doc-1", template, "introduccion", config)

    raw = path.read_text(encoding="utf-8")
    assert "Texto no relacionado" not in raw
```

Note: `Path(tmp_path / "manual").mkdir()` is not needed — `EvidenceService.source_hash`/`rules_hash` both guard with `file_exists` before listing, so a non-existent `manual_dir` is skipped safely (verified in Task 2).

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py::test_build_section_renders_scaffold_gathers_six_hashes_and_writes_section_file`
Expected: FAIL with `AttributeError: 'PipelineService' object has no attribute 'build_section'`

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/pipeline.py`, replace the import at line 17:

```python
from docs.domain.models.template import Template
```

with:

```python
from docs.domain.models.template import SectionContract, Template
from docs.domain.section_rendering import render_section_draft
```

(Insert the `render_section_draft` import as a new line immediately after; keep the existing `from docs.domain.models.template import Template` alphabetical position among the other `docs.domain.*` imports — i.e. the two lines together replace the single original line 17.)

Insert the new method between `context_confirmed_lines` (ends at line 118) and `_stage_callables` (starts at line 120):

```python
    def build_section(self, doc_id: str, template: Template, section_id: str, config: dict[str, Any]) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        contract = template.section_contracts.get(section_id, SectionContract())
        context: dict[str, str] = {}
        for topic in template.context_schema.topics:
            if section_id not in topic.consumed_by:
                continue
            if self.context_repository.topic_exists(doc_id, topic.id):
                context[topic.id] = self.context_repository.read_topic_raw(doc_id, topic.id)
        keyword_bold_terms = config.get("format", {}).get("keyword_bold_terms", {}).get(section_id, [])
        body = render_section_draft(section_id, section.title, contract, context, keyword_bold_terms)
        return self.review_service.build_section(
            doc_id, template, section_id, body,
            source_hash=self.evidence_service.source_hash(config),
            source_manifest_hash=self.evidence_service.manifest_hash(config["paths"].get("source_manifest")),
            code_evidence_manifest_hash=self.evidence_service.manifest_hash(
                config["paths"].get("code_evidence_manifest")
            ),
            rules_hash=self.evidence_service.rules_hash(config),
            contract_hash=self.evidence_service.contract_hash(config, section_id),
            prompt_hash=self.evidence_service.prompt_hash(config),
        )

```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py`
Expected: PASS (all existing tests plus the 2 new ones)

Then run the full suite: `rtk pytest -q` — expected 770 passed, 7 skipped.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/pipeline.py tests/integration/test_pipeline_service.py
git commit -m "feat(pipeline): add PipelineService.build_section orchestration method"
```

---

### Task 5: Wire `stage_build_sections` to `PipelineService.build_section`

**Files:**
- Modify: `src/docs/application/pipeline.py:154-159`
- Modify (existing tests that assumed permanent failure): `tests/integration/test_pipeline_service.py:278-297`

**Interfaces:**
- Consumes: `PipelineService.build_section(doc_id, template, section_id, config) -> Path` (Task 4).
- Produces: `stage_build_sections() -> tuple[bool, str]` (unchanged public shape — it is one of the closures returned by `_stage_callables`, keyed `"build-sections"`), now actually succeeding instead of always raising.

- [ ] **Step 1: Write the failing test**

Two existing tests in `tests/integration/test_pipeline_service.py` currently assert that `build-sections` **fails** (because of the `NotImplementedError` this task removes). They must be replaced — running them unmodified against the new implementation would itself be a false RED (the old assertions describe behavior this task intentionally changes), so replacing them here **is** this task's Step 1.

Replace `test_run_pipeline_prep_reports_build_sections_as_a_failed_stage` (currently lines 278-287):

```python
def test_run_pipeline_prep_reports_build_sections_as_a_failed_stage(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)  # gh unavailable -> collect-issues "omitido"
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage = next(s for s in summary["stages"] if s["stage"] == "build-sections")
    assert stage["ok"] is False
    assert "NotImplementedError" not in stage["detail"]  # detail is the exception message, not its type
    assert "build-section requiere" in stage["detail"]
```

with:

```python
def test_run_pipeline_prep_build_sections_succeeds_and_writes_the_section_file(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)  # gh unavailable -> collect-issues "omitido"
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage = next(s for s in summary["stages"] if s["stage"] == "build-sections")
    assert stage["ok"] is True
    assert stage["detail"] == "1 secciones"
    section_path = service.review_service.repository.section_path("doc1", 1, "introduccion")
    assert section_path.exists()
    assert "PENDIENTE: documentar algo con evidencia del ledger, contexto o fuentes." in section_path.read_text(
        encoding="utf-8"
    )
```

Replace `test_run_pipeline_prep_does_not_fail_fast_after_build_sections` (currently lines 290-297):

```python
def test_run_pipeline_prep_does_not_fail_fast_after_build_sections(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage_names = [s["stage"] for s in summary["stages"]]
    assert "pack-context" in stage_names  # ran despite build-sections failing (fail_fast=False)
```

with:

```python
def test_run_pipeline_prep_runs_pack_context_after_build_sections(tmp_path, monkeypatch):
    # build-sections now succeeds (Task 5); this test only confirms the stage
    # ordering/continuation still holds, not a failure-recovery scenario.
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    _patch_doctor_tools(monkeypatch)
    monkeypatch.setattr("shutil.which", lambda name: None)
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage_names = [s["stage"] for s in summary["stages"]]
    assert "pack-context" in stage_names
    pack_context_stage = next(s for s in summary["stages"] if s["stage"] == "pack-context")
    assert pack_context_stage["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py::test_run_pipeline_prep_build_sections_succeeds_and_writes_the_section_file`
Expected: FAIL — `stage["ok"]` is still `False` and `stage["detail"]` still contains `"build-section requiere"`, because `stage_build_sections` still raises `NotImplementedError` at this point.

- [ ] **Step 3: Write minimal implementation**

In `src/docs/application/pipeline.py`, replace lines 154-159:

```python
        def stage_build_sections() -> tuple[bool, str]:
            raise NotImplementedError(
                "build-section requiere un renderer de borradores y source_hash/"
                "prompt_hash aún no modelados en esta migración (ver Slice 6 y "
                "Slice 8, Design Decision 4)."
            )
```

with:

```python
        def stage_build_sections() -> tuple[bool, str]:
            paths = [str(self.build_section(doc_id, template, section.id, config)) for section in template.sections]
            return True, f"{len(paths)} secciones"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_pipeline_service.py`
Expected: PASS (both replaced tests, plus all other existing tests in the file)

Then run the full suite: `rtk pytest -q` — expected 770 passed, 7 skipped (2 tests replaced 1:1, no net change in count from Task 4's baseline).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/pipeline.py tests/integration/test_pipeline_service.py
git commit -m "feat(pipeline): wire stage_build_sections to PipelineService.build_section"
```

---

### Task 6: CLI `build-section <id>` command

**Files:**
- Modify: `src/docs/cli/main.py:156-166`
- Modify (existing test that assumed permanent failure): `tests/integration/test_cli_section.py:37-40`

**Interfaces:**
- Consumes: `deps.pipeline.build_section(doc_id, template, section_id, config) -> Path` (Task 4), `deps.resolve_context(doc) -> ResolvedContext` (existing, unchanged).
- Produces: the `build-section <id>` CLI command now writes the section file and prints its path (exit code 0), matching the pattern already established by the `build-ledger` command (`cli/main.py:145-153`: `deps, doc = _ctx(ctx)`; `resolved = deps.resolve_context(doc)`; call one service method; print/write).

- [ ] **Step 1: Write the failing test**

Replace `test_build_section_surfaces_unmodeled_gap_cleanly` in `tests/integration/test_cli_section.py` (currently lines 37-40):

```python
def test_build_section_surfaces_unmodeled_gap_cleanly(ws):
    result = runner.invoke(app, ["build-section", "introduccion"])
    assert result.exit_code == 1
    assert "build-section requiere" in result.output
```

with:

```python
def test_build_section_writes_scaffold_and_prints_path(ws):
    result = runner.invoke(app, ["build-section", "introduccion"])
    assert result.exit_code == 0
    path = Path(result.output.strip())
    assert path.exists()
    assert "PENDIENTE: documentar contexto con evidencia del ledger, contexto o fuentes." in path.read_text(
        encoding="utf-8"
    )
```

(This uses the `ws` fixture's `_TEMPLATE` already defined at the top of the file, lines 15-20, whose `section_contracts` is `{"introduccion": {"required_content": ["contexto"]}}` and whose `context_schema.topics` is `[]` — no context topics, so the scaffold contains only the title, disclaimer, and the one PENDIENTE line.)

- [ ] **Step 2: Run test to verify it fails**

Run: `rtk pytest -q tests/integration/test_cli_section.py::test_build_section_writes_scaffold_and_prints_path`
Expected: FAIL — `result.exit_code == 1` (the current stub), not `0`.

- [ ] **Step 3: Write minimal implementation**

In `src/docs/cli/main.py`, replace lines 156-166:

```python
_BUILD_SECTION_UNAVAILABLE = (
    "build-section requiere un renderer de borradores y source_hash/prompt_hash "
    "aún no modelados en esta migración (ver Slice 6 y Slice 8, Design Decision 4)."
)


@app.command("build-section")
def build_section(ctx: typer.Context, section_id: str = typer.Argument(...)) -> None:
    # Judgment call 3: surface the unmodeled gap cleanly, do not fake hashes.
    print(f"ERROR: {_BUILD_SECTION_UNAVAILABLE}", file=sys.stderr)
    raise typer.Exit(code=1)
```

with:

```python
@app.command("build-section")
def build_section(ctx: typer.Context, section_id: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.pipeline.build_section(resolved.doc_id, resolved.template, section_id, resolved.config))
```

`import sys` (line 5) stays — it is still used by `main()`'s error handler (`cli/main.py:473`).

- [ ] **Step 4: Run test to verify it passes**

Run: `rtk pytest -q tests/integration/test_cli_section.py`
Expected: PASS

Then run the full suite: `rtk pytest -q` — expected 770 passed, 7 skipped (1 test replaced 1:1, no net change from Task 5's baseline).

- [ ] **Step 5: Commit**

```bash
git add src/docs/cli/main.py tests/integration/test_cli_section.py
git commit -m "feat(cli): wire build-section command to PipelineService.build_section"
```
