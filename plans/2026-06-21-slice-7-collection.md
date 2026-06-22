# Slice 7 — Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Branch:** `design/harness-migration`

**Goal:** Port legacy `collect_sources`, `classify_source`, `parse_gh_issues`, `collect_issues`, `collect_code_evidence`, `collect_git_facts`, `dedupe_facts`, and `_detect_github_repo` (`tesina_harness.py` lines 885-1156) into pure domain functions plus a new port/adapter/service triplet. These functions build three manifests — `source-manifest.json` (`collect_sources`), `issues-manifest.json` (`collect_issues`), `code-evidence-manifest.json` (`collect_code_evidence`) — by globbing files, hashing them, calling `gh`/`git` as subprocesses, and assembling fact lists. This slice splits the I/O-entangled legacy functions into: pure domain functions that classify, parse, and dedupe data already fetched (`domain/collection.py`), a new `SourceRepository` port describing the very different I/O shape these functions need (subprocess execution + glob-and-read-many-files, distinct from `EvidenceRepository`'s single-file hashing), a `FilesystemSourceRepository` adapter doing the real globbing/subprocess work, and a `CollectionService` wiring domain decisions to port I/O — replacing legacy `collect_sources`/`collect_issues`/`collect_code_evidence` end-to-end.

**Architecture:** Pragmatic hexagonal, same shape as Slices 1-6. `domain/collection.py` is pure: no `Path.glob`, no `subprocess.run`, no `Path.read_text`. It accepts plain strings/dicts describing data already fetched (a source's declared `type`, a raw JSON string from `gh`, a list of already-built fact dicts) and returns classifications, parsed lists, or deduped lists. `domain/ports/source_repository.py` declares the `SourceRepository` Protocol the application layer depends on. `infrastructure/persistence/filesystem_source_repository.py` implements that Protocol with real `pathlib`/`subprocess`/`shutil` I/O. `application/collection.py` holds `CollectionService`, composing the port (glob/read/hash/subprocess) with the domain functions (classify/parse/dedupe) and `EvidenceRepository`'s existing `hash_file`/`write_manifest` (reused, not reimplemented) — mirroring `EvidenceService`'s composition pattern. Nothing in `domain/collection.py` imports from `application`, `infrastructure`, or `cli`.

**Tech Stack:** Python ≥3.11, Pydantic v2 (no new models needed — manifests stay plain `dict`, matching legacy's untyped JSON shape and this codebase's existing precedent in Slices 4/6), `subprocess.run` (verbatim legacy invocation shape), pytest with `tmp_path` + `monkeypatch`/fake-port substitution for adapter/integration tests (no test shells out to a real `gh`/`git` binary).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. `domain/collection.py` imports nothing from `application`, `infrastructure`, or `cli`.
- **Reuse, don't re-port:** `sha256_file`/`_as_posix`/`write_json_manifest` are already ported as `EvidenceRepository.hash_file`/path-resolve-as_posix/`write_manifest` (Slice 4). `_clean_markdown_text` is already ported as `domain/markdown_text.py:clean_markdown_text` (Slice 3). `CollectionService` depends on **both** `SourceRepository` (new, this slice) and `EvidenceRepository` (existing, Slice 4) rather than duplicating hashing/manifest-write logic into the new port — see Task 3's rationale.
- **No typed config model.** Following the exact precedent of `EvidenceService.build_rules(self, config: dict[str, Any])` (Slice 4) and `ReviewService`/`ContextService` methods, every new service method in this slice takes a raw `config: dict[str, Any]` and reads `config["paths"][...]` / `config.get(...)` directly. No `ProjectConfig` Pydantic model is introduced — same deferral as Slice 4's Self-Review item 2, still deferred to the eventual CLI slice (Slice 15 per `roadmap.md`).
- **Parity over cleanup.** No retry logic, no timeouts, no caching, no new try/except beyond what legacy has. `collect_issues`'s `subprocess.run(..., check=True, ...)` for `gh issue list` is **not** wrapped in a new try/except — legacy lets `CalledProcessError` (and the explicit `RuntimeError`s for missing `gh`/repo) bubble up unhandled, and this port preserves that exactly. `collect_git_facts` and `_detect_github_repo`, by contrast, **do** have a bare `except Exception` in legacy that swallows subprocess failure into a fallback value — this is also preserved verbatim (see Task 2 and Task 4), not "fixed" into a narrower exception type.
- **REPO_ROOT is an injected parameter, not a module constant.** Legacy's `REPO_ROOT = TESINA_ROOT.parent` is a fixed path computed once at import time from the script's own location. This codebase has no equivalent of "the script's own location" as a meaningful concept (it's a library, not a single script), and Slice 6's pre-execution review established the convention "caller passes values in, the port doesn't compute paths internally." Every new port method that legacy implicitly ran with `cwd=REPO_ROOT` (`collect_git_facts`, `_detect_github_repo`) takes `repo_root: Path` as an explicit parameter instead.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## Design decisions (documented per the task brief)

1. **New port, not an `EvidenceRepository` extension.** `EvidenceRepository` (Slice 4) is shaped around "hash/read one already-known file, read/write one manifest" — single-file primitives. This slice's impure functions need: globbing several *different* config-declared roots (`context_dir`, `manual_dir`, `evidence_sources.files`, `evidence_sources.code_globs`), detecting whether `gh` is on `PATH`, and running `subprocess.run` against `gh`/`git` with captured stdout. That is a different I/O shape (subprocess + multi-root glob orchestration vs. plain file hashing) serving a different concern (raw source/evidence/issue collection vs. manifest hashing for the rules engine). Bolting it onto `EvidenceRepository` would mix "hash a known file" with "find out what files even exist and shell out to external CLIs," diluting that Protocol's single responsibility. A new `SourceRepository` port keeps each Protocol narrow and named for what it actually does. `CollectionService` (Task 4) depends on **both** ports — `SourceRepository` for the new glob/subprocess primitives, `EvidenceRepository` for `hash_file`/`write_manifest` reuse — rather than duplicating those two methods onto the new Protocol.
2. **`resolve_executable`: minimal real port, no fallback-path machinery.** `collect_issues` calls `resolve_executable("gh", [])` — empty fallback list, meaning the only behavior actually exercised at this call site is `shutil.which(name)` (the bundled-runtime-binary branch and the `fallbacks` loop are dead code for this caller, since the fallback list is empty and `CODEX_RUNTIME_BIN` is itself an out-of-scope packaging path used only by pandoc/libreoffice/pdfinfo/pdftoppm callers later in legacy — Slice 10+ concern). Porting the full function with its bundled-runtime/fallback-list machinery now would port behavior nothing in scope exercises. This slice ports a minimal `SourceRepository.find_executable(name: str) -> str | None` that does exactly `shutil.which(name)` — equivalent to legacy's `resolve_executable(name, [])` for every existing call site in scope. The fuller version (fallback paths, bundled runtime) is deferred to whichever future slice ports `build_docx`/QA tooling (Slice 10-12 per `roadmap.md`), which is the only place legacy calls `resolve_executable` with non-empty fallbacks.
3. **`load_context`'s role in `collect_sources`: ported via a new `SourceRepository` method, not via `ContextRepository`.** Legacy's `load_context(config)` (lines 606-615) globs `context_dir` for `*.md`, skips `_`-prefixed files and `index.md`, and returns `{stem: raw_text}` — used in `collect_sources` (lines 927, 939) purely to build a lowercased, concatenated blob of all approved-context text for substring/regex searches (`contradiction_terms`, `sensitive_context_fields`). It does **not** need `ContextRepository`'s topic-parsing machinery (`read_topic`/`Topic` model/frontmatter) — it just wants raw concatenated text. Checking `domain/ports/context_repository.py`: the closest method is `read_topic_raw(doc_id, topic_id)`, which reads **one** topic by id, not "all topic files in a directory" — there is no glob-all equivalent, and adding one to `ContextRepository` would mean that Protocol gains a method only `collect_sources` ever calls, for a concern (raw context-dir globbing) that isn't really "context completion / topic CRUD," `ContextRepository`'s actual responsibility. Decision: port this as `SourceRepository.read_context_texts(context_dir: Path) -> dict[str, str]`, replicating legacy's glob/skip/read exactly. This keeps `ContextRepository` unchanged and keeps the new port's scope coherent ("read source/context files for collection purposes"). The `contradiction_terms`/`sensitive_context_fields` fact-injection logic itself **is** ported (Task 1, pure) since a clean I/O path exists — no scope-carve-out needed here, unlike the `source_hash`/`prompt_hash` deferral in Slice 6.
4. **`REPO_ROOT` becomes a caller-supplied `repo_root: Path`.** `collect_git_facts(path: Path)` and `_detect_github_repo()` both implicitly use module-level `REPO_ROOT` as the subprocess `cwd`. Ported as `SourceRepository.run_git_log(path: Path, repo_root: Path) -> str` and `SourceRepository.detect_github_remote(repo_root: Path) -> str`, with `repo_root` passed in by `CollectionService` callers (ultimately from `config` or a future CLI-level workspace root — out of scope to wire up a concrete source for `repo_root` beyond accepting it as a parameter in this slice, matching Slice 6's "pass values in" convention).
5. **`collect_issues` error parity confirmed.** `gh issue list ... check=True` raising `subprocess.CalledProcessError` on failure is legacy's real, intentional behavior (no try/except wraps it) — preserved as-is. The two explicit `RuntimeError`s (`gh` missing; repo not detected) are also preserved verbatim, including their exact Spanish error strings.

---

## File Structure

- `src/docs/domain/collection.py` — `classify_source`, `parse_gh_issue`, `parse_gh_issues`, `dedupe_facts`.
- `src/docs/domain/ports/source_repository.py` — `SourceRepository` Protocol.
- `src/docs/infrastructure/persistence/filesystem_source_repository.py` — `FilesystemSourceRepository`.
- `src/docs/application/collection.py` — `CollectionService`.
- `tests/unit/domain/test_collection.py`
- `tests/unit/infrastructure/test_filesystem_source_repository.py`
- `tests/integration/test_collection_service.py`

---

### Task 1: Pure domain functions — classify, parse, dedupe

**Files:**
- Create: `src/docs/domain/collection.py`
- Test: `tests/unit/domain/test_collection.py`

**Legacy source (verbatim, lines 959-988 + 1127-1135):**

```python
def classify_source(source_type: str) -> str:
    if source_type in {"approved_context", "institutional_manual", "mobile_code_or_docs"}:
        return "confirmado"
    if source_type == "example_reference":
        return "fuera_de_alcance"
    if source_type == "cover_template":
        return "confirmado"
    return "pendiente"


def parse_gh_issues(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"No se pudo parsear salida JSON de gh: {exc}") from exc
    issues: list[dict[str, Any]] = []
    for item in data:
        labels = item.get("labels") or []
        issues.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "url": item.get("url", ""),
                "labels": [label.get("name", "") for label in labels if isinstance(label, dict)],
                "classification": "confirmado",
                "source": "github_issues",
            }
        )
    return issues


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = f"{fact.get('classification')}|{fact.get('claim')}|{fact.get('source')}"
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    return deduped
```

**Interfaces:**
- Consumes: nothing from other domain modules (self-contained, like `domain/evidence.py`).
- Produces:
  - `classify_source(source_type: str) -> str` — verbatim port, identical branching and Spanish classification strings (`"confirmado"`, `"fuera_de_alcance"`, `"pendiente"`).
  - `parse_gh_issues(raw: str) -> list[dict[str, Any]]` — verbatim port. Stays in `domain/` per the task brief: it takes an already-fetched JSON string and does no subprocess work itself; `json.loads`/`json.JSONDecodeError` are pure stdlib parsing, not I/O.
  - `dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]` — verbatim port, list-only dedup by composite key, no I/O.

**Note on `parse_gh_issues`'s error message:** the `ValueError(f"No se pudo parsear salida JSON de gh: {exc}")` string is preserved verbatim — it is a user/document-facing diagnostic, not an internal code comment, consistent with the project convention of keeping legacy Spanish strings byte-for-byte where they're data, not code.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_collection.py
import pytest

from docs.domain.collection import classify_source, dedupe_facts, parse_gh_issues


@pytest.mark.parametrize(
    "source_type,expected",
    [
        ("approved_context", "confirmado"),
        ("institutional_manual", "confirmado"),
        ("mobile_code_or_docs", "confirmado"),
        ("example_reference", "fuera_de_alcance"),
        ("cover_template", "confirmado"),
        ("evidence", "pendiente"),
        ("unknown_type", "pendiente"),
    ],
)
def test_classify_source(source_type, expected):
    assert classify_source(source_type) == expected


def test_parse_gh_issues_empty_string_defaults_to_empty_list():
    assert parse_gh_issues("") == []


def test_parse_gh_issues_invalid_json_raises_value_error_with_spanish_message():
    with pytest.raises(ValueError, match="No se pudo parsear salida JSON de gh"):
        parse_gh_issues("not json")


def test_parse_gh_issues_maps_fields_and_forces_classification():
    raw = (
        '[{"number": 1, "title": "Bug", "state": "OPEN", "url": "https://x", '
        '"labels": [{"name": "bug"}, {"name": "p1"}]}]'
    )
    issues = parse_gh_issues(raw)
    assert issues == [
        {
            "number": 1,
            "title": "Bug",
            "state": "OPEN",
            "url": "https://x",
            "labels": ["bug", "p1"],
            "classification": "confirmado",
            "source": "github_issues",
        }
    ]


def test_parse_gh_issues_missing_optional_fields_default_safely():
    issues = parse_gh_issues('[{"number": 2}]')
    assert issues == [
        {
            "number": 2,
            "title": "",
            "state": "",
            "url": "",
            "labels": [],
            "classification": "confirmado",
            "source": "github_issues",
        }
    ]


def test_parse_gh_issues_ignores_non_dict_labels():
    issues = parse_gh_issues('[{"number": 3, "labels": ["raw-string-label", {"name": "ok"}]}]')
    assert issues[0]["labels"] == ["ok"]


def test_dedupe_facts_removes_exact_duplicates_by_composite_key():
    fact = {"classification": "confirmado", "claim": "x", "source": "y"}
    deduped = dedupe_facts([fact, dict(fact)])
    assert deduped == [fact]


def test_dedupe_facts_preserves_first_occurrence_order():
    a = {"classification": "confirmado", "claim": "a", "source": "s"}
    b = {"classification": "confirmado", "claim": "b", "source": "s"}
    deduped = dedupe_facts([a, b, dict(a)])
    assert deduped == [a, b]


def test_dedupe_facts_distinguishes_by_each_key_component():
    a = {"classification": "confirmado", "claim": "x", "source": "s1"}
    b = {"classification": "confirmado", "claim": "x", "source": "s2"}
    assert dedupe_facts([a, b]) == [a, b]


def test_dedupe_facts_empty_list_returns_empty_list():
    assert dedupe_facts([]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_collection.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.collection`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/collection.py
from __future__ import annotations

import json
from typing import Any

_CONFIRMED_SOURCE_TYPES = {"approved_context", "institutional_manual", "mobile_code_or_docs"}


def classify_source(source_type: str) -> str:
    if source_type in _CONFIRMED_SOURCE_TYPES:
        return "confirmado"
    if source_type == "example_reference":
        return "fuera_de_alcance"
    if source_type == "cover_template":
        return "confirmado"
    return "pendiente"


def parse_gh_issues(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"No se pudo parsear salida JSON de gh: {exc}") from exc
    issues: list[dict[str, Any]] = []
    for item in data:
        labels = item.get("labels") or []
        issues.append(
            {
                "number": item.get("number"),
                "title": item.get("title", ""),
                "state": item.get("state", ""),
                "url": item.get("url", ""),
                "labels": [label.get("name", "") for label in labels if isinstance(label, dict)],
                "classification": "confirmado",
                "source": "github_issues",
            }
        )
    return issues


def dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for fact in facts:
        key = f"{fact.get('classification')}|{fact.get('claim')}|{fact.get('source')}"
        if key not in seen:
            deduped.append(fact)
            seen.add(key)
    return deduped
```

**Test expectations note:** tests pin observable behavior (classification mapping, parsed issue shape, dedup-by-composite-key), not internal structure — consistent with this project's strict TDD convention. No test asserts on `_CONFIRMED_SOURCE_TYPES` existing as a set; it's an implementation detail.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_collection.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/collection.py tests/unit/domain/test_collection.py
git commit -m "feat(domain): add classify_source/parse_gh_issues/dedupe_facts pure collection helpers"
```

---

### Task 2: SourceRepository port

**Files:**
- Create: `src/docs/domain/ports/source_repository.py`
- Test: none (a `Protocol` with no behavior has nothing to unit test on its own, exactly as Slice 4 Task 2's `EvidenceRepository` port was introduced without a standalone test file — verified indirectly by Task 3's adapter conforming to it).

**Legacy source these methods must jointly cover (verbatim, lines 906-925, 992-1021, 1066-1089, 1102-1124, 1138-1155, plus `load_context` lines 606-615 and `resolve_executable` line 2297 as discussed in Design decision 2/3 above):**

```python
for path in sorted(Path(config["paths"]["context_dir"]).glob("*.md")):
    if path.name.startswith("_") or path.name == "index.md":
        continue
    add_file(path, "approved_context", "contexto aprobado del documento")
manual_dir = config["paths"].get("manual_dir")
if manual_dir and Path(manual_dir).exists():
    for path in sorted(Path(manual_dir).glob("*.md")):
        add_file(path, "institutional_manual", "norma documental obligatoria")
```

```python
def load_context(config: dict[str, Any]) -> dict[str, str]:
    context_dir = Path(config["paths"]["context_dir"])
    context: dict[str, str] = {}
    if not context_dir.exists():
        return context
    for path in sorted(context_dir.glob("*.md")):
        if path.name.startswith("_") or path.name == "index.md":
            continue
        context[path.stem] = path.read_text(encoding="utf-8")
    return context
```

```python
gh = resolve_executable("gh", [])
...
proc = subprocess.run(
    [gh, "issue", "list", "--repo", repo, "--state", "all", "--limit", "200",
     "--json", "number,title,state,createdAt,closedAt,labels,url"],
    check=True, capture_output=True, text=True, encoding="utf-8",
)
```

```python
matched = sorted(root.glob(glob_entry.get("glob", ""))) if glob_entry.get("glob") else []
```

```python
def collect_git_facts(path: Path) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "--max-count=40", "--", str(path.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        )
    except Exception:
        return [{"classification": "pendiente", "claim": "No se pudo obtener git log para la app móvil.", "source": "git"}]
    ...


def _detect_github_repo() -> str:
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
        )
    except Exception:
        return ""
    remote = proc.stdout.strip()
    match = re.search(r"github\.com[:/](?P<repo>[^/]+/[^/.]+(?:-[^/.]*)?)", remote)
    if not match:
        return ""
    return match.group("repo").removesuffix(".git")
```

**Interfaces:**
- Consumes: nothing (pure interface declaration).
- Produces: `SourceRepository` Protocol with primitives covering every impure operation `CollectionService` (Task 4) needs that `EvidenceRepository` does not already provide:
  - `glob_markdown(directory: Path) -> list[Path]` — sorted `*.md` glob; used for `context_dir` and `manual_dir` scanning in `collect_sources`.
  - `read_context_texts(context_dir: Path) -> dict[str, str]` — verbatim `load_context` port (Design decision 3): returns `{}` if `context_dir` doesn't exist, else `{stem: text}` for every `*.md` file not starting with `_` and not named `index.md`.
  - `glob_pattern(root: Path, pattern: str) -> list[Path]` — sorted arbitrary glob under `root`; used by `collect_code_evidence`'s `code_globs` entries (`root.glob(glob_entry.get("glob", ""))`). Kept distinct from `glob_markdown` because the glob pattern is config-supplied, not hardcoded to `*.md`.
  - `find_executable(name: str) -> str | None` — `shutil.which(name)` only (Design decision 2 — no fallback-path machinery ported).
  - `run_gh_issue_list(gh_path: str, repo: str) -> str` — runs the exact `gh issue list --repo {repo} --state all --limit 200 --json number,title,state,createdAt,closedAt,labels,url` subprocess with `check=True, capture_output=True, text=True, encoding="utf-8"`, returns `proc.stdout`. `check=True` means `CalledProcessError` propagates uncaught (Design decision 5 / parity note).
  - `run_git_log(path: Path, repo_root: Path) -> str | None` — runs `git log --oneline --max-count=40 -- {relative_path}` with `cwd=repo_root`; returns `proc.stdout` on success, `None` on any exception (mirrors legacy's bare `except Exception: return [...]` — the *fallback fact* itself is a domain/service concern, not the port's; the port only reports "did the git call succeed, and if so what was the output," see Task 4).
  - `detect_github_remote(repo_root: Path) -> str` — runs `git remote get-url origin` with `cwd=repo_root`; returns the stripped stdout on success, `""` on any exception (matching `_detect_github_repo`'s bare `except Exception: return ""`).

This Protocol is intentionally a thin "filesystem glob + subprocess execution" interface, mirroring `EvidenceRepository`'s "thin primitives, not one coarse method" shape (Slice 4 Task 2's stated rationale) — the regex match against `github.com` remotes, and the decision of what fallback git-log fact to inject on failure, stay in domain/application, not the port.

- [ ] **Step 1: Write the failing test**

This task introduces only a `Protocol` declaration with no independently testable runtime behavior — same situation as Slice 4 Task 2. Skip directly to Step 3; Task 3's adapter test is the first test exercising this Protocol's shape.

- [ ] **Step 2: Run test to verify it fails**

N/A — no test file in this task.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/source_repository.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SourceRepository(Protocol):
    def glob_markdown(self, directory: Path) -> list[Path]: ...
    def read_context_texts(self, context_dir: Path) -> dict[str, str]: ...
    def glob_pattern(self, root: Path, pattern: str) -> list[Path]: ...
    def find_executable(self, name: str) -> str | None: ...
    def run_gh_issue_list(self, gh_path: str, repo: str) -> str: ...
    def run_git_log(self, path: Path, repo_root: Path) -> str | None: ...
    def detect_github_remote(self, repo_root: Path) -> str: ...
```

- [ ] **Step 4: Run test to verify it passes**

N/A — no test in this task. Sanity-check the module imports cleanly:

Run: `uv run python -c "from docs.domain.ports.source_repository import SourceRepository; print(SourceRepository)"`
Expected: prints the Protocol class, no import error.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/source_repository.py
git commit -m "feat(domain): add SourceRepository port for glob/subprocess collection I/O"
```

---

### Task 3: FilesystemSourceRepository adapter

**Files:**
- Create: `src/docs/infrastructure/persistence/filesystem_source_repository.py`
- Test: `tests/unit/infrastructure/test_filesystem_source_repository.py`

**Legacy subprocess invocation parity (confirmed from lines 998-1016, 1104-1111, 1140-1147):**

```python
proc = subprocess.run(
    [gh, "issue", "list", "--repo", repo, "--state", "all", "--limit", "200",
     "--json", "number,title,state,createdAt,closedAt,labels,url"],
    check=True, capture_output=True, text=True, encoding="utf-8",
)
```
```python
proc = subprocess.run(
    ["git", "log", "--oneline", "--max-count=40", "--", str(path.relative_to(REPO_ROOT))],
    cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
)
```
```python
proc = subprocess.run(
    ["git", "remote", "get-url", "origin"],
    cwd=REPO_ROOT, check=True, capture_output=True, text=True, encoding="utf-8",
)
```

All three use `check=True, capture_output=True, text=True, encoding="utf-8"` — this exact kwargs tuple is preserved verbatim in every adapter method that shells out.

**`resolve_executable` minimal-port parity (Design decision 2):** `shutil.which(name)` only — no bundled-runtime branch, no fallback loop.

**`load_context` parity (Design decision 3, lines 606-615):** glob `*.md` under `context_dir`, skip `_`-prefixed and `index.md`, return `{}` if dir missing.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_filesystem_source_repository.py
import subprocess
from pathlib import Path

import pytest

from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository


@pytest.fixture
def repo() -> FilesystemSourceRepository:
    return FilesystemSourceRepository()


def test_glob_markdown_sorted(tmp_path: Path, repo):
    (tmp_path / "01-b.md").write_text("b")
    (tmp_path / "00-a.md").write_text("a")
    (tmp_path / "ignore.txt").write_text("x")
    files = repo.glob_markdown(tmp_path)
    assert [f.name for f in files] == ["00-a.md", "01-b.md"]


def test_read_context_texts_returns_empty_dict_when_dir_missing(tmp_path: Path, repo):
    assert repo.read_context_texts(tmp_path / "missing") == {}


def test_read_context_texts_skips_underscore_and_index_files(tmp_path: Path, repo):
    (tmp_path / "_draft.md").write_text("draft")
    (tmp_path / "index.md").write_text("index")
    (tmp_path / "scope.md").write_text("alcance del proyecto")
    texts = repo.read_context_texts(tmp_path)
    assert texts == {"scope": "alcance del proyecto"}


def test_glob_pattern_sorted_under_root(tmp_path: Path, repo):
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "a.py").write_text("a")
    files = repo.glob_pattern(tmp_path, "*.py")
    assert [f.name for f in files] == ["a.py", "b.py"]


def test_find_executable_returns_none_for_unknown_binary(repo):
    assert repo.find_executable("definitely-not-a-real-binary-xyz") is None


def test_find_executable_resolves_known_binary_on_path(repo, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git" if name == "git" else None)
    assert repo.find_executable("git") == "/usr/bin/git"


def test_run_gh_issue_list_invokes_expected_subprocess_args(repo, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    result = repo.run_gh_issue_list("/usr/bin/gh", "owner/repo")
    assert result == "[]"
    assert captured["args"] == [
        "/usr/bin/gh", "issue", "list", "--repo", "owner/repo", "--state", "all",
        "--limit", "200", "--json", "number,title,state,createdAt,closedAt,labels,url",
    ]
    assert captured["kwargs"] == {
        "check": True, "capture_output": True, "text": True, "encoding": "utf-8",
    }


def test_run_gh_issue_list_propagates_called_process_error(repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        repo.run_gh_issue_list("/usr/bin/gh", "owner/repo")


def test_run_git_log_returns_stdout_on_success(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc123 commit message\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    target = tmp_path / "sub" / "file.py"
    result = repo.run_git_log(target, tmp_path)
    assert result == "abc123 commit message\n"


def test_run_git_log_returns_none_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.run_git_log(tmp_path / "file.py", tmp_path) is None


def test_detect_github_remote_returns_stripped_stdout(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.detect_github_remote(tmp_path) == "git@github.com:org/repo.git"


def test_detect_github_remote_returns_empty_string_on_any_exception(tmp_path: Path, repo, monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("git not found")

    monkeypatch.setattr("subprocess.run", fake_run)
    assert repo.detect_github_remote(tmp_path) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_filesystem_source_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.filesystem_source_repository`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/infrastructure/persistence/filesystem_source_repository.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_RUN_KWARGS = {"check": True, "capture_output": True, "text": True, "encoding": "utf-8"}


class FilesystemSourceRepository:
    def glob_markdown(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.md"))

    def read_context_texts(self, context_dir: Path) -> dict[str, str]:
        context: dict[str, str] = {}
        if not context_dir.exists():
            return context
        for path in sorted(context_dir.glob("*.md")):
            if path.name.startswith("_") or path.name == "index.md":
                continue
            context[path.stem] = path.read_text(encoding="utf-8")
        return context

    def glob_pattern(self, root: Path, pattern: str) -> list[Path]:
        return sorted(root.glob(pattern)) if pattern else []

    def find_executable(self, name: str) -> str | None:
        return shutil.which(name)

    def run_gh_issue_list(self, gh_path: str, repo: str) -> str:
        proc = subprocess.run(
            [
                gh_path,
                "issue",
                "list",
                "--repo",
                repo,
                "--state",
                "all",
                "--limit",
                "200",
                "--json",
                "number,title,state,createdAt,closedAt,labels,url",
            ],
            **_RUN_KWARGS,
        )
        return proc.stdout

    def run_git_log(self, path: Path, repo_root: Path) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "log", "--oneline", "--max-count=40", "--", str(path.relative_to(repo_root))],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception:
            return None
        return proc.stdout

    def detect_github_remote(self, repo_root: Path) -> str:
        try:
            proc = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo_root,
                **_RUN_KWARGS,
            )
        except Exception:
            return ""
        return proc.stdout.strip()
```

**Note on `run_git_log` returning `None` vs. legacy returning a fallback fact list directly:** legacy's `collect_git_facts` couples "did the subprocess fail" with "here is the fallback fact to use instead" in one function. This port separates them: the adapter reports raw success/failure (`str | None`), and `CollectionService` (Task 4) — not the port — decides to inject the `"pendiente"` fallback fact dict when the result is `None`. This keeps the adapter a thin I/O primitive and the fallback-fact *content* (Spanish claim text) a service-level decision, consistent with Slice 4's port-vs-service split rationale.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_filesystem_source_repository.py -v`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/filesystem_source_repository.py tests/unit/infrastructure/test_filesystem_source_repository.py
git commit -m "feat(infrastructure): add FilesystemSourceRepository with verbatim legacy glob/subprocess behavior"
```

---

### Task 4: CollectionService

**Files:**
- Create: `src/docs/application/collection.py`
- Test: `tests/integration/test_collection_service.py`

**Interfaces:**
- Consumes: `SourceRepository` (Task 2); `EvidenceRepository` (Slice 4, reused for `hash_file`/`write_manifest`); `classify_source`, `parse_gh_issues`, `dedupe_facts` (Task 1); `clean_markdown_text` (Slice 3, `domain/markdown_text.py`).
- Produces: `CollectionService` class with:
  - `collect_sources(self, config: dict[str, Any]) -> Path`
  - `collect_issues(self, config: dict[str, Any]) -> Path`
  - `collect_code_evidence(self, config: dict[str, Any], repo_root: Path | None = None) -> Path`

**`collect_sources` — exact build steps (verbatim from legacy lines 885-956):**

```python
def collect_sources(config: dict[str, Any]) -> Path:
    manifest_path = Path(config["paths"]["source_manifest"])
    sources: list[dict[str, Any]] = []

    def add_file(path: Path, source_type: str, use: str) -> None:
        if not path.exists() or not path.is_file():
            return
        text = ""
        if path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml"}:
            text = path.read_text(encoding="utf-8", errors="replace")
        sources.append({
            "path": _as_posix(path), "type": source_type, "use": use,
            "classification": classify_source(source_type), "sha256": sha256_file(path),
            "excerpt": _clean_markdown_text(text[:900]) if text else "",
        })

    for path in sorted(Path(config["paths"]["context_dir"]).glob("*.md")):
        if path.name.startswith("_") or path.name == "index.md":
            continue
        add_file(path, "approved_context", "contexto aprobado del documento")
    manual_dir = config["paths"].get("manual_dir")
    if manual_dir and Path(manual_dir).exists():
        for path in sorted(Path(manual_dir).glob("*.md")):
            add_file(path, "institutional_manual", "norma documental obligatoria")

    evidence = config.get("evidence_sources", {})
    evidence_root = Path(evidence["root"]) if evidence.get("root") else None
    for entry in evidence.get("files", []):
        rel = entry.get("path", "")
        target = (evidence_root / rel) if evidence_root else Path(rel)
        add_file(target, entry.get("type", "evidence"), entry.get("use", "evidencia técnica secundaria"))

    if config["paths"].get("template_docx"):
        add_file(Path(config["paths"]["template_docx"]), "cover_template", "plantilla de portada reutilizable")
    if config["paths"].get("example_pdf"):
        add_file(Path(config["paths"]["example_pdf"]), "example_reference", "referencia estructural, no fuente de contenido")

    context_text = "\n".join(load_context(config).values()).lower()
    facts: list[dict[str, Any]] = list(config.get("collect_facts_seed", []))
    contradiction_terms = [term.lower() for term in evidence.get("scope_contradiction_terms", [])]
    if contradiction_terms and any(term in context_text for term in contradiction_terms):
        facts.append({
            "classification": "contradiccion",
            "claim": "El contexto menciona términos fuera del alcance declarado; resolver con evidencia o delimitar.",
            "source": "context",
        })
    for field in config.get("privacy", {}).get("sensitive_context_fields", []):
        if re.search(rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|", "\n".join(load_context(config).values()), flags=re.IGNORECASE):
            facts.append({
                "classification": "dato_sensible",
                "claim": f"El contexto aprobado contiene el campo sensible `{field}`; no debe pasar al cuerpo sin instrucción explícita.",
                "source": "tesina/context",
            })

    manifest = {
        "schema": 1, "policy": config.get("project", {}).get("scope_policy", ""),
        "source_count": len(sources), "sources": sources, "facts": facts,
    }
    write_json_manifest(manifest_path, manifest)
    return manifest_path
```

**Service wiring notes:**
1. `add_file`'s inline closure becomes a private `_collect_file_source` method (or nested closure — implementer's call, behavior is what's pinned) that calls `self.evidence_repository.file_exists`/`file_size`... — note legacy's `add_file` actually needs `path.is_file()` (not in `EvidenceRepository`) and `path.read_text(..., errors="replace")` (matches `SourceRepository` semantics, not `EvidenceRepository.read_text` which also uses `errors="replace"` — either port's `read_text` works; use `EvidenceRepository.read_text` since it already exists with identical semantics, do not add a duplicate). Add `is_file()` as a need: reuse `self.evidence_repository.file_exists(path) and path.is_file()` is awkward since `file_exists` only wraps `.exists()` — call `path.is_file()` directly in the service (it's a cheap stdlib `Path` predicate, not the kind of "I/O orchestration" worth hiding behind a port method, consistent with how `EvidenceService.build_rules` already calls `path.resolve().as_posix()` directly rather than through a port method).
2. The two `load_context(config).values()` calls in legacy are redundant (called twice, same result) — the service computes `context_texts = self.source_repository.read_context_texts(Path(config["paths"]["context_dir"]))` once and reuses it for both the `contradiction_terms` check and the `sensitive_context_fields` regex scan. This is a deliberate, documented exception (single computation replacing a verbatim duplicate call) — not a behavior change, since `load_context` is referentially transparent over the same `config`. Flagged here exactly like Slice 3's `pending_allowed_in_draft` fix precedent.
3. `context_text = "\n".join(context_texts.values()).lower()` — dict ordering in Python 3.7+ is insertion order, and `read_context_texts` builds its dict from a sorted glob, so this is deterministic and matches legacy's iteration order exactly (legacy's `load_context` also builds from a sorted glob).
4. `sha256_file`/`_as_posix`/`write_json_manifest` calls become `self.evidence_repository.hash_file(path)` / `path.resolve().as_posix()` / `self.evidence_repository.write_manifest(manifest_path, manifest)` respectively — reused from Slice 4, not reimplemented (per Global Constraints).
5. `_clean_markdown_text` becomes `clean_markdown_text` import from `domain/markdown_text.py` (Slice 3).
6. `re.search` for `sensitive_context_fields` stays inline in the service (it's a one-line stdlib regex over already-fetched text, not I/O — keeping it here, not pushing it into `domain/collection.py`, is consistent with how `EvidenceService` keeps small inline logic rather than extracting single-use one-liners into domain functions; if the implementer prefers a pure `domain.collection.scan_sensitive_fields(context_text, fields) -> list[str]` helper for testability, that is an acceptable refinement but not required by this plan — note it as implementer discretion, not a fixed requirement).

**`collect_issues` — exact build steps (verbatim from legacy lines 991-1021):**

```python
def collect_issues(config: dict[str, Any]) -> Path:
    gh = resolve_executable("gh", [])
    if not gh:
        raise RuntimeError("GitHub CLI `gh` no está disponible. Instálalo o exporta issues a JSON.")
    repo = _detect_github_repo()
    if not repo:
        raise RuntimeError("No se pudo detectar el repositorio GitHub desde `git remote get-url origin`.")
    proc = subprocess.run([...], check=True, capture_output=True, text=True, encoding="utf-8")
    issues = parse_gh_issues(proc.stdout)
    manifest_path = Path(config["paths"]["issues_manifest"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_manifest(manifest_path, {"schema": 1, "repo": repo, "issue_count": len(issues), "issues": issues})
    return manifest_path
```

Ported as:
```python
def collect_issues(self, config: dict[str, Any], repo_root: Path) -> Path:
    gh = self.source_repository.find_executable("gh")
    if not gh:
        raise RuntimeError("GitHub CLI `gh` no está disponible. Instálalo o exporta issues a JSON.")
    repo = self.source_repository.detect_github_remote(repo_root)
    repo = _extract_github_repo(repo)  # see _detect_github_repo regex note below
    if not repo:
        raise RuntimeError("No se pudo detectar el repositorio GitHub desde `git remote get-url origin`.")
    raw = self.source_repository.run_gh_issue_list(gh, repo)
    issues = parse_gh_issues(raw)
    manifest_path = Path(config["paths"]["issues_manifest"])
    payload = {"schema": 1, "repo": repo, "issue_count": len(issues), "issues": issues}
    self.evidence_repository.write_manifest(manifest_path, payload)
    return manifest_path
```

**Important correction caught while porting `_detect_github_repo`:** legacy's `_detect_github_repo()` does **two** things — runs `git remote get-url origin` *and* regex-extracts the `owner/repo` slug from the remote URL via `re.search(r"github\.com[:/](?P<repo>[^/]+/[^/.]+(?:-[^/.]*)?)", remote)`. Task 2/3's `SourceRepository.detect_github_remote(repo_root)` only does the first part (raw `git remote get-url origin` output) — the regex extraction is pure string processing with no I/O, so it belongs in `domain/collection.py`, not the port. **Add this to Task 1** as `extract_github_repo(remote_url: str) -> str` (verbatim regex + `.removesuffix(".git")`, returns `""` on no match) — this was underspecified in the initial task split above; the implementer must add this pure function to `domain/collection.py` in Task 1 (with its own tests: matches `git@github.com:org/repo.git`, matches `https://github.com/org/repo`, returns `""` for non-GitHub remotes or empty string) before Task 4 can call it. `CollectionService.collect_issues` calls `extract_github_repo(self.source_repository.detect_github_remote(repo_root))`.

**`collect_code_evidence` and `collect_git_facts` — exact build steps (verbatim from legacy lines 1024-1125):** see full block in the brief above (lines 1024-1124 read in full at the start of this task). Ported as:
```python
def collect_code_evidence(self, config: dict[str, Any], repo_root: Path) -> Path:
    manifest_path = Path(config["paths"]["code_evidence_manifest"])
    evidence = config.get("evidence_sources", {})
    root = Path(evidence["root"]) if evidence.get("root") else None
    files: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []

    def resolve(rel: str) -> Path:
        return (root / rel) if root else Path(rel)

    def add_code_file(path: Path, evidence_type: str) -> str:
        if not path.exists() or not path.is_file():
            return ""
        text = self.evidence_repository.read_text(path)
        files.append({
            "path": path.resolve().as_posix(), "type": evidence_type,
            "sha256": self.evidence_repository.hash_file(path),
            "excerpt": clean_markdown_text(text[:900]),
        })
        return text

    dependency_manifest = ""
    for entry in evidence.get("files", []):
        text = add_code_file(resolve(entry.get("path", "")), entry.get("type", "evidence"))
        if entry.get("type", "").endswith("dependency_manifest"):
            dependency_manifest = text

    for dependency in evidence.get("dependency_tokens", []):
        if dependency.lower() in dependency_manifest.lower():
            facts.append({
                "classification": "confirmado",
                "claim": f"El proyecto declara la dependencia `{dependency}`.",
                "source": "dependency_manifest",
            })

    source_tokens = evidence.get("source_tokens", [])
    for glob_entry in evidence.get("code_globs", []):
        if not root:
            break
        limit = int(glob_entry.get("limit", 120))
        matched = self.source_repository.glob_pattern(root, glob_entry.get("glob", ""))
        for path in matched[:limit]:
            if not path.is_file():
                continue
            text = add_code_file(path, glob_entry.get("type", "source"))
            lowered = text.lower()
            for token_entry in source_tokens:
                token = token_entry.get("token", "").lower()
                if token and token in lowered:
                    facts.append({
                        "classification": "confirmado",
                        "claim": f"Se detectó uso de {token_entry.get('label', token)} en el código.",
                        "source": path.resolve().as_posix(),
                    })
                    break

    if root and evidence.get("git_log", False):
        facts.extend(self._collect_git_facts(root, repo_root))

    manifest = {
        "schema": 1, "root": root.resolve().as_posix() if root else "",
        "file_count": len(files), "files": files, "facts": dedupe_facts(facts),
    }
    self.evidence_repository.write_manifest(manifest_path, manifest)
    return manifest_path


def _collect_git_facts(self, path: Path, repo_root: Path) -> list[dict[str, Any]]:
    stdout = self.source_repository.run_git_log(path, repo_root)
    if stdout is None:
        return [{
            "classification": "pendiente",
            "claim": "No se pudo obtener git log para la app móvil.",
            "source": "git",
        }]
    facts: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if line.strip():
            facts.append({
                "classification": "confirmado",
                "claim": f"Commit relacionado con app móvil: {line.strip()}",
                "source": "git log",
            })
    return facts
```

**Note on `_as_posix(root)` for the `"root"` manifest field:** legacy's `_as_posix(path) = path.resolve().as_posix()` — ported the same way as Task 4's traceability paths in Slice 4 (`path.resolve().as_posix()` called directly in the service, not through a port method).

**`repo_root` parameter note:** `collect_issues` doesn't actually need `repo_root` for the `gh` call itself (only `_detect_github_repo`/`detect_github_remote` does, via `cwd=repo_root`), but it does need it to call `detect_github_remote`. Both `collect_issues` and `collect_code_evidence` take `repo_root: Path` as an explicit parameter per Design decision 4 — `collect_sources` does not need it (no git/gh calls in `collect_sources`).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_collection_service.py
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from docs.application.collection import CollectionService
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def service() -> CollectionService:
    return CollectionService(FilesystemSourceRepository(), JsonEvidenceRepository())


def _config(tmp_path: Path, **overrides) -> dict[str, Any]:
    context_dir = tmp_path / "context"
    context_dir.mkdir()
    config: dict[str, Any] = {
        "paths": {
            "context_dir": str(context_dir),
            "source_manifest": str(tmp_path / "source-manifest.json"),
            "issues_manifest": str(tmp_path / "issues-manifest.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence-manifest.json"),
        },
        "evidence_sources": {},
        "privacy": {},
        "project": {},
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


# --- collect_sources ---

def test_collect_sources_includes_approved_context_md_files(tmp_path: Path, service):
    config = _config(tmp_path)
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "scope.md").write_text("Alcance del proyecto.")
    (context_dir / "_draft.md").write_text("borrador")
    (context_dir / "index.md").write_text("indice")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["source_count"] == 1
    assert manifest["sources"][0]["type"] == "approved_context"
    assert manifest["sources"][0]["classification"] == "confirmado"


def test_collect_sources_includes_manual_dir_when_present(tmp_path: Path, service):
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    (manual_dir / "norma.md").write_text("Norma institucional.")
    config = _config(tmp_path, paths={"manual_dir": str(manual_dir)})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    types = [s["type"] for s in manifest["sources"]]
    assert "institutional_manual" in types


def test_collect_sources_skips_missing_manual_dir(tmp_path: Path, service):
    config = _config(tmp_path, paths={"manual_dir": str(tmp_path / "missing")})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["sources"] == []


def test_collect_sources_includes_evidence_files_with_use_and_type(tmp_path: Path, service):
    evidence_root = tmp_path / "evidence_root"
    evidence_root.mkdir()
    (evidence_root / "data.json").write_text("{}")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "files": [{"path": "data.json", "type": "tech_doc", "use": "evidencia secundaria"}],
        },
    )
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entry = next(s for s in manifest["sources"] if s["type"] == "tech_doc")
    assert entry["use"] == "evidencia secundaria"


def test_collect_sources_includes_cover_template_and_example_pdf(tmp_path: Path, service):
    template = tmp_path / "template.docx"
    template.write_bytes(b"PK\x03\x04fake")
    example = tmp_path / "example.pdf"
    example.write_bytes(b"%PDF-1.4 fake")
    config = _config(tmp_path, paths={"template_docx": str(template), "example_pdf": str(example)})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    types = {s["type"] for s in manifest["sources"]}
    assert types == {"cover_template", "example_reference"}
    classifications = {s["type"]: s["classification"] for s in manifest["sources"]}
    assert classifications["cover_template"] == "confirmado"
    assert classifications["example_reference"] == "fuera_de_alcance"


def test_collect_sources_injects_contradiction_fact_when_term_found(tmp_path: Path, service):
    context_dir = Path(_config(tmp_path)["paths"]["context_dir"])
    config = _config(
        tmp_path,
        evidence_sources={"scope_contradiction_terms": ["fuera de alcance original"]},
    )
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "scope.md").write_text("Esto está Fuera De Alcance Original, ojo.")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any(f["classification"] == "contradiccion" for f in manifest["facts"])


def test_collect_sources_injects_sensitive_field_fact_when_table_row_present(tmp_path: Path, service):
    config = _config(tmp_path, privacy={"sensitive_context_fields": ["DNI"]})
    context_dir = Path(config["paths"]["context_dir"])
    (context_dir / "datos.md").write_text("| Campo | Valor |\n| **DNI** | 12345678 |\n")
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any(f["classification"] == "dato_sensible" and "DNI" in f["claim"] for f in manifest["facts"])


def test_collect_sources_carries_scope_policy(tmp_path: Path, service):
    config = _config(tmp_path, project={"scope_policy": "alcance institucional"})
    path = service.collect_sources(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["policy"] == "alcance institucional"


# --- collect_issues ---

def test_collect_issues_raises_when_gh_not_available(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = _config(tmp_path)
    with pytest.raises(RuntimeError, match="GitHub CLI `gh` no está disponible"):
        service.collect_issues(config, repo_root=tmp_path)


def test_collect_issues_raises_when_repo_not_detected(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            raise OSError("no remote")
        raise AssertionError("should not call gh before repo is detected")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    with pytest.raises(RuntimeError, match="No se pudo detectar el repositorio GitHub"):
        service.collect_issues(config, repo_root=tmp_path)


def test_collect_issues_writes_manifest_with_parsed_issues(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")
        return subprocess.CompletedProcess(
            args, 0, stdout='[{"number": 1, "title": "Bug", "state": "OPEN", "url": "u", "labels": []}]', stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    path = service.collect_issues(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["repo"] == "org/repo"
    assert manifest["issue_count"] == 1
    assert manifest["issues"][0]["classification"] == "confirmado"


def test_collect_issues_propagates_called_process_error_from_gh(tmp_path: Path, service, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gh")

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "remote"]:
            return subprocess.CompletedProcess(args, 0, stdout="git@github.com:org/repo.git\n", stderr="")
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        service.collect_issues(config, repo_root=tmp_path)


# --- collect_code_evidence ---

def test_collect_code_evidence_empty_when_no_evidence_sources(tmp_path: Path, service):
    config = _config(tmp_path)
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["files"] == []
    assert manifest["facts"] == []
    assert manifest["root"] == ""


def test_collect_code_evidence_detects_dependency_token(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "pyproject.toml").write_text('dependencies = ["fastapi"]')
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "files": [{"path": "pyproject.toml", "type": "python_dependency_manifest"}],
            "dependency_tokens": ["fastapi"],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert any("fastapi" in f["claim"] for f in manifest["facts"])


def test_collect_code_evidence_globs_code_files_and_detects_source_token(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "main.py").write_text("import fastapi\napp = fastapi.FastAPI()")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "code_globs": [{"glob": "*.py", "type": "source", "limit": 10}],
            "source_tokens": [{"token": "fastapi", "label": "FastAPI"}],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 1
    assert any("FastAPI" in f["claim"] for f in manifest["facts"])


def test_collect_code_evidence_respects_glob_limit(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    for i in range(5):
        (evidence_root / f"f{i}.py").write_text("x = 1")
    config = _config(
        tmp_path,
        evidence_sources={"root": str(evidence_root), "code_globs": [{"glob": "*.py", "limit": 2}]},
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2


def test_collect_code_evidence_skips_git_log_when_flag_false(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fail_run(*args, **kwargs):
        raise AssertionError("git should not be called when git_log is False")

    monkeypatch.setattr("subprocess.run", fail_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": False})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["facts"] == []


def test_collect_code_evidence_adds_git_log_facts_when_enabled(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="abc123 fix bug\ndef456 add feature\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": True})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["facts"]) == 2
    assert all(f["source"] == "git log" for f in manifest["facts"])


def test_collect_code_evidence_falls_back_to_pendiente_fact_on_git_failure(tmp_path: Path, service, monkeypatch):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()

    def fake_run(args, **kwargs):
        raise OSError("git not available")

    monkeypatch.setattr("subprocess.run", fake_run)
    config = _config(tmp_path, evidence_sources={"root": str(evidence_root), "git_log": True})
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["facts"] == [
        {
            "classification": "pendiente",
            "claim": "No se pudo obtener git log para la app móvil.",
            "source": "git",
        }
    ]


def test_collect_code_evidence_dedupes_facts(tmp_path: Path, service):
    evidence_root = tmp_path / "code"
    evidence_root.mkdir()
    (evidence_root / "a.py").write_text("import fastapi")
    (evidence_root / "b.py").write_text("import fastapi")
    config = _config(
        tmp_path,
        evidence_sources={
            "root": str(evidence_root),
            "code_globs": [{"glob": "*.py", "limit": 10}],
            "source_tokens": [{"token": "fastapi", "label": "FastAPI"}],
        },
    )
    path = service.collect_code_evidence(config, repo_root=tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claims = [f["claim"] for f in manifest["facts"] if "FastAPI" in f["claim"]]
    # two files both trigger the same token -> distinct sources, NOT deduped to one
    assert len(claims) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_collection_service.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.application.collection`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/collection.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.collection import classify_source, dedupe_facts, extract_github_repo, parse_gh_issues
from docs.domain.markdown_text import clean_markdown_text
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.source_repository import SourceRepository

_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}
_SOURCE_EXCERPT_LENGTH = 900
_CODE_EXCERPT_LENGTH = 900


class CollectionService:
    def __init__(self, source_repository: SourceRepository, evidence_repository: EvidenceRepository) -> None:
        self.source_repository = source_repository
        self.evidence_repository = evidence_repository

    def collect_sources(self, config: dict[str, Any]) -> Path:
        manifest_path = Path(config["paths"]["source_manifest"])
        sources: list[dict[str, Any]] = []

        def add_file(path: Path, source_type: str, use: str) -> None:
            if not path.exists() or not path.is_file():
                return
            text = ""
            if path.suffix.lower() in _TEXT_SUFFIXES:
                text = self.evidence_repository.read_text(path)
            sources.append(
                {
                    "path": path.resolve().as_posix(),
                    "type": source_type,
                    "use": use,
                    "classification": classify_source(source_type),
                    "sha256": self.evidence_repository.hash_file(path),
                    "excerpt": clean_markdown_text(text[:_SOURCE_EXCERPT_LENGTH]) if text else "",
                }
            )

        context_dir = Path(config["paths"]["context_dir"])
        for path in self.source_repository.glob_markdown(context_dir):
            if path.name.startswith("_") or path.name == "index.md":
                continue
            add_file(path, "approved_context", "contexto aprobado del documento")

        manual_dir = config["paths"].get("manual_dir")
        if manual_dir and Path(manual_dir).exists():
            for path in self.source_repository.glob_markdown(Path(manual_dir)):
                add_file(path, "institutional_manual", "norma documental obligatoria")

        evidence = config.get("evidence_sources", {})
        evidence_root = Path(evidence["root"]) if evidence.get("root") else None
        for entry in evidence.get("files", []):
            rel = entry.get("path", "")
            target = (evidence_root / rel) if evidence_root else Path(rel)
            add_file(target, entry.get("type", "evidence"), entry.get("use", "evidencia técnica secundaria"))

        if config["paths"].get("template_docx"):
            add_file(
                Path(config["paths"]["template_docx"]), "cover_template", "plantilla de portada reutilizable"
            )
        if config["paths"].get("example_pdf"):
            add_file(
                Path(config["paths"]["example_pdf"]),
                "example_reference",
                "referencia estructural, no fuente de contenido",
            )

        # Legacy calls load_context(config) twice (once per check below) for the
        # identical result. read_context_texts is referentially transparent over
        # the same config, so this service computes it once and reuses it —
        # not a behavior change, just removing a verbatim duplicate call.
        context_texts = self.source_repository.read_context_texts(context_dir)
        context_text = "\n".join(context_texts.values()).lower()

        facts: list[dict[str, Any]] = list(config.get("collect_facts_seed", []))
        contradiction_terms = [term.lower() for term in evidence.get("scope_contradiction_terms", [])]
        if contradiction_terms and any(term in context_text for term in contradiction_terms):
            facts.append(
                {
                    "classification": "contradiccion",
                    "claim": (
                        "El contexto menciona términos fuera del alcance declarado; "
                        "resolver con evidencia o delimitar."
                    ),
                    "source": "context",
                }
            )
        import re

        for field in config.get("privacy", {}).get("sensitive_context_fields", []):
            if re.search(
                rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|",
                "\n".join(context_texts.values()),
                flags=re.IGNORECASE,
            ):
                facts.append(
                    {
                        "classification": "dato_sensible",
                        "claim": (
                            f"El contexto aprobado contiene el campo sensible `{field}`; "
                            "no debe pasar al cuerpo sin instrucción explícita."
                        ),
                        "source": "tesina/context",
                    }
                )

        manifest = {
            "schema": 1,
            "policy": config.get("project", {}).get("scope_policy", ""),
            "source_count": len(sources),
            "sources": sources,
            "facts": facts,
        }
        self.evidence_repository.write_manifest(manifest_path, manifest)
        return manifest_path

    def collect_issues(self, config: dict[str, Any], repo_root: Path) -> Path:
        gh = self.source_repository.find_executable("gh")
        if not gh:
            raise RuntimeError("GitHub CLI `gh` no está disponible. Instálalo o exporta issues a JSON.")
        remote = self.source_repository.detect_github_remote(repo_root)
        repo = extract_github_repo(remote)
        if not repo:
            raise RuntimeError("No se pudo detectar el repositorio GitHub desde `git remote get-url origin`.")
        raw = self.source_repository.run_gh_issue_list(gh, repo)
        issues = parse_gh_issues(raw)
        manifest_path = Path(config["paths"]["issues_manifest"])
        payload = {"schema": 1, "repo": repo, "issue_count": len(issues), "issues": issues}
        self.evidence_repository.write_manifest(manifest_path, payload)
        return manifest_path

    def collect_code_evidence(self, config: dict[str, Any], repo_root: Path) -> Path:
        manifest_path = Path(config["paths"]["code_evidence_manifest"])
        evidence = config.get("evidence_sources", {})
        root = Path(evidence["root"]) if evidence.get("root") else None
        files: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []

        def resolve(rel: str) -> Path:
            return (root / rel) if root else Path(rel)

        def add_code_file(path: Path, evidence_type: str) -> str:
            if not path.exists() or not path.is_file():
                return ""
            text = self.evidence_repository.read_text(path)
            files.append(
                {
                    "path": path.resolve().as_posix(),
                    "type": evidence_type,
                    "sha256": self.evidence_repository.hash_file(path),
                    "excerpt": clean_markdown_text(text[:_CODE_EXCERPT_LENGTH]),
                }
            )
            return text

        dependency_manifest = ""
        for entry in evidence.get("files", []):
            text = add_code_file(resolve(entry.get("path", "")), entry.get("type", "evidence"))
            if entry.get("type", "").endswith("dependency_manifest"):
                dependency_manifest = text

        for dependency in evidence.get("dependency_tokens", []):
            if dependency.lower() in dependency_manifest.lower():
                facts.append(
                    {
                        "classification": "confirmado",
                        "claim": f"El proyecto declara la dependencia `{dependency}`.",
                        "source": "dependency_manifest",
                    }
                )

        source_tokens = evidence.get("source_tokens", [])
        for glob_entry in evidence.get("code_globs", []):
            if not root:
                break
            limit = int(glob_entry.get("limit", 120))
            matched = self.source_repository.glob_pattern(root, glob_entry.get("glob", ""))
            for path in matched[:limit]:
                if not path.is_file():
                    continue
                text = add_code_file(path, glob_entry.get("type", "source"))
                lowered = text.lower()
                for token_entry in source_tokens:
                    token = token_entry.get("token", "").lower()
                    if token and token in lowered:
                        facts.append(
                            {
                                "classification": "confirmado",
                                "claim": f"Se detectó uso de {token_entry.get('label', token)} en el código.",
                                "source": path.resolve().as_posix(),
                            }
                        )
                        break

        if root and evidence.get("git_log", False):
            facts.extend(self._collect_git_facts(root, repo_root))

        manifest = {
            "schema": 1,
            "root": root.resolve().as_posix() if root else "",
            "file_count": len(files),
            "files": files,
            "facts": dedupe_facts(facts),
        }
        self.evidence_repository.write_manifest(manifest_path, manifest)
        return manifest_path

    def _collect_git_facts(self, path: Path, repo_root: Path) -> list[dict[str, Any]]:
        stdout = self.source_repository.run_git_log(path, repo_root)
        if stdout is None:
            return [
                {
                    "classification": "pendiente",
                    "claim": "No se pudo obtener git log para la app móvil.",
                    "source": "git",
                }
            ]
        facts: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            if line.strip():
                facts.append(
                    {
                        "classification": "confirmado",
                        "claim": f"Commit relacionado con app móvil: {line.strip()}",
                        "source": "git log",
                    }
                )
        return facts
```

Also add to `src/docs/domain/collection.py` (Task 1 amendment — see correction note above):

```python
import re as _re

_GITHUB_REMOTE_RE = _re.compile(r"github\.com[:/](?P<repo>[^/]+/[^/.]+(?:-[^/.]*)?)")


def extract_github_repo(remote_url: str) -> str:
    match = _GITHUB_REMOTE_RE.search(remote_url)
    if not match:
        return ""
    return match.group("repo").removesuffix(".git")
```

(Implementer note: place this in Task 1's file/tests, not as a separate task — it is pure and belongs with `classify_source`/`parse_gh_issues`/`dedupe_facts`. Add corresponding tests to `tests/unit/domain/test_collection.py`: SSH remote, HTTPS remote, non-GitHub remote returns `""`, empty string returns `""`.)

**Test expectations note:** integration tests pin manifest *content* (classification values, fact injection conditions, file counts, error messages) via real `FilesystemSourceRepository` + `JsonEvidenceRepository`, with `subprocess.run`/`shutil.which` monkeypatched at the boundary — no test shells out to real `gh`/`git` binaries, consistent with this project's existing test convention of using `tmp_path` and avoiding real external tool dependencies in CI.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_collection_service.py -v`
Expected: PASS (21 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/collection.py src/docs/domain/collection.py tests/integration/test_collection_service.py tests/unit/domain/test_collection.py
git commit -m "feat(application): add CollectionService replacing legacy collect_sources/collect_issues/collect_code_evidence"
```

---

## Full suite check (run after Task 4)

```bash
uv run pytest -W error -q
```

Expected: all tests from Slices 1-6 plus this slice's 11 (Task 1, plus ~4 more for `extract_github_repo` added during Task 4 = 15) + 13 (Task 3) + 21 (Task 4) new tests pass, zero warnings.

---

## Out of scope for this slice

- **`load_context_index`, `load_context_for`** (legacy lines 724, 734) — distinct functions from `load_context`, not called by any function in lines 885-1156, not ported here.
- **`resolve_executable`'s bundled-runtime and fallback-path branches** (`CODEX_RUNTIME_BIN`, `PANDOC_FALLBACKS`, `LIBREOFFICE_FALLBACKS`, `POPPLER_PDFINFO_FALLBACKS`, `POPPLER_PDFTOPPM_FALLBACKS`) — only `shutil.which(name)` is ported (Design decision 2), since `collect_issues` is the only in-scope caller and it always passes `fallbacks=[]`. The fuller version is deferred to whichever slice ports `build_docx`/QA tooling (Slices 10-12 per `roadmap.md`).
- **`format_audit_docx`, `build_docx`, and everything past line 1156** — untouched by this slice, confirmed not referenced by any task above. `resolve_executable`'s non-`gh` call sites (lines 2217-3000) are all inside or downstream of these functions and remain unported.
- **`contradiction_terms`/`sensitive_context_fields` fact-injection logic** — **NOT deferred.** Unlike the brief's contingency for carving this out, Design decision 3 found a clean port path (`SourceRepository.read_context_texts`, a thin glob-and-read method scoped to this slice's new port) without needing `ContextRepository` or any parallel `load_context` helper. This logic is fully ported in Task 4 as part of `collect_sources`.
- **A typed config/`ProjectConfig` Pydantic model** — still deferred, per Slice 4's Self-Review item 2 and this plan's Global Constraints; every new service method takes raw `dict[str, Any]`, matching `EvidenceService.build_rules`'s exact precedent.
- **A concrete source for `repo_root`** (e.g. wiring it from a CLI argument or `Workspace`) — `collect_issues`/`collect_code_evidence` accept `repo_root: Path` as an explicit parameter (Design decision 4), but nothing in this slice decides *where* a caller gets that path from at runtime; that wiring belongs to the eventual CLI slice (Slice 15 per `roadmap.md`), the same deferral pattern as `EvidenceService.build_rules` taking a raw `config` dict whose assembly is also CLI-slice work.
- **`load_context_index`-style caching or memoization of `read_context_texts`** — not introduced; each call re-globs and re-reads, matching legacy's behavior of calling `load_context` fresh each time (even though this slice's service collapses legacy's *duplicate* call into one, per the documented exception above — it does not introduce caching across separate `collect_sources` invocations).
