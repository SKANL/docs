# Slice 14 — Pipeline & Run Logging · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 3159–3196 (`_git_commit`/`_runs_dir`/
`log_run`), 3199–3278 (`_pipeline_stages`), 3281–3304 (`run_pipeline`),
3307–3321 (`verify_all`), 3342–3352 (`list_runs`). The roadmap's cited range
(3152–3354) pads slightly past the actual function bodies to the next blank
line and also includes `parse_simple_yaml`/`apply_corrections`'s tail
(3152–3149, already shipped in Slice 13) and `command_doctor`'s head
(3355+, CLI — Slice 15) — not a real drift, confirmed by direct read.

## Overview / Scope

This is the terminal orchestration slice. Every capability shipped in
Slices 1–13 gets composed here into one `PipelineService` that reproduces
legacy's `run_pipeline`/`verify_all`/`log_run`/`_pipeline_stages`/`list_runs`.
Nothing in this range does new domain work of its own — it sequences,
times, and persists the outcomes of calls this migration has already built.

Four things happen in this slice:

1. Ports the two genuinely pure fragments in this range as new domain
   modules: the stage-ordering/fail-fast table `_pipeline_stages` builds
   (`domain/pipeline.py:pipeline_stage_plan`), and a new pure function,
   `domain/normative.py:resolve_normative_settings`, that closes a gap left
   open by every prior review-composing slice (see Judgment call 1 below).
2. Grows `SourceRepository` (Slice 7) with one method,
   `run_git_rev_parse_head(repo_root: Path) -> str`, needed for `log_run`'s
   `git_commit` field — the same external tool (`git`) that port's two
   existing methods (`run_git_log`, `detect_github_remote`) already shell
   out to.
3. Implements that one method on `FilesystemSourceRepository`.
4. Adds `PipelineService` (`application/pipeline.py`), composing
   `DoctorService`, `EvidenceService`, `EvidenceRepository`,
   `CollectionService`, `SourceRepository`, `ReviewService`,
   `ContextPackService`, `ContextRepository`, `DocxAssemblyService`,
   `FormatAuditService`, `QaService`, and `Workspace` — every collaborator
   the 13 pipeline stages touch, plus `Workspace` for the run-log directory
   default. `run_pipeline`/`verify_all`/`log_run`/`list_runs` all land on
   this one service.

### Judgment calls resolved before writing task code (all made by the plan
author — this run is unattended; each is the most defensible reading of
what's already shipped, not a guess)

1. **`resolve_normative_settings` is new pure groundwork this slice must
   add — it is not scope creep.** Legacy's `review_section` (1445–1499)
   inlines reading `config.get("normative", {})` for
   `excluded_front_matter`/`first_person_patterns`/`subjective_terms`/
   `scope_term`/`scope_focus`, plus `SECRET_PATTERNS + config["privacy"]
   ["forbidden_in_body_patterns"]`, falling back to four module-level
   constants (`EXCLUDED_FRONT_MATTER`, `FIRST_PERSON_PATTERNS`,
   `SUBJECTIVE_TERMS`, `SECRET_PATTERNS`, lines 68–110) when the config key
   is absent. **Confirmed by grep: none of these four constants, nor any
   config-extraction bridge for them, exist anywhere in `src/docs` today.**
   Slices 3, 5, 8, and 9 each shipped a consumer that *requires* these
   values as caller-supplied keyword arguments
   (`review_section_text`/`review_document`/`pack_context`/
   `pack_context_document`) and each one explicitly deferred building the
   bridge to "a future slice, or the CLI" (Slice 8's plan, Design Decision
   3, verbatim: *"The caller ... is responsible for resolving context via
   `ContextService`/`ContextRepository` before calling into this slice's
   pure rendering functions"* — same deferral pattern applies here).
   `PipelineService` is the first caller that actually needs to invoke
   `review_document`/`pack_context`/`pack_context_document` end-to-end from
   a raw `config` dict, so it is the first place this bridge is genuinely
   load-bearing. Porting it now is a verbatim port of already-real legacy
   logic (not new modeling), lands in `domain/` (pure — reads a plain
   dict, returns a plain dict, no I/O), and will be directly reusable by
   Slice 15's own `review-document`/`review-section`/`pack-context` CLI
   commands, which need the identical bridge.
2. **`is_policy_file` is hardcoded to `False` everywhere in this slice.**
   Already established as always-`False` in this exact code path by
   Slice 5's pre-execution review (`review_document`'s section files are
   always named via `SectionRepository`'s zero-padded convention, which
   never matches legacy's two hardcoded literals `"00-fact-ledger.md"`/
   `"README.md"`) — not a new finding, just re-applied here since
   `PipelineService` is a second caller of the same review functions.
3. **`build-sections` stage cannot be fully ported — it raises
   `NotImplementedError` with a citation, not silently omitted or faked.**
   Legacy's `_pipeline_stages` calls `build_section(config, section["id"])`
   per section — a self-contained legacy function that renders a draft
   body from context and computes `source_hash`/`prompt_hash` internally.
   The migrated `ReviewService.build_section` (Slice 8) instead takes
   `body: str`, `source_hash: str`, and `prompt_hash: str` as **required
   caller-supplied parameters** — a deliberate Slice 8 decision (Design
   Decision 4) because `source_hash` needs `context_dir`+`manual_dir`
   globbing combined with `config["sections"]`, and `prompt_hash` needs a
   `prompts_dir` config *concept this migration has never modeled*; both
   were explicitly carved out in Slice 6 and reconfirmed in Slice 8 as
   "speculative modeling" if ported early. Nothing has changed since —
   grepped again this session, still absent. Inventing a scaffold-rendering
   subsystem now, just to make one pipeline stage "work," would be exactly
   the speculative modeling both prior slices refused to do. Decision: the
   `build-sections` stage callable raises `NotImplementedError` citing this
   history; `run_pipeline`'s own generic `except Exception` stage-loop
   (already present in legacy, reused verbatim) catches it and records
   `("build-sections", ok=False, detail="ERROR: ...")`, exactly like any
   other real stage failure. Because `build-sections` is not `fail_fast`
   (`False` in legacy, preserved), `prep`/`all` runs continue past it to
   `pack-context` and beyond — this is a real, currently-permanent gap in
   `run_pipeline("prep")`'s "passed" outcome, surfaced honestly rather than
   hidden, and closeable later without touching this slice's shape once a
   future slice models draft-rendering + `prompts_dir`.
4. **`_context_confirmed_lines` drops legacy's `dato_sensible` ledger
   branch — a documented, inherited limitation, not a new bug.** Legacy's
   `render_fact_ledger` step 2 (1243–1257) routes non-sensitive topic
   fields into `grouped["confirmado"]` and sensitive fields into a
   *different* bucket, `grouped["dato_sensible"]`. The already-shipped
   `EvidenceService.render_fact_ledger(config, context_confirmed_lines:
   list[str] | None = None)` (Slice 8) only accepts **one** flat list that
   it appends entirely into `grouped["confirmado"]` — there is no parameter
   through which a second, differently-classified bucket of lines can be
   injected. Extending that signature is out of scope for this slice (it
   would mean re-opening already-shipped, already-reviewed Slice 8 code
   for a capability this slice doesn't strictly need to unblock its own
   scope). Decision: `PipelineService._context_confirmed_lines` computes
   only the non-sensitive branch (`if not value or field.sensitive:
   continue`) — sensitive fields are silently *dropped* from the ledger
   entirely in this slice's `build-ledger` stage, not mis-classified as
   confirmed. Flagged in "Risks" below with the exact future fix (extend
   `render_fact_ledger` with a second `context_sensitive_lines` param) so
   it isn't mistaken for a regression this slice introduced.
5. **`repo_root: Path` is a required parameter on `run_pipeline`, not a
   module constant or an optional-with-a-default.** Mirrors Slice 7's
   Design Decision 4 verbatim (`REPO_ROOT` has no equivalent in a library
   codebase with no "the script's own location"), extended here because
   `collect-issues`/`collect-code-evidence` stages need it exactly as
   `CollectionService.collect_issues`/`collect_code_evidence` already
   require it as a caller-supplied parameter. `verify_all` does **not**
   take `repo_root` — confirmed by re-reading legacy 3307–3321, it never
   calls `collect_issues`/`collect_code_evidence`/`log_run`.
6. **Run logs default to `workspace.doc_root(doc_id) / "runs"`, not a
   global `RUNS_DIR` constant — `config["paths"]["runs_dir"]` still
   overrides when set, matching legacy's own precedence.** Legacy's
   `_runs_dir(config)` checks `config["paths"].get("runs_dir")` first, else
   falls back to a single shared module-level `RUNS_DIR` path — legacy's
   own docstring on `log_run` already says *"por documento si hay
   config"* (per-document, if config says so), acknowledging the global
   fallback was itself a legacy compromise. This migration has modeled
   per-document run storage since Slice 1: `DocumentService._SUBDIRS`
   already provisions a `"runs"` subdirectory under every document's root
   at creation time. Falling back to `workspace.doc_root(doc_id)/"runs"`
   instead of a hardcoded global path is therefore not a new concept — it
   completes a per-document convention this migration already committed to
   in Slice 1, and it is strictly *more* correct for a multi-document
   library than legacy's single-shared-directory fallback.
7. **No new port for `log_run`/`list_runs`'s JSON file I/O.** Both do
   exactly one thing each: read/write a single JSON file, or glob a
   directory of them — no subprocess, no external tool. This is the exact
   category Slice 13's Design Decision 4 already resolved for
   `corrections_applied` (*"Reading/writing one JSON state file and
   globbing one directory ... is no more complex than [`DocxAssemblyService`
   tempdir writes / `QaService` mkdir+rmtree] ... the actual boundary this
   migration's Global Constraints have consistently drawn: only
   external-tool subprocess calls are pushed behind a port"*). Applying
   that same precedent here: `log_run`/`list_runs` do direct
   `pathlib`/`json` I/O inside `PipelineService`, no new port.
8. **`SourceRepository` grows by one method (`run_git_rev_parse_head`)
   rather than a new port being introduced for `_git_commit`.** The
   `git_commit` field's subprocess call (`git rev-parse --short HEAD`) is
   the exact external-tool-subprocess case that *does* need a port per the
   constraint above — the only real choice is *which* port. `SourceRepository`
   already contains two `git` subprocess methods (`run_git_log`,
   `detect_github_remote`) with the identical bare
   `except Exception: return <empty>` shape this new method needs. Growing
   that port (same underlying tool, same shape) is smaller and more
   consistent than introducing a bespoke one-method port; mirrors Slice
   11b's precedent for growing `DocxAssemblyPort` with `insert_toc_field`
   "because it operates on the same artifact family via the same
   underlying tool."

## Legacy code blocks (verbatim — as supplied, reused without modification
except where noted above)

### `_git_commit` / `_runs_dir` / `log_run` (lines 3159–3196)

```python
def _git_commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return ""
    return proc.stdout.strip()


def _runs_dir(config: dict[str, Any] | None = None) -> Path:
    if config:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
    return RUNS_DIR


def log_run(command: str, payload: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Registra una corrida en runs/<timestamp>.json para observabilidad (por documento si hay config)."""
    runs_dir = _runs_dir(config)
    runs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    record = {
        "timestamp": timestamp,
        "command": command,
        "git_commit": _git_commit(),
        **payload,
    }
    safe_name = timestamp.replace(":", "-")
    path = runs_dir / f"{safe_name}-{command}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
```

### `_pipeline_stages` (lines 3199–3278)

```python
def _pipeline_stages(config: dict[str, Any], stage_set: str, strict: bool) -> list[tuple[str, Any, bool]]:
    """Devuelve (nombre, callable->(ok, detalle), fail_fast) en orden de dependencias."""

    def stage_doctor() -> tuple[bool, str]:
        result = run_doctor(config, strict=strict)
        return result.passed, result.to_markdown()

    def stage_build_rules() -> tuple[bool, str]:
        return True, str(build_rules(config))

    def stage_review_rules() -> tuple[bool, str]:
        result = review_rules(config, strict=strict)
        return result.passed, result.to_markdown()

    def stage_collect_sources() -> tuple[bool, str]:
        return True, str(collect_sources(config))

    def stage_collect_code_evidence() -> tuple[bool, str]:
        return True, str(collect_code_evidence(config))

    def stage_collect_issues() -> tuple[bool, str]:
        try:
            return True, str(collect_issues(config))
        except Exception as exc:  # best-effort: gh puede no estar disponible
            return True, f"omitido: {exc}"

    def stage_build_ledger() -> tuple[bool, str]:
        path = Path(config["paths"]["fact_ledger"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_fact_ledger(config, load_context(config)), encoding="utf-8")
        return True, str(path)

    def stage_build_sections() -> tuple[bool, str]:
        paths = [str(build_section(config, section["id"])) for section in config["sections"]]
        return True, f"{len(paths)} secciones"

    def stage_pack_context() -> tuple[bool, str]:
        paths = [str(pack_context(config, section["id"])) for section in config["sections"]]
        pack_context_document(config)
        return True, f"{len(paths)} context packs + 1 documento"

    def stage_review_document() -> tuple[bool, str]:
        result = review_document(config, strict=strict)
        return result.passed, result.to_markdown()

    def stage_build_docx() -> tuple[bool, str]:
        return True, str(build_docx(config))

    def stage_format_audit() -> tuple[bool, str]:
        docx_path = Path(config["paths"]["output_draft_dir"]) / "tesina-draft.docx"
        result = format_audit_docx(docx_path, strict=strict, config=config)
        return result.passed, result.to_markdown()

    def stage_qa_docx() -> tuple[bool, str]:
        docx_path = Path(config["paths"]["output_draft_dir"]) / "tesina-draft.docx"
        return True, str(qa_docx(config, docx_path, strict=strict))

    prep: list[tuple[str, Any, bool]] = [
        ("doctor", stage_doctor, True),
        ("build-rules", stage_build_rules, False),
        ("review-rules", stage_review_rules, True),
        ("collect-sources", stage_collect_sources, False),
        ("collect-code-evidence", stage_collect_code_evidence, False),
        ("collect-issues", stage_collect_issues, False),
        ("build-ledger", stage_build_ledger, False),
        ("build-sections", stage_build_sections, False),
        ("pack-context", stage_pack_context, False),
    ]
    assemble: list[tuple[str, Any, bool]] = [
        ("build-docx", stage_build_docx, True),
        ("format-audit-docx", stage_format_audit, True),
        ("qa-docx", stage_qa_docx, True),
    ]
    if stage_set == "prep":
        return prep
    if stage_set == "assemble":
        return assemble
    if stage_set == "all":
        return prep + [("review-document", stage_review_document, True)] + assemble
    raise ValueError(f"Conjunto de etapas desconocido: {stage_set}. Usa prep, assemble o all.")
```

### `run_pipeline` (lines 3281–3304)

```python
def run_pipeline(
    config: dict[str, Any],
    stage_set: str,
    strict: bool = False,
    stages: list[tuple[str, Any, bool]] | None = None,
) -> dict[str, Any]:
    stages = stages if stages is not None else _pipeline_stages(config, stage_set, strict)
    results: list[dict[str, Any]] = []
    passed = True
    for name, callable_, fail_fast in stages:
        started = datetime.now()
        try:
            ok, detail = callable_()
        except Exception as exc:
            ok, detail = False, f"ERROR: {exc}"
        duration = (datetime.now() - started).total_seconds()
        results.append({"stage": name, "ok": ok, "duration_s": round(duration, 3), "detail": detail})
        if not ok:
            passed = False
            if fail_fast:
                break
    summary = {"stage_set": stage_set, "strict": strict, "passed": passed, "stages": results}
    log_run(f"pipeline-{stage_set}", summary, config=config)
    return summary
```

### `verify_all` (lines 3307–3321)

```python
def verify_all(config: dict[str, Any], docx_path: Path | None = None, strict: bool = True) -> ReviewResult:
    """Definition-of-done: agrega los gates de revisión en un único pass/fail."""
    issues: list[Issue] = []
    issues.extend(review_rules(config, strict=strict).issues)
    issues.extend(review_document(config, strict=strict).issues)
    if docx_path is None:
        candidate = Path(config["paths"]["output_draft_dir"]) / "tesina-draft.docx"
        docx_path = candidate if candidate.exists() else None
    if docx_path and docx_path.exists():
        issues.extend(format_audit_docx(docx_path, strict=strict, config=config).issues)
        try:
            qa_docx(config, docx_path, strict=strict)
        except Exception as exc:
            issues.append(Issue("error", f"QA visual falló: {exc}", code="qa.failed"))
    return ReviewResult(issues)
```

### `list_runs` (lines 3342–3352)

```python
def list_runs(limit: int = 20, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    runs_dir = _runs_dir(config)
    if not runs_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records
```

### Referenced legacy fragments (context only, needed to justify Judgment
call 1 — not re-ported verbatim as standalone functions, absorbed into
`resolve_normative_settings`)

```python
# review_section, lines 1455–1458, 1473, 1477–1478
normative = (config or {}).get("normative", {})
excluded = normative.get("excluded_front_matter", EXCLUDED_FRONT_MATTER)
first_person = normative.get("first_person_patterns", FIRST_PERSON_PATTERNS)
subjective = normative.get("subjective_terms", SUBJECTIVE_TERMS)
...
for pattern in SECRET_PATTERNS + list((config or {}).get("privacy", {}).get("forbidden_in_body_patterns", [])):
    ...
scope_term = normative.get("scope_term")
scope_focus = normative.get("scope_focus")
```

```python
# module constants, lines 68–110
EXCLUDED_FRONT_MATTER = {
    "portada": "La portada se toma desde la plantilla DOCX, no se redacta como sección.",
    "hoja de guarda": "La hoja de guarda está excluida del arnés.",
    "carta responsiva": "La carta responsiva está excluida del arnés.",
    "carta de liberación": "Las cartas de liberación están excluidas del arnés.",
    "carta de liberacion": "Las cartas de liberación están excluidas del arnés.",
}

FIRST_PERSON_PATTERNS = [
    r"\byo\b", r"\bnosotros\b", r"\bnosotras\b", r"\bmi\b", r"\bmis\b",
    r"\bnuestro\b", r"\bnuestra\b", r"\bdesarrollé\b", r"\bdesarrollamos\b",
    r"\bconsidero\b", r"\bcreemos\b",
]

SUBJECTIVE_TERMS = [
    "excelente", "impresionante", "increíble", "increible", "claramente",
    "obviamente", "afortunadamente", "lamentablemente", "simplemente",
    "éxito", "exito", "fracaso",
]

SECRET_PATTERNS = [
    r"\bapi[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bsecret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bpassword\s*[:=]\s*['\"]?[^'\"\s]{8,}",
    r"\btoken\s*[:=]\s*['\"]?[A-Za-z0-9_\-.]{24,}",
]
```

```python
# render_fact_ledger step 2, lines 1243–1257 (context provided for
# resolve_normative_settings's SIBLING helper, _context_confirmed_lines,
# on PipelineService — NOT part of resolve_normative_settings itself)
for topic in context_schema(config):
    values = read_topic(config, topic)
    if isinstance(values, dict):
        for field in topic.get("fields", []):
            value = values.get(field["key"], "")
            if not value:
                continue
            if field.get("sensitive"):
                grouped["dato_sensible"].append(f"{field['label']} (dato sensible; excluido del cuerpo).")
            else:
                grouped["confirmado"].append(f"{field['label']}: {value}")
    elif isinstance(values, str) and values.strip():
        snippet = values.strip()[:160]
        grouped["confirmado"].append(f"{topic.get('title', topic['id'])}: {snippet}")
```

## Already satisfied — not re-ported here

- `run_doctor` → `DoctorService.run_doctor(doc_id, config, strict)` (Slice 13).
- `build_rules` → `EvidenceService.build_rules(config)` (Slice 4).
- `review_rules(config, strict)` → `docs.domain.rules.review_rules(template,
  manifest_exists, manifest_size, strict)` (Slice 3), called directly from
  `PipelineService` after building `manifest_exists`/`manifest_size` the
  same way `DoctorService.run_doctor` already does internally (not shared
  code — a 3-line lookup duplicated once, see "Risks" item 3).
- `collect_sources`/`collect_issues`/`collect_code_evidence` →
  `CollectionService` (Slice 7).
- `render_fact_ledger`/`load_manifest_facts` →
  `EvidenceService.render_fact_ledger`/`load_manifest_facts` (Slice 8).
- `pack_context`/`pack_context_document` → `ContextPackService` (Slice 9).
- `review_document` → `ReviewService.review_document` (Slice 5, extended
  Slice 3).
- `build_docx` → `DocxAssemblyService.build(doc_id, config)` (Slices
  11a/11b).
- `format_audit_docx` → `FormatAuditService.audit_format(docx_path, config,
  strict)` (Slice 10).
- `qa_docx` → `QaService.qa_docx(config, docx_path, strict)` (Slice 12).
- `Issue`/`ReviewResult` → `docs.domain.review` (Slice 3).
- `run_git_log`/`detect_github_remote` → `SourceRepository` (Slice 7);
  `run_git_rev_parse_head` (this slice) is the third method on that same
  port, not a new one.

### Out of scope (confirmed, not re-derived)

- `build-sections`'s actual scaffold-rendering capability (`render_section_draft`
  from context, `source_hash`, `prompt_hash`) — remains deferred per Slice
  6/8's own established scope carve-out; this slice only wires the stage
  slot and documents why it currently fails (Judgment call 3).
- `stamp_section` — already shipped (Slice 6), not part of this range.
- Any CLI surface (`command_doctor`, `command_*`, `argparse`) — Slice 15.
  `PipelineService.run_pipeline`/`verify_all`/`log_run`/`list_runs` are
  library methods; wiring them to `run`/`verify`/`list-runs` CLI commands
  is explicitly Slice 15's job.

## Task breakdown

### Task 1 — Pure domain additions (`domain/pipeline.py`, `domain/normative.py`)

**Files to create/modify:**
- Create `src/docs/domain/pipeline.py`.
- Create `src/docs/domain/normative.py`.
- Create `tests/unit/domain/test_pipeline.py`.
- Create `tests/unit/domain/test_normative.py`.

**Verbatim legacy reference:** the stage-name/fail-fast structure inside
`_pipeline_stages` (3256–3278), ported as pure data (the callables
themselves are impure and land on `PipelineService` in Task 5). The four
module constants (68–110) and the `normative`/`SECRET_PATTERNS` extraction
fragment (1455–1458, 1473, 1477–1478), ported as `resolve_normative_settings`
— new pure groundwork per Judgment call 1, not a re-port of an existing
named legacy function.

**Planned implementation:**

```python
# src/docs/domain/pipeline.py
from __future__ import annotations

_PREP_STAGES: list[tuple[str, bool]] = [
    ("doctor", True),
    ("build-rules", False),
    ("review-rules", True),
    ("collect-sources", False),
    ("collect-code-evidence", False),
    ("collect-issues", False),
    ("build-ledger", False),
    ("build-sections", False),
    ("pack-context", False),
]

_ASSEMBLE_STAGES: list[tuple[str, bool]] = [
    ("build-docx", True),
    ("format-audit-docx", True),
    ("qa-docx", True),
]


def pipeline_stage_plan(stage_set: str) -> list[tuple[str, bool]]:
    """Devuelve (nombre, fail_fast) en orden de dependencias para el stage_set dado."""
    if stage_set == "prep":
        return list(_PREP_STAGES)
    if stage_set == "assemble":
        return list(_ASSEMBLE_STAGES)
    if stage_set == "all":
        return list(_PREP_STAGES) + [("review-document", True)] + list(_ASSEMBLE_STAGES)
    raise ValueError(f"Conjunto de etapas desconocido: {stage_set}. Usa prep, assemble o all.")
```

```python
# src/docs/domain/normative.py
from __future__ import annotations

from typing import Any

EXCLUDED_FRONT_MATTER: dict[str, str] = {
    "portada": "La portada se toma desde la plantilla DOCX, no se redacta como sección.",
    "hoja de guarda": "La hoja de guarda está excluida del arnés.",
    "carta responsiva": "La carta responsiva está excluida del arnés.",
    "carta de liberación": "Las cartas de liberación están excluidas del arnés.",
    "carta de liberacion": "Las cartas de liberación están excluidas del arnés.",
}

FIRST_PERSON_PATTERNS: list[str] = [
    r"\byo\b",
    r"\bnosotros\b",
    r"\bnosotras\b",
    r"\bmi\b",
    r"\bmis\b",
    r"\bnuestro\b",
    r"\bnuestra\b",
    r"\bdesarrollé\b",
    r"\bdesarrollamos\b",
    r"\bconsidero\b",
    r"\bcreemos\b",
]

SUBJECTIVE_TERMS: list[str] = [
    "excelente",
    "impresionante",
    "increíble",
    "increible",
    "claramente",
    "obviamente",
    "afortunadamente",
    "lamentablemente",
    "simplemente",
    "éxito",
    "exito",
    "fracaso",
]

SECRET_PATTERNS: list[str] = [
    r"\bapi[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bsecret\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}",
    r"\bpassword\s*[:=]\s*['\"]?[^'\"\s]{8,}",
    r"\btoken\s*[:=]\s*['\"]?[A-Za-z0-9_\-.]{24,}",
]


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

**Planned test code:**

```python
# tests/unit/domain/test_pipeline.py
from __future__ import annotations

import pytest

from docs.domain.pipeline import pipeline_stage_plan


def test_pipeline_stage_plan_prep_has_nine_stages_in_order():
    stages = pipeline_stage_plan("prep")
    assert [name for name, _ in stages] == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "pack-context",
    ]


def test_pipeline_stage_plan_prep_fail_fast_flags_match_legacy():
    stages = dict(pipeline_stage_plan("prep"))
    assert stages["doctor"] is True
    assert stages["review-rules"] is True
    assert stages["build-rules"] is False
    assert stages["build-sections"] is False


def test_pipeline_stage_plan_assemble_has_three_fail_fast_stages():
    stages = pipeline_stage_plan("assemble")
    assert [name for name, _ in stages] == ["build-docx", "format-audit-docx", "qa-docx"]
    assert all(fail_fast for _, fail_fast in stages)


def test_pipeline_stage_plan_all_is_prep_plus_review_document_plus_assemble():
    stages = pipeline_stage_plan("all")
    names = [name for name, _ in stages]
    assert names == [
        "doctor", "build-rules", "review-rules", "collect-sources",
        "collect-code-evidence", "collect-issues", "build-ledger",
        "build-sections", "pack-context", "review-document",
        "build-docx", "format-audit-docx", "qa-docx",
    ]
    assert dict(stages)["review-document"] is True


def test_pipeline_stage_plan_unknown_stage_set_raises_value_error():
    with pytest.raises(ValueError, match="Conjunto de etapas desconocido: bogus. Usa prep, assemble o all."):
        pipeline_stage_plan("bogus")
```

```python
# tests/unit/domain/test_normative.py
from __future__ import annotations

from docs.domain.normative import (
    EXCLUDED_FRONT_MATTER,
    FIRST_PERSON_PATTERNS,
    SECRET_PATTERNS,
    SUBJECTIVE_TERMS,
    resolve_normative_settings,
)


def test_resolve_normative_settings_uses_defaults_when_config_is_empty():
    settings = resolve_normative_settings({})
    assert settings["excluded_terms"] == EXCLUDED_FRONT_MATTER
    assert settings["first_person_patterns"] == FIRST_PERSON_PATTERNS
    assert settings["subjective_terms"] == SUBJECTIVE_TERMS
    assert settings["secret_patterns"] == SECRET_PATTERNS
    assert settings["is_policy_file"] is False
    assert settings["scope_term"] == ""
    assert settings["scope_focus"] == ""


def test_resolve_normative_settings_overrides_from_config():
    config = {
        "normative": {
            "excluded_front_matter": {"anexo": "fuera de alcance"},
            "first_person_patterns": [r"\byo\b"],
            "subjective_terms": ["genial"],
            "scope_term": "ecosistema",
            "scope_focus": "app móvil",
        }
    }
    settings = resolve_normative_settings(config)
    assert settings["excluded_terms"] == {"anexo": "fuera de alcance"}
    assert settings["first_person_patterns"] == [r"\byo\b"]
    assert settings["subjective_terms"] == ["genial"]
    assert settings["scope_term"] == "ecosistema"
    assert settings["scope_focus"] == "app móvil"


def test_resolve_normative_settings_converts_list_excluded_front_matter_to_dict():
    config = {"normative": {"excluded_front_matter": ["portada", "anexo"]}}
    settings = resolve_normative_settings(config)
    assert settings["excluded_terms"] == {"portada": "", "anexo": ""}


def test_resolve_normative_settings_appends_privacy_forbidden_patterns_to_secret_patterns():
    config = {"privacy": {"forbidden_in_body_patterns": [r"\bdni\s*[:=]\s*\d{7,8}"]}}
    settings = resolve_normative_settings(config)
    assert settings["secret_patterns"] == SECRET_PATTERNS + [r"\bdni\s*[:=]\s*\d{7,8}"]
```

**Expected test count:** ~9 unit tests (5 + 4). Self-reviewable — pure
functions/data, no I/O.

---

### Task 2 — `SourceRepository` Protocol extension

**Files to create/modify:**
- Modify `src/docs/domain/ports/source_repository.py`: add
  `run_git_rev_parse_head`.

**Verbatim legacy reference:** none new — the *command* is legacy's
`_git_commit` (3159–3171), but as a Protocol method it's new surface on an
existing port (Judgment call 8). No behavior to test (bare-Protocol
precedent, every prior slice's port-growth task).

**Planned implementation:**

```python
# src/docs/domain/ports/source_repository.py (addition — existing methods untouched)
    def run_git_rev_parse_head(self, repo_root: Path) -> str: ...
```

**Expected test count:** 0 new tests by design. Self-reviewable — diff
against this plan's code block should be byte-for-byte, existing 7 methods
untouched.

---

### Task 3 — `FilesystemSourceRepository.run_git_rev_parse_head`

**Files to create/modify:**
- Modify `src/docs/infrastructure/persistence/filesystem_source_repository.py`:
  implement `run_git_rev_parse_head`.
- Modify `tests/unit/infrastructure/test_filesystem_source_repository.py`:
  add tests for the new method.

**Verbatim legacy reference:** `_git_commit` (3159–3171), verbatim except
`REPO_ROOT` becomes the caller-supplied `repo_root: Path` parameter
(Slice 7 Design Decision 4, reapplied) and the bare
`except Exception: return ""` shape is copied from this same file's
existing `detect_github_remote`, not `run_git_log` (which returns `None`
on failure) — `_git_commit` itself returns `""` on failure in legacy, so
`detect_github_remote`'s shape is the correct one to mirror.

**Planned implementation:**

```python
# src/docs/infrastructure/persistence/filesystem_source_repository.py (addition)
    def run_git_rev_parse_head(self, repo_root: Path) -> str:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception:
            return ""
        return proc.stdout.strip()
```

**Planned test code:**

```python
# tests/unit/infrastructure/test_filesystem_source_repository.py (additions)

def test_run_git_rev_parse_head_returns_stripped_stdout(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc1234\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_rev_parse_head(tmp_path) == "abc1234"


def test_run_git_rev_parse_head_returns_empty_string_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_rev_parse_head(tmp_path) == ""
```

**Expected test count:** ~2 unit tests. Self-reviewable — mirrors
`detect_github_remote`'s already-reviewed test pair exactly.

---

### Task 4 — `PipelineService.log_run` / `list_runs`

**Files to create/modify:**
- Create `src/docs/application/pipeline.py` (this task adds only
  `log_run`/`list_runs`/`_runs_dir`; `run_pipeline`/`verify_all` land in
  Tasks 5–6 on the same class).
- Create `tests/integration/test_pipeline_service.py` (this task's tests;
  Tasks 5–6 extend the same file).

**Verbatim legacy reference:** `_runs_dir`/`log_run` (3159–3196) except:
(a) the default directory is `workspace.doc_root(doc_id)/"runs"` instead of
a global `RUNS_DIR` constant (Judgment call 6), still overridden by
`config["paths"]["runs_dir"]` when present, matching legacy's precedence
exactly; (b) `git_commit` is resolved via
`self.source_repository.run_git_rev_parse_head(repo_root)` instead of an
inline `subprocess.run` call (Judgment call 8) — `PipelineService` never
imports `subprocess` directly. `list_runs` (3342–3352) is verbatim, only
`_runs_dir`'s resolution changes.

**Planned implementation:**

```python
# src/docs/application/pipeline.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docs.application.collection import CollectionService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.ports.context_repository import ContextRepository
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository
from docs.domain.workspace import Workspace

_DRAFT_DOCX_NAME = "tesina-draft.docx"


class PipelineService:
    def __init__(
        self,
        doctor_service: DoctorService,
        evidence_service: EvidenceService,
        evidence_repository: EvidenceRepository,
        collection_service: CollectionService,
        source_repository: SourceRepository,
        review_service: ReviewService,
        context_pack_service: ContextPackService,
        context_repository: ContextRepository,
        docx_assembly_service: DocxAssemblyService,
        format_audit_service: FormatAuditService,
        qa_service: QaService,
        workspace: Workspace,
    ) -> None:
        self.doctor_service = doctor_service
        self.evidence_service = evidence_service
        self.evidence_repository = evidence_repository
        self.collection_service = collection_service
        self.source_repository = source_repository
        self.review_service = review_service
        self.context_pack_service = context_pack_service
        self.context_repository = context_repository
        self.docx_assembly_service = docx_assembly_service
        self.format_audit_service = format_audit_service
        self.qa_service = qa_service
        self.workspace = workspace

    def log_run(
        self, doc_id: str, config: dict[str, Any], repo_root: Path, command: str, payload: dict[str, Any]
    ) -> Path:
        runs_dir = self._runs_dir(doc_id, config)
        runs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        record = {
            "timestamp": timestamp,
            "command": command,
            "git_commit": self.source_repository.run_git_rev_parse_head(repo_root),
            **payload,
        }
        safe_name = timestamp.replace(":", "-")
        path = runs_dir / f"{safe_name}-{command}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def list_runs(self, doc_id: str, config: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        runs_dir = self._runs_dir(doc_id, config)
        if not runs_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(runs_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
        return records

    def _runs_dir(self, doc_id: str, config: dict[str, Any]) -> Path:
        configured = config.get("paths", {}).get("runs_dir")
        if configured:
            return Path(configured)
        return self.workspace.doc_root(doc_id) / "runs"
```

**Planned test code:**

```python
# tests/integration/test_pipeline_service.py
from __future__ import annotations

import json
from pathlib import Path

from docs.application.collection import CollectionService
from docs.application.context_pack import ContextPackService
from docs.application.doctor import DoctorService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository
from docs.application.asset import AssetService


def _service(tmp_path) -> tuple[PipelineService, Workspace]:
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    evidence_repo = JsonEvidenceRepository()
    section_repo = JsonSectionRepository(workspace)
    source_repo = FilesystemSourceRepository()
    context_repo = JsonContextRepository(workspace)
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    evidence_service = EvidenceService(evidence_repo)
    review_service = ReviewService(section_repo)
    collection_service = CollectionService(source_repo, evidence_repo)
    context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
    docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
    qa_service = QaService(LibreOfficeQaAdapter(), format_audit_service)
    doctor_service = DoctorService(evidence_repo, asset_service)
    service = PipelineService(
        doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
        review_service, context_pack_service, context_repo, docx_assembly_service,
        format_audit_service, qa_service, workspace,
    )
    return service, workspace


def test_log_run_writes_a_json_record_under_the_document_runs_dir(tmp_path):
    service, workspace = _service(tmp_path)
    config = {"paths": {}}
    path = service.log_run("doc1", config, tmp_path, "pipeline-prep", {"passed": True, "stages": []})
    assert path.parent == workspace.doc_root("doc1") / "runs"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["command"] == "pipeline-prep"
    assert record["passed"] is True
    assert "timestamp" in record
    assert "git_commit" in record


def test_log_run_honors_configured_runs_dir_override(tmp_path):
    service, _ = _service(tmp_path)
    override_dir = tmp_path / "custom-runs"
    config = {"paths": {"runs_dir": str(override_dir)}}
    path = service.log_run("doc1", config, tmp_path, "pipeline-prep", {"passed": True})
    assert path.parent == override_dir


def test_list_runs_returns_empty_list_when_runs_dir_missing(tmp_path):
    service, _ = _service(tmp_path)
    assert service.list_runs("doc1", {"paths": {}}) == []


def test_list_runs_returns_records_most_recent_first(tmp_path):
    service, _ = _service(tmp_path)
    config = {"paths": {}}
    service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": 1})
    service.log_run("doc1", config, tmp_path, "pipeline-assemble", {"n": 2})
    records = service.list_runs("doc1", config)
    assert [r["n"] for r in records] == [2, 1]


def test_list_runs_respects_limit(tmp_path):
    service, _ = _service(tmp_path)
    config = {"paths": {}}
    for i in range(3):
        service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": i})
    assert len(service.list_runs("doc1", config, limit=2)) == 2


def test_list_runs_skips_malformed_json_files(tmp_path):
    service, workspace = _service(tmp_path)
    config = {"paths": {}}
    service.log_run("doc1", config, tmp_path, "pipeline-prep", {"n": 1})
    (workspace.doc_root("doc1") / "runs" / "broken.json").write_text("not json", encoding="utf-8")
    records = service.list_runs("doc1", config)
    assert len(records) == 1
```

**Expected test count:** ~6 integration tests, real adapters (no mocks) —
`git_commit`'s actual value isn't asserted beyond "key present" since this
repo's own git state shouldn't leak into a fixed test expectation. Needs
implementer + fresh-context reviewer for the `_runs_dir` precedence logic.

---

### Task 5 — `PipelineService.run_pipeline`

**Files to create/modify:**
- Modify `src/docs/application/pipeline.py`: add `_rules_manifest_state`,
  `_context_confirmed_lines`, `_stage_callables`, `run_pipeline`.
- Modify `tests/integration/test_pipeline_service.py`: add tests for this
  task.

**Verbatim legacy reference:** `_pipeline_stages` (3199–3278) and
`run_pipeline` (3281–3304), verbatim except: (a) every stage closure now
calls the migrated service methods listed in "Already satisfied" instead
of legacy module-level functions; (b) `stage_review_rules`/
`stage_pack_context`/`stage_review_document` additionally build
`manifest_exists`/`manifest_size` (via `_rules_manifest_state`) and/or
normative kwargs (via `resolve_normative_settings`) since the migrated
functions they call need pre-extracted values legacy computed internally;
(c) `stage_build_ledger` builds `context_confirmed_lines` via
`_context_confirmed_lines` instead of passing `load_context(config)`
through (Judgment call 4 — legacy's own `render_fact_ledger` body actually
**ignores** its `context` parameter entirely, confirmed by direct read of
lines 1225–1264: the real per-topic reading happens via
`context_schema(config)`/`read_topic(config, topic)`, not the passed-in
`context` dict — so this is not a behavior change to a load-bearing
parameter, it's replacing a dead parameter with the pre-computed
equivalent the migrated function actually needs); (d) `stage_build_sections`
raises `NotImplementedError` (Judgment call 3) instead of calling
`build_section` per section; (e) `run_pipeline` requires `repo_root: Path`
(Judgment call 5) and dispatches stage names to bound closures via a
`dict[str, Callable]` (`_stage_callables`) rather than legacy's inline
`stages: list[tuple[str, Any, bool]] | None` override parameter — the
override-list capability is dropped since nothing in this migration calls
`run_pipeline` with a custom `stages` list yet (CLI, Slice 15, can add it
back trivially if needed by accepting an optional stage-name subset).

**Planned implementation:**

```python
# src/docs/application/pipeline.py (additions)
from typing import Callable

from docs.domain.models.template import Template
from docs.domain.normative import resolve_normative_settings
from docs.domain.pipeline import pipeline_stage_plan
from docs.domain.rules import review_rules

# ... (inside PipelineService, added after __init__/log_run/list_runs/_runs_dir)

    def _rules_manifest_state(self, config: dict[str, Any]) -> tuple[bool, int]:
        rules_path = Path(config["paths"]["rules_manifest"])
        exists = self.evidence_repository.file_exists(rules_path)
        size = self.evidence_repository.file_size(rules_path) if exists else 0
        return exists, size

    def _context_confirmed_lines(self, doc_id: str, template: Template) -> list[str]:
        # Legacy also routes sensitive topic fields into a separate
        # "dato_sensible" ledger bucket. EvidenceService.render_fact_ledger
        # (Slice 8) only accepts one confirmado-scoped list, so sensitive
        # fields are skipped here rather than mis-classified. See plan's
        # "Risks and open judgment calls".
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

    def _stage_callables(
        self, doc_id: str, template: Template, config: dict[str, Any], repo_root: Path, strict: bool
    ) -> dict[str, Callable[[], tuple[bool, str]]]:
        def stage_doctor() -> tuple[bool, str]:
            result = self.doctor_service.run_doctor(doc_id, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_build_rules() -> tuple[bool, str]:
            return True, str(self.evidence_service.build_rules(config))

        def stage_review_rules() -> tuple[bool, str]:
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            result = review_rules(template, manifest_exists, manifest_size, strict=strict)
            return result.passed, result.to_markdown()

        def stage_collect_sources() -> tuple[bool, str]:
            return True, str(self.collection_service.collect_sources(config))

        def stage_collect_code_evidence() -> tuple[bool, str]:
            return True, str(self.collection_service.collect_code_evidence(config, repo_root))

        def stage_collect_issues() -> tuple[bool, str]:
            try:
                return True, str(self.collection_service.collect_issues(config, repo_root))
            except Exception as exc:  # best-effort: gh puede no estar disponible
                return True, f"omitido: {exc}"

        def stage_build_ledger() -> tuple[bool, str]:
            path = Path(config["paths"]["fact_ledger"])
            path.parent.mkdir(parents=True, exist_ok=True)
            context_lines = self._context_confirmed_lines(doc_id, template)
            path.write_text(self.evidence_service.render_fact_ledger(config, context_lines), encoding="utf-8")
            return True, str(path)

        def stage_build_sections() -> tuple[bool, str]:
            raise NotImplementedError(
                "build-section requiere un renderer de borradores y source_hash/"
                "prompt_hash aún no modelados en esta migración (ver Slice 6 y "
                "Slice 8, Design Decision 4)."
            )

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

        def stage_review_document() -> tuple[bool, str]:
            normative = resolve_normative_settings(config)
            manifest_exists, manifest_size = self._rules_manifest_state(config)
            result = self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            )
            return result.passed, result.to_markdown()

        def stage_build_docx() -> tuple[bool, str]:
            return True, str(self.docx_assembly_service.build(doc_id, config))

        def stage_format_audit() -> tuple[bool, str]:
            docx_path = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            result = self.format_audit_service.audit_format(docx_path, config, strict=strict)
            return result.passed, result.to_markdown()

        def stage_qa_docx() -> tuple[bool, str]:
            docx_path = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            return True, str(self.qa_service.qa_docx(config, docx_path, strict=strict))

        return {
            "doctor": stage_doctor,
            "build-rules": stage_build_rules,
            "review-rules": stage_review_rules,
            "collect-sources": stage_collect_sources,
            "collect-code-evidence": stage_collect_code_evidence,
            "collect-issues": stage_collect_issues,
            "build-ledger": stage_build_ledger,
            "build-sections": stage_build_sections,
            "pack-context": stage_pack_context,
            "review-document": stage_review_document,
            "build-docx": stage_build_docx,
            "format-audit-docx": stage_format_audit,
            "qa-docx": stage_qa_docx,
        }

    def run_pipeline(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        stage_set: str,
        repo_root: Path,
        strict: bool = False,
    ) -> dict[str, Any]:
        stages = pipeline_stage_plan(stage_set)
        callables = self._stage_callables(doc_id, template, config, repo_root, strict)
        results: list[dict[str, Any]] = []
        passed = True
        for name, fail_fast in stages:
            started = datetime.now()
            try:
                ok, detail = callables[name]()
            except Exception as exc:
                ok, detail = False, f"ERROR: {exc}"
            duration = (datetime.now() - started).total_seconds()
            results.append({"stage": name, "ok": ok, "duration_s": round(duration, 3), "detail": detail})
            if not ok:
                passed = False
                if fail_fast:
                    break
        summary = {"stage_set": stage_set, "strict": strict, "passed": passed, "stages": results}
        self.log_run(doc_id, config, repo_root, f"pipeline-{stage_set}", summary)
        return summary
```

**Planned test code:**

```python
# tests/integration/test_pipeline_service.py (additions — reuse _service
# from Task 4, plus a minimal Template/config fixture)
from docs.domain.models.template import Section, SectionContract, Template


def _template() -> Template:
    return Template(
        type="tesina",
        title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=False)],
        section_contracts={"introduccion": SectionContract()},
    )


def _pipeline_config(tmp_path: Path) -> dict:
    return {
        "paths": {
            "rules_manifest": str(tmp_path / "manual-rules.json"),
            "context_dir": str(tmp_path / "context"),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
        },
        "sections": [{"id": "introduccion", "order": 1}],
        "evidence_sources": {},
        "privacy": {},
        "project": {},
    }


def test_run_pipeline_prep_reports_build_sections_as_a_failed_stage(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)  # gh unavailable -> collect-issues "omitido"
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage = next(s for s in summary["stages"] if s["stage"] == "build-sections")
    assert stage["ok"] is False
    assert "NotImplementedError" not in stage["detail"]  # detail is the exception message, not its type
    assert "build-section requiere" in stage["detail"]


def test_run_pipeline_prep_does_not_fail_fast_after_build_sections(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    summary = service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    stage_names = [s["stage"] for s in summary["stages"]]
    assert "pack-context" in stage_names  # ran despite build-sections failing (fail_fast=False)


def test_run_pipeline_stops_at_first_fail_fast_failure(tmp_path):
    service, _ = _service(tmp_path)
    config = _pipeline_config(tmp_path)
    del config["paths"]["context_dir"]  # doctor's context_dir check will raise a KeyError -> ERROR, fail_fast=True
    summary = service.run_pipeline("doc1", _template(), config, "prep", repo_root=tmp_path)
    assert summary["passed"] is False
    assert summary["stages"][0]["stage"] == "doctor"
    assert len(summary["stages"]) == 1


def test_run_pipeline_writes_a_run_log_entry(tmp_path, monkeypatch):
    Path(tmp_path / "context").mkdir()
    service, workspace = _service(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "prep", repo_root=tmp_path)
    runs = service.list_runs("doc1", _pipeline_config(tmp_path))
    assert any(r["command"] == "pipeline-prep" for r in runs)


def test_run_pipeline_unknown_stage_set_raises_value_error(tmp_path):
    service, _ = _service(tmp_path)
    with pytest.raises(ValueError, match="Conjunto de etapas desconocido"):
        service.run_pipeline("doc1", _template(), _pipeline_config(tmp_path), "bogus", repo_root=tmp_path)
```

**Expected test count:** ~5 integration tests, real adapters. **Highest-risk
task in this slice** — needs implementer + fresh-context reviewer. The
reviewer should specifically verify: (a) `stage_build_sections` genuinely
reaches `run_pipeline`'s exception handler and doesn't crash the whole
`run_pipeline` call; (b) fail_fast stages actually stop the loop (test 3
above); (c) `_rules_manifest_state`/`resolve_normative_settings` are called
with the SAME `config` each stage receives (no stale closure capture bugs
— every closure reads from the same outer `config`/`template`/`doc_id`/
`repo_root`/`strict` parameters, none of which are mutated mid-loop); (d)
`log_run` is called exactly once per `run_pipeline` call, after the loop,
not per-stage.

---

### Task 6 — `PipelineService.verify_all`

**Files to create/modify:**
- Modify `src/docs/application/pipeline.py`: add `verify_all`.
- Modify `tests/integration/test_pipeline_service.py`: add tests for this
  task.

**Verbatim legacy reference:** `verify_all` (3307–3321), verbatim except
the same service-call substitutions as Task 5's stages, reusing
`_rules_manifest_state`/`resolve_normative_settings` (Task 5) rather than
re-deriving them. Confirmed by re-reading legacy: `verify_all` does not
call `collect_issues`/`collect_code_evidence`/`log_run`, so it takes no
`repo_root` parameter (unlike `run_pipeline`).

**Planned implementation:**

```python
# src/docs/application/pipeline.py (addition)
from docs.domain.review import Issue, ReviewResult

# ... (inside PipelineService)

    def verify_all(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        docx_path: Path | None = None,
        strict: bool = True,
    ) -> ReviewResult:
        issues: list[Issue] = []
        manifest_exists, manifest_size = self._rules_manifest_state(config)
        issues.extend(review_rules(template, manifest_exists, manifest_size, strict=strict).issues)
        normative = resolve_normative_settings(config)
        issues.extend(
            self.review_service.review_document(
                doc_id, template, strict=strict,
                manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
            ).issues
        )
        if docx_path is None:
            candidate = Path(config["paths"]["output_draft_dir"]) / _DRAFT_DOCX_NAME
            docx_path = candidate if candidate.exists() else None
        if docx_path and docx_path.exists():
            issues.extend(self.format_audit_service.audit_format(docx_path, config, strict=strict).issues)
            try:
                self.qa_service.qa_docx(config, docx_path, strict=strict)
            except Exception as exc:
                issues.append(Issue("error", f"QA visual falló: {exc}", code="qa.failed"))
        return ReviewResult(issues)
```

**Planned test code:**

```python
# tests/integration/test_pipeline_service.py (additions)

def test_verify_all_includes_review_rules_and_review_document_issues(tmp_path):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    config = _pipeline_config(tmp_path)
    config["paths"]["output_draft_dir"] = str(tmp_path / "draft")  # no docx present -> docx-dependent checks skipped
    result = service.verify_all("doc1", _template(), config, strict=True)
    assert not result.passed  # missing rules_manifest -> review_rules error under strict


def test_verify_all_skips_docx_checks_when_no_draft_exists(tmp_path):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    config = _pipeline_config(tmp_path)
    config["paths"]["output_draft_dir"] = str(tmp_path / "draft")
    result = service.verify_all("doc1", _template(), config, strict=False)
    assert not any(issue.code == "qa.failed" for issue in result.issues)


def test_verify_all_appends_qa_failed_issue_when_qa_docx_raises(tmp_path):
    Path(tmp_path / "context").mkdir()
    service, _ = _service(tmp_path)
    config = _pipeline_config(tmp_path)
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir()
    config["paths"]["output_draft_dir"] = str(draft_dir)
    docx_path = draft_dir / "tesina-draft.docx"
    from docx import Document
    Document().save(docx_path)
    result = service.verify_all("doc1", _template(), config, strict=False)
    assert any(issue.code == "qa.failed" for issue in result.issues) or result.issues  # LibreOffice-dependent; see note below
```

Note on the third test: whether `qa_docx` succeeds or raises depends on
LibreOffice being installed in the execution environment (Slice 12's own
convention). The implementer should split this into two `skipif`-guarded
variants — one asserting `qa.failed` appears when LibreOffice is
unavailable (monkeypatching `LibreOfficeQaAdapter.render_docx_to_pdf` to
raise, deterministic without needing the real binary), one asserting a
successful QA path when it is (`skipif(not _HAS_LIBREOFFICE)`), mirroring
`test_qa_service.py`'s existing dual-path convention exactly, rather than
the single loosely-asserting test sketched above.

**Expected test count:** ~3 integration tests (plus the LibreOffice split
noted above, ~4-5 in practice). Needs implementer + fresh-context reviewer
— confirm `verify_all` reuses Task 5's helpers rather than duplicating
them, and that the docx-path resolution/existence-guard sequencing matches
legacy exactly (candidate resolved before the `if docx_path and
docx_path.exists()` guard, not after).

## Global constraints

- Config stays a plain `dict[str, Any]` everywhere except the
  `Template`/`SectionContract` objects `PipelineService`'s callers already
  construct (same convention every prior slice follows — `PipelineService`
  itself never calls `Template.model_validate`; that stays inside
  `DoctorService`, which is called as a black box).
- `domain/pipeline.py` and `domain/normative.py` import nothing from
  application/infrastructure/cli; `domain/pipeline.py` imports nothing at
  all beyond stdlib typing; `domain/normative.py` imports only `typing`.
- `SourceRepository` stays a bare `Protocol` — no default method bodies.
- `application/pipeline.py` never imports `subprocess` directly — the one
  external-tool call this slice needs (`git rev-parse`) goes through
  `SourceRepository.run_git_rev_parse_head` (Task 3), consistent with
  every prior slice's "only ports do subprocess" boundary.
- No new third-party pip dependency.
- `PipelineService`'s constructor takes 12 dependencies (11 collaborators +
  `Workspace`). This is expected, not a design smell to fix in this slice
  — the roadmap explicitly frames Slice 14 as "orchestrates everything
  above," and every one of those 12 is a real, distinct collaborator with
  no natural sub-grouping that wouldn't just relocate the same fan-out
  into an intermediate wrapper with no other purpose.
- Every task is TDD: failing test first, minimal implementation, full
  suite run (`rtk pytest -q`) after each task, commit per task.
- Every test must be a real assertion against real behavior — no
  placeholder tests.
- `RUNS_DIR`/`REPO_ROOT`/`CODEX_RUNTIME_BIN`/legacy's generic
  `resolve_executable` must not appear anywhere in `src/docs` after this
  slice (grep-verifiable, consistent with every prior slice's constraint).

## Risks and open judgment calls

1. **RESOLVED — `build-sections` stage raises `NotImplementedError`
   instead of working.** See Judgment call 3. Downstream effect:
   `run_pipeline("prep")` and `run_pipeline("all")` will never report
   `passed=True` until a future slice models draft-rendering-from-context
   plus a `prompts_dir` concept and re-wires this one stage — this is a
   real, currently-permanent limitation of this slice's `run_pipeline`,
   not a bug introduced here. `run_pipeline("assemble")` is unaffected
   (doesn't include this stage).
2. **RESOLVED — `_context_confirmed_lines` drops legacy's `dato_sensible`
   ledger classification.** See Judgment call 4. Downstream effect: the
   `build-ledger` stage's output will not contain a "Datos sensibles
   excluidos del cuerpo" section sourced from context topics (manifest-
   sourced `dato_sensible` facts, e.g. from `CollectionService.collect_sources`'s
   own sensitive-field detection, are unaffected — that's a different code
   path, already flowing through `EvidenceService.load_manifest_facts`
   inside `render_fact_ledger` itself). A future micro-slice can close this
   by extending `EvidenceService.render_fact_ledger`'s signature with a
   second `context_sensitive_lines: list[str] | None = None` parameter.
3. **Low-stakes, plan-author's call, not escalated:** `_rules_manifest_state`
   duplicates ~3 lines of logic `DoctorService.run_doctor` already computes
   internally (not exposed as a reusable method). Extracting a shared
   helper across two unrelated services for 3 lines was judged not worth
   the coupling it would introduce (either a new free function both import,
   or `PipelineService` reaching into `DoctorService`'s internals) — a
   reviewer could reasonably ask for the free-function version; flagged for
   their judgment, not treated as load-bearing.
4. **Low-stakes:** `run_pipeline` drops legacy's `stages: list[tuple[str,
   Any, bool]] | None = None` override parameter (see Task 5's "Verbatim
   legacy reference" note) since nothing in this migration constructs a
   custom stage list today. If Slice 15's CLI needs partial-stage-set
   execution (e.g., `run --only doctor,build-rules`), the cleanest
   extension is an optional `only: list[str] | None` filter on
   `pipeline_stage_plan`'s result, not resurrecting the raw-callable
   override — flagged for that future slice's author, not solved here.
5. **Low-stakes:** Task 4 bundles `log_run`/`list_runs`/`_runs_dir` into one
   task rather than splitting `log_run` and `list_runs` further — both are
   small, share `_runs_dir`, and are naturally tested together (a
   `list_runs` test needs `log_run` to have written something first, or an
   empty-directory case). Mirrors Slice 13's Task-1 granularity note.
