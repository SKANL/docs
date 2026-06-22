# Slice 4 — Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port legacy `build_rules` — the manifest-writing / file-hashing logic deferred out of Slice 3 — into a pure domain function plus a hexagonal port/adapter/service triplet. `build_rules` hashes the manual-source markdown files and traceability PDFs/extracted files, builds a JSON manifest (`manual-rules.json`) describing them plus the document's normative config, and writes it to disk only if its content (modulo `generated_at`) actually changed. This slice splits that single I/O-entangled legacy function into: a pure domain function that decides *what the manifest should contain* given already-computed file facts (`domain/evidence.py`), an `EvidenceRepository` port describing the I/O the manifest needs (file hashing, file stat, manifest read/write), a `JsonEvidenceRepository` adapter doing the actual filesystem work, and an `EvidenceService.build_rules` that wires domain decision to port I/O — replacing legacy `build_rules` end-to-end.

**Architecture:** Pragmatic hexagonal, same shape as Slices 1–3. `domain/evidence.py` is pure: no `Path.read_text`, no `hashlib`, no `Path.exists()`. It accepts plain dicts/dataclasses describing files that already exist (path, hash, size, headings, excerpt) and assembles the manifest dict — it never touches the filesystem itself. `domain/ports/evidence_repository.py` declares the `EvidenceRepository` Protocol the application layer depends on. `infrastructure/persistence/json_evidence_repository.py` implements that Protocol with real `pathlib`/`hashlib`/`json` I/O, reusing `domain/markdown_text.py`'s `extract_markdown_headings`/`clean_markdown_text` for the per-file excerpt/heading computation (no new text-processing logic). `application/evidence.py` holds `EvidenceService`, which composes the port (to gather file facts and write the manifest) with the domain function (to build manifest content) — mirroring `DocumentService`'s composition of `DocumentRepository` + plain domain calls. Nothing in `domain/evidence.py` imports from `application`, `infrastructure`, or `cli`.

**Tech Stack:** Python ≥3.11, Pydantic v2 (no new models needed — manifest is a plain `dict`, matching legacy's untyped JSON shape), `hashlib.sha256` (verbatim legacy algorithm — confirmed below), pytest with `tmp_path` for adapter/integration tests (no test touches the real legacy file tree).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. `domain/evidence.py` imports nothing from `application`, `infrastructure`, or `cli`.
- **Hash algorithm parity, confirmed from legacy source:** `sha256_file(path) = hashlib.sha256(path.read_bytes()).hexdigest()`; `sha256_json(value) = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()`. Both ported verbatim in Task 2 (the adapter) — `sort_keys=True` and `ensure_ascii=False` on the JSON-hash path are load-bearing for parity and must not be dropped.
- **Manifest write-skip optimization, confirmed from legacy source:** legacy `write_json_manifest(path, payload)` reads the existing manifest (if any), compares it to the new payload with `generated_at` stripped from both sides (via `strip_generated_at`, which recursively drops the `generated_at` key from dicts), and skips the write entirely if they're equal — only then does it stamp a fresh `generated_at` and write. This means `generated_at` is **not** part of the domain decision (it's a side effect of the I/O layer, written only on an actual content change) and is **not** modeled by `domain/evidence.py` at all — Task 4 (the adapter's write path) reproduces the skip-if-unchanged behavior exactly, stamping `generated_at` only when it decides to write.
- **Verbatim parity over modeling purity.** Every field name, ordering, and code path in the manifest dict is copied from legacy `build_rules`. Where legacy has a quirk (e.g. `traceability` checks `path.exists()` for `manual_pdf`/`example_pdf` but unconditionally globs `extracted_dir` only after its own separate `.exists()` check; `manual_pdf`/`example_pdf` are read from `config["paths"].get(key, "")` — an **empty string** path, when missing — and `Path("").exists()` is `False`, so the entry is simply skipped, not an error), it is preserved and called out in a code comment — never "fixed" silently.
- The manifest is a plain `dict[str, Any]`, not a typed Pydantic model — legacy never gives it a schema beyond `"schema": 1`, and the only structural readers of `manual-rules.json` today are `review_rules` (Slice 3, which only reads `manifest_exists: bool, manifest_size: int` — never the manifest body) and legacy's `doctor`/CLI checks (out of scope; not ported in this slice). No task in this slice needs a typed manifest model; introducing one now would be speculative.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/domain/evidence.py` — `ManualFileFact`, `TraceabilityFact`, `build_manifest`.
- `src/docs/domain/ports/evidence_repository.py` — `EvidenceRepository` Protocol.
- `src/docs/infrastructure/persistence/json_evidence_repository.py` — `JsonEvidenceRepository`.
- `src/docs/application/evidence.py` — `EvidenceService`.
- `tests/unit/domain/test_evidence.py`
- `tests/unit/infrastructure/test_json_evidence_repository.py`
- `tests/integration/test_evidence_service.py`

---

### Task 1: Pure domain manifest builder

**Files:**
- Create: `src/docs/domain/evidence.py`
- Test: `tests/unit/domain/test_evidence.py`

**Interfaces:**
- Consumes: nothing from other domain modules in this slice (intentionally self-contained — see note below).
- Produces:
  - `ManualFileFact` frozen dataclass: `path: str, name: str, sha256: str, headings: list[str], excerpt: str`.
  - `TraceabilityFact` frozen dataclass: `path: str, type: str, sha256: str, size: int`.
  - `build_manifest(manual_files: list[ManualFileFact], traceability: list[TraceabilityFact], advisor_overrides: list[dict], draft_mode: dict, strict_mode: dict, preliminaries: dict, format: dict, apa7: dict, privacy: dict, section_contracts: dict[str, dict], contract_hashes: dict[str, str]) -> dict[str, Any]`

**Why this function takes pre-computed facts, not a `Template` or file paths:** legacy `build_rules(config)` reads `config["paths"]["manual_dir"]`/`extracted_dir`/`manual_pdf`/`example_pdf` directly and does the hashing/globbing/file-reading itself. This slice's `build_manifest` is the pure decision core only — "given these files already exist with these hashes/headings/excerpts, and this config data, assemble the manifest dict." The adapter (Task 2/3) does the actual globbing, reading, and hashing, and calls `build_manifest` with the results. This mirrors Slice 3's split of `review_rules` (pure) from "the caller resolves `manifest_exists`/`manifest_size`" (I/O, deferred). `build_manifest` does not need `Template`, `SectionContract`, or any other Slice 1–3 domain type — legacy reads `section_contracts`/`advisor_overrides`/etc. as raw dicts off `config`, and `build_manifest` does the same (`section_contracts: dict[str, dict]`) rather than depending on `domain.models.template.SectionContract`, since legacy itself never validates these sub-blocks before manifesting them — it just round-trips whatever dict shape is in `config`. `contract_hashes` is passed in pre-computed (not computed inside `build_manifest`) because computing it requires `sha256_json`, which is I/O-adjacent (depends on `hashlib`+`json` the same way file hashing does) and belongs in the adapter alongside `sha256_file`, not duplicated as a second hashing utility inside `domain/`.

**Exact manifest shape (verbatim from legacy, field order as listed — dict key order is not semantically significant for JSON but is preserved here for readability/diffability with legacy output):**

```python
{
    "schema": 1,
    "policy": {
        "normative_source": "tesina/guides/manual-estadia-tic",
        "pdf_and_extracted_use": "rules_traceability_only",
        "apa_style": "APA 7",
        "advisor_overrides": advisor_overrides,
        "draft_mode": draft_mode,
        "strict_mode": strict_mode,
    },
    "manual_files": [ {"path": f.path, "name": f.name, "sha256": f.sha256, "headings": f.headings, "excerpt": f.excerpt} for f in manual_files ],
    "traceability": [ {"path": t.path, "type": t.type, "sha256": t.sha256, "size": t.size} for t in traceability ],
    "preliminaries": preliminaries,
    "format": format,
    "advisor_overrides": advisor_overrides,
    "apa7": apa7,
    "privacy": privacy,
    "section_contracts": section_contracts,
    "contract_hashes": contract_hashes,
}
```

Note the verbatim legacy duplication: `advisor_overrides` appears both nested under `policy` and at the top level. This is real legacy behavior (`tesina_harness.py` lines ~485-505), not a bug introduced by this port — preserve it, do not deduplicate.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_evidence.py
from docs.domain.evidence import ManualFileFact, TraceabilityFact, build_manifest


def _manual_file(**overrides) -> ManualFileFact:
    defaults = dict(
        path="/repo/manual/00-intro.md",
        name="00-intro.md",
        sha256="a" * 64,
        headings=["Introducción"],
        excerpt="Texto de ejemplo.",
    )
    defaults.update(overrides)
    return ManualFileFact(**defaults)


def _traceability(**overrides) -> TraceabilityFact:
    defaults = dict(path="/repo/manual.pdf", type="institutional_pdf", sha256="b" * 64, size=1024)
    defaults.update(overrides)
    return TraceabilityFact(**defaults)


def _call(**overrides):
    defaults = dict(
        manual_files=[],
        traceability=[],
        advisor_overrides=[],
        draft_mode={},
        strict_mode={},
        preliminaries={},
        format={},
        apa7={},
        privacy={},
        section_contracts={},
        contract_hashes={},
    )
    defaults.update(overrides)
    return build_manifest(**defaults)


def test_build_manifest_schema_and_fixed_policy_fields():
    manifest = _call()
    assert manifest["schema"] == 1
    assert manifest["policy"]["normative_source"] == "tesina/guides/manual-estadia-tic"
    assert manifest["policy"]["pdf_and_extracted_use"] == "rules_traceability_only"
    assert manifest["policy"]["apa_style"] == "APA 7"


def test_build_manifest_policy_carries_advisor_overrides_and_modes():
    overrides = [{"id": "x", "status": "active"}]
    draft = {"allow_pending": True}
    strict = {"allow_pending": False}
    manifest = _call(advisor_overrides=overrides, draft_mode=draft, strict_mode=strict)
    assert manifest["policy"]["advisor_overrides"] == overrides
    assert manifest["policy"]["draft_mode"] == draft
    assert manifest["policy"]["strict_mode"] == strict


def test_build_manifest_advisor_overrides_duplicated_at_top_level_verbatim_legacy():
    overrides = [{"id": "x", "status": "active"}]
    manifest = _call(advisor_overrides=overrides)
    assert manifest["advisor_overrides"] == overrides
    assert manifest["policy"]["advisor_overrides"] == overrides


def test_build_manifest_manual_files_serialized_from_facts():
    fact = _manual_file()
    manifest = _call(manual_files=[fact])
    assert manifest["manual_files"] == [
        {
            "path": fact.path,
            "name": fact.name,
            "sha256": fact.sha256,
            "headings": fact.headings,
            "excerpt": fact.excerpt,
        }
    ]


def test_build_manifest_traceability_serialized_from_facts():
    fact = _traceability()
    manifest = _call(traceability=[fact])
    assert manifest["traceability"] == [
        {"path": fact.path, "type": fact.type, "sha256": fact.sha256, "size": fact.size}
    ]


def test_build_manifest_preserves_manual_files_order():
    first = _manual_file(name="00-intro.md")
    second = _manual_file(name="01-objetivos.md")
    manifest = _call(manual_files=[first, second])
    assert [f["name"] for f in manifest["manual_files"]] == ["00-intro.md", "01-objetivos.md"]


def test_build_manifest_passes_through_format_apa7_privacy_preliminaries():
    manifest = _call(
        preliminaries={"roman_pagination": {"enabled": True}},
        format={"page_margins_cm": {}},
        apa7={"enabled": True},
        privacy={"redact": True},
    )
    assert manifest["preliminaries"] == {"roman_pagination": {"enabled": True}}
    assert manifest["format"] == {"page_margins_cm": {}}
    assert manifest["apa7"] == {"enabled": True}
    assert manifest["privacy"] == {"redact": True}


def test_build_manifest_section_contracts_and_hashes_passed_through():
    contracts = {"intro": {"title": "Introducción"}}
    hashes = {"intro": "c" * 64}
    manifest = _call(section_contracts=contracts, contract_hashes=hashes)
    assert manifest["section_contracts"] == contracts
    assert manifest["contract_hashes"] == hashes


def test_build_manifest_empty_inputs_produce_empty_lists_and_dicts():
    manifest = _call()
    assert manifest["manual_files"] == []
    assert manifest["traceability"] == []
    assert manifest["section_contracts"] == {}
    assert manifest["contract_hashes"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_evidence.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.evidence`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/evidence.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManualFileFact:
    path: str
    name: str
    sha256: str
    headings: list[str]
    excerpt: str


@dataclass(frozen=True)
class TraceabilityFact:
    path: str
    type: str
    sha256: str
    size: int


def build_manifest(
    manual_files: list[ManualFileFact],
    traceability: list[TraceabilityFact],
    advisor_overrides: list[dict],
    draft_mode: dict,
    strict_mode: dict,
    preliminaries: dict,
    format: dict,
    apa7: dict,
    privacy: dict,
    section_contracts: dict[str, dict],
    contract_hashes: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema": 1,
        "policy": {
            "normative_source": "tesina/guides/manual-estadia-tic",
            "pdf_and_extracted_use": "rules_traceability_only",
            "apa_style": "APA 7",
            # Legacy quirk (intentional, not a bug): advisor_overrides is duplicated
            # both here and at the manifest's top level (see below). Preserve as-is.
            "advisor_overrides": advisor_overrides,
            "draft_mode": draft_mode,
            "strict_mode": strict_mode,
        },
        "manual_files": [
            {
                "path": fact.path,
                "name": fact.name,
                "sha256": fact.sha256,
                "headings": fact.headings,
                "excerpt": fact.excerpt,
            }
            for fact in manual_files
        ],
        "traceability": [
            {"path": fact.path, "type": fact.type, "sha256": fact.sha256, "size": fact.size}
            for fact in traceability
        ],
        "preliminaries": preliminaries,
        "format": format,
        "advisor_overrides": advisor_overrides,
        "apa7": apa7,
        "privacy": privacy,
        "section_contracts": section_contracts,
        "contract_hashes": contract_hashes,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_evidence.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/evidence.py tests/unit/domain/test_evidence.py
git commit -m "feat(domain): add build_manifest pure manifest assembly for evidence/rules"
```

---

### Task 2: EvidenceRepository port

**Files:**
- Create: `src/docs/domain/ports/evidence_repository.py`
- Test: none (a `Protocol` with no behavior has nothing to unit test on its own — verified indirectly by Task 3's adapter conforming to it and Task 4's service using it via duck typing, consistent with how Slice 1's `DocumentRepository` Protocol was introduced in Task 5 of Slice 1 without its own standalone test file).

**Interfaces:**
- Consumes: nothing (pure interface declaration).
- Produces: `EvidenceRepository` Protocol with methods mirroring exactly what `JsonEvidenceRepository` (Task 3) must implement to let `EvidenceService.build_rules` (Task 4) replace legacy `build_rules` end-to-end:
  - `hash_file(path: Path) -> str` — sha256 of file bytes.
  - `hash_json(value: Any) -> str` — sha256 of `json.dumps(value, ensure_ascii=False, sort_keys=True)`.
  - `list_manual_files(manual_dir: Path) -> list[Path]` — sorted `*.md` glob.
  - `read_text(path: Path) -> str` — `errors="replace"` decoded text, for heading/excerpt extraction.
  - `file_exists(path: Path) -> bool`
  - `file_size(path: Path) -> int`
  - `list_traceability_files(extracted_dir: Path) -> list[Path]` — sorted glob of files with `.md`/`.json` suffix (case-insensitive).
  - `read_manifest(path: Path) -> dict[str, Any] | None` — `None` if the file doesn't exist or fails to parse as JSON (legacy's `write_json_manifest` treats invalid JSON the same as absent).
  - `write_manifest(path: Path, payload: dict[str, Any]) -> None` — performs the skip-if-unchanged + `generated_at` stamping behavior described in the Global Constraints; this is the one method that bundles "decide whether to write" with "write," because that decision is itself I/O (reading the existing file) and not a domain concern — see Task 1's note on why `generated_at` isn't part of `build_manifest`.

This Protocol is intentionally a thin "filesystem facts + raw hashing primitives" interface, not a single coarse `build_rules(config) -> Path` method, so the pure parts (sorting, glob filtering by suffix, assembling the manifest dict via `build_manifest`) stay testable without going through the Protocol at all — `EvidenceService` (Task 4) is what actually orchestrates these primitives into the legacy `build_rules` shape.

- [ ] **Step 1: Write the failing test**

This task introduces only a `Protocol` (an interface declaration), which is structural typing with no runtime behavior of its own to assert against — there is nothing to make fail or pass independently of an implementation. Skip directly to Step 3; Task 3's adapter test will be the first test that actually exercises this Protocol's shape (by implementing every method it declares).

- [ ] **Step 2: Run test to verify it fails**

N/A — no test file in this task (see Step 1 rationale).

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/evidence_repository.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class EvidenceRepository(Protocol):
    def hash_file(self, path: Path) -> str: ...
    def hash_json(self, value: Any) -> str: ...
    def list_manual_files(self, manual_dir: Path) -> list[Path]: ...
    def read_text(self, path: Path) -> str: ...
    def file_exists(self, path: Path) -> bool: ...
    def file_size(self, path: Path) -> int: ...
    def list_traceability_files(self, extracted_dir: Path) -> list[Path]: ...
    def read_manifest(self, path: Path) -> dict[str, Any] | None: ...
    def write_manifest(self, path: Path, payload: dict[str, Any]) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

N/A — no test in this task. Sanity-check the module imports cleanly:

Run: `uv run python -c "from docs.domain.ports.evidence_repository import EvidenceRepository; print(EvidenceRepository)"`
Expected: prints the Protocol class, no import error.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/evidence_repository.py
git commit -m "feat(domain): add EvidenceRepository port for manifest/file-hashing I/O"
```

---

### Task 3: JsonEvidenceRepository adapter

**Files:**
- Create: `src/docs/infrastructure/persistence/json_evidence_repository.py`
- Test: `tests/unit/infrastructure/test_json_evidence_repository.py`

**Interfaces:**
- Consumes: `EvidenceRepository` (Task 2, structurally — Python `Protocol`s are not subclassed, just satisfied).
- Produces: `JsonEvidenceRepository` class implementing every method of `EvidenceRepository`.

**Hash algorithm parity (confirmed from `tesina_harness.py` lines 365–374):**
```python
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
```

**Manifest write parity (confirmed from `tesina_harness.py` lines 377–396):**
```python
def write_json_manifest(path: Path, payload: dict[str, Any]) -> None:
    next_payload = dict(payload)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
        if strip_generated_at(existing) == strip_generated_at(next_payload):
            return
    next_payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(next_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
```
`strip_generated_at` recursively removes the `generated_at` key from nested dicts/lists before comparing — `write_manifest` must replicate this exact compare-then-skip-or-stamp-and-write behavior, including writing only when content differs (a no-op write when content is unchanged, even if `path` already exists with stale `generated_at`).

**Traceability file filter parity:** legacy's `extracted_dir` glob is `sorted(extracted_dir.glob("*"))` filtered to `path.is_file() and path.suffix.lower() in {".md", ".json"}` — `list_traceability_files` must apply the same case-insensitive suffix filter and file-only filter, returning sorted paths.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_json_evidence_repository.py
import hashlib
import json
from pathlib import Path

import pytest

from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def repo() -> JsonEvidenceRepository:
    return JsonEvidenceRepository()


def test_hash_file_matches_raw_sha256_of_bytes(tmp_path: Path, repo):
    path = tmp_path / "a.md"
    path.write_bytes(b"hello world")
    assert repo.hash_file(path) == hashlib.sha256(b"hello world").hexdigest()


def test_hash_json_matches_sorted_ensure_ascii_false_dump(repo):
    value = {"b": 1, "a": "café"}
    expected = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert repo.hash_json(value) == expected


def test_list_manual_files_sorted_md_glob(tmp_path: Path, repo):
    (tmp_path / "01-b.md").write_text("b")
    (tmp_path / "00-a.md").write_text("a")
    (tmp_path / "ignore.txt").write_text("x")
    files = repo.list_manual_files(tmp_path)
    assert [f.name for f in files] == ["00-a.md", "01-b.md"]


def test_read_text_replaces_invalid_bytes(tmp_path: Path, repo):
    path = tmp_path / "bad.md"
    path.write_bytes(b"valid \xff\xfe invalid")
    text = repo.read_text(path)
    assert "valid" in text and "invalid" in text


def test_file_exists_and_file_size(tmp_path: Path, repo):
    path = tmp_path / "f.md"
    path.write_bytes(b"12345")
    assert repo.file_exists(path) is True
    assert repo.file_size(path) == 5
    assert repo.file_exists(tmp_path / "missing.md") is False


def test_list_traceability_files_filters_by_suffix_and_files_only(tmp_path: Path, repo):
    (tmp_path / "note.md").write_text("a")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "image.png").write_text("x")
    (tmp_path / "sub").mkdir()
    files = repo.list_traceability_files(tmp_path)
    assert sorted(f.name for f in files) == ["data.json", "note.md"]


def test_list_traceability_files_suffix_case_insensitive(tmp_path: Path, repo):
    (tmp_path / "NOTE.MD").write_text("a")
    files = repo.list_traceability_files(tmp_path)
    assert [f.name for f in files] == ["NOTE.MD"]


def test_read_manifest_returns_none_when_missing(tmp_path: Path, repo):
    assert repo.read_manifest(tmp_path / "missing.json") is None


def test_read_manifest_returns_none_when_invalid_json(tmp_path: Path, repo):
    path = tmp_path / "bad.json"
    path.write_text("not json")
    assert repo.read_manifest(path) is None


def test_read_manifest_returns_parsed_dict(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 1}))
    assert repo.read_manifest(path) == {"schema": 1}


def test_write_manifest_creates_file_with_generated_at_and_sorted_keys(tmp_path: Path, repo):
    path = tmp_path / "sub" / "manifest.json"
    repo.write_manifest(path, {"schema": 1, "b": 2, "a": 1})
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert payload["schema"] == 1
    assert "generated_at" in payload
    assert text.index('"a"') < text.index('"b"')  # sort_keys=True


def test_write_manifest_skips_write_when_content_unchanged_ignoring_generated_at(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    repo.write_manifest(path, {"schema": 1})
    first_text = path.read_text(encoding="utf-8")
    repo.write_manifest(path, {"schema": 1})
    second_text = path.read_text(encoding="utf-8")
    assert first_text == second_text  # generated_at unchanged: no rewrite happened


def test_write_manifest_rewrites_with_new_generated_at_when_content_changes(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    repo.write_manifest(path, {"schema": 1, "manual_files": []})
    first_generated_at = json.loads(path.read_text(encoding="utf-8"))["generated_at"]
    repo.write_manifest(path, {"schema": 1, "manual_files": [{"name": "x.md"}]})
    second = json.loads(path.read_text(encoding="utf-8"))
    assert second["manual_files"] == [{"name": "x.md"}]
    assert "generated_at" in second


def test_write_manifest_treats_corrupt_existing_file_as_absent(tmp_path: Path, repo):
    path = tmp_path / "manifest.json"
    path.write_text("not json")
    repo.write_manifest(path, {"schema": 1})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert "generated_at" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_json_evidence_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.infrastructure.persistence.json_evidence_repository`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/infrastructure/persistence/json_evidence_repository.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

_TRACEABILITY_SUFFIXES = {".md", ".json"}


def _strip_generated_at(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_generated_at(item) for key, item in value.items() if key != "generated_at"}
    if isinstance(value, list):
        return [_strip_generated_at(item) for item in value]
    return value


class JsonEvidenceRepository:
    def hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def hash_json(self, value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def list_manual_files(self, manual_dir: Path) -> list[Path]:
        return sorted(manual_dir.glob("*.md"))

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def file_exists(self, path: Path) -> bool:
        return path.exists()

    def file_size(self, path: Path) -> int:
        return path.stat().st_size

    def list_traceability_files(self, extracted_dir: Path) -> list[Path]:
        return sorted(
            path
            for path in extracted_dir.glob("*")
            if path.is_file() and path.suffix.lower() in _TRACEABILITY_SUFFIXES
        )

    def read_manifest(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def write_manifest(self, path: Path, payload: dict[str, Any]) -> None:
        next_payload = dict(payload)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            if _strip_generated_at(existing) == _strip_generated_at(next_payload):
                return
        next_payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(next_payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_json_evidence_repository.py -v`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/json_evidence_repository.py tests/unit/infrastructure/test_json_evidence_repository.py
git commit -m "feat(infrastructure): add JsonEvidenceRepository with verbatim legacy hashing and manifest-write skip"
```

---

### Task 4: EvidenceService.build_rules

**Files:**
- Create: `src/docs/application/evidence.py`
- Test: `tests/integration/test_evidence_service.py`

**Interfaces:**
- Consumes: `EvidenceRepository` (Task 2); `ManualFileFact`, `TraceabilityFact`, `build_manifest` (Task 1); `extract_markdown_headings`, `clean_markdown_text` (Slice 3, `domain/markdown_text.py` — reused, not reimplemented).
- Produces: `EvidenceService` class with `build_rules(self, config: dict[str, Any]) -> Path`.

**Documented split from legacy `build_rules(config)`:** legacy reads `config["paths"]["manual_dir"]`, `config["paths"]["extracted_dir"]`, `config["paths"].get("manual_pdf", "")`, `config["paths"].get("example_pdf", "")`, `config["paths"]["rules_manifest"]`, plus `config.get("section_contracts", {})`, `config.get("advisor_overrides", [])`, `config.get("strict_policy", {})`, `config.get("preliminaries", {})`, `config.get("format", {})`, `config.get("apa7", {})`, `config.get("privacy", {})`. `EvidenceService.build_rules` takes the **same raw `config: dict`** shape (not a typed `Template`) because legacy's `config` here is the full merged project config dict (paths + template + project overrides combined at the CLI layer) — not the same shape as `domain.models.template.Template`. Modeling that merged config as a typed Pydantic model is out of scope for this slice (no task in this plan needs it as a model — every field is read once, by key, exactly as legacy does); a typed `ProjectConfig` model is left for a future slice if/when the CLI layer (Slice 10, per `progress.md`) needs one.

**Exact build steps (verbatim from legacy `build_rules`, `tesina_harness.py` lines 475–532), now expressed via the port:**

1. `manual_dir = Path(config["paths"]["manual_dir"])`; `extracted_dir = Path(config["paths"]["extracted_dir"])`.
2. For each path in `self.repository.list_manual_files(manual_dir)` (sorted `*.md`): read text via `self.repository.read_text(path)`; build a `ManualFileFact(path=path.resolve().as_posix(), name=path.name, sha256=self.repository.hash_file(path), headings=extract_markdown_headings(text), excerpt=clean_markdown_text(text[:1200]))`.
3. Traceability: for `("manual_pdf", "institutional_pdf")` and `("example_pdf", "structural_example_pdf")`, read `path_str = config["paths"].get(key, "")`; if `path_str` is empty, **skip without calling `file_exists`** (legacy's `Path("").exists()` is always `False`, but checking an empty-string path through the port is wasted I/O with no behavioral difference — skip in the service for clarity, this is not a behavior change, just avoiding a pointless port call); otherwise build `path = Path(path_str)`, and only append a `TraceabilityFact` if `self.repository.file_exists(path)` is `True`.
4. If `self.repository.file_exists(extracted_dir)`: for each `path` in `self.repository.list_traceability_files(extracted_dir)`, append `TraceabilityFact(path=path.resolve().as_posix(), type="extracted_traceability", sha256=self.repository.hash_file(path), size=self.repository.file_size(path))`.
5. `section_contracts = config.get("section_contracts", {})`; `contract_hashes = {section_id: self.repository.hash_json(contract) for section_id, contract in section_contracts.items()}`.
6. Call `build_manifest(...)` with all the above plus `advisor_overrides=config.get("advisor_overrides", [])`, `draft_mode=config.get("strict_policy", {}).get("draft", {})`, `strict_mode=config.get("strict_policy", {}).get("strict", {})`, `preliminaries=config.get("preliminaries", {})`, `format=config.get("format", {})`, `apa7=config.get("apa7", {})`, `privacy=config.get("privacy", {})`, `section_contracts=section_contracts`, `contract_hashes=contract_hashes`.
7. `path = Path(config["paths"]["rules_manifest"])`; `self.repository.write_manifest(path, manifest)`; return `path`.

**Path serialization note:** legacy's `_as_posix(path) = path.resolve().as_posix()`. This service resolves paths the same way before storing them in `ManualFileFact.path`/`TraceabilityFact.path` — resolution happens in the service (which has the `Path` objects from the port), not in the port methods themselves (which only need to return raw `Path`s for the service to resolve).

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_evidence_service.py
import json
from pathlib import Path

import pytest

from docs.application.evidence import EvidenceService
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository


@pytest.fixture
def service() -> EvidenceService:
    return EvidenceService(JsonEvidenceRepository())


def _config(tmp_path: Path, **overrides) -> dict:
    manual_dir = tmp_path / "manual"
    manual_dir.mkdir()
    extracted_dir = tmp_path / "extracted"
    config = {
        "paths": {
            "manual_dir": str(manual_dir),
            "extracted_dir": str(extracted_dir),
            "rules_manifest": str(tmp_path / "manual-rules.json"),
        },
        "section_contracts": {},
        "advisor_overrides": [],
        "strict_policy": {},
        "preliminaries": {},
        "format": {},
        "apa7": {},
        "privacy": {},
    }
    config["paths"].update(overrides.pop("paths", {}))
    config.update(overrides)
    return config


def test_build_rules_returns_manifest_path(tmp_path: Path, service):
    config = _config(tmp_path)
    result_path = service.build_rules(config)
    assert result_path == Path(config["paths"]["rules_manifest"])
    assert result_path.exists()


def test_build_rules_hashes_manual_markdown_files(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Introducción\n\nTexto inicial.")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1
    entry = manifest["manual_files"][0]
    assert entry["name"] == "00-intro.md"
    assert entry["headings"] == ["Introducción"]
    assert len(entry["sha256"]) == 64


def test_build_rules_manual_files_sorted_by_filename(tmp_path: Path, service):
    config = _config(tmp_path)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "01-b.md").write_text("# B")
    (manual_dir / "00-a.md").write_text("# A")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["manual_files"]] == ["00-a.md", "01-b.md"]


def test_build_rules_skips_missing_manual_pdf_and_example_pdf(tmp_path: Path, service):
    config = _config(tmp_path, paths={"manual_pdf": "", "example_pdf": str(tmp_path / "missing.pdf")})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_includes_existing_manual_pdf_as_traceability(tmp_path: Path, service):
    pdf_path = tmp_path / "manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    config = _config(tmp_path, paths={"manual_pdf": str(pdf_path)})
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["traceability"]) == 1
    entry = manifest["traceability"][0]
    assert entry["type"] == "institutional_pdf"
    assert entry["size"] == pdf_path.stat().st_size


def test_build_rules_includes_extracted_dir_md_and_json_files(tmp_path: Path, service):
    config = _config(tmp_path)
    extracted_dir = Path(config["paths"]["extracted_dir"])
    extracted_dir.mkdir()
    (extracted_dir / "notes.md").write_text("notas")
    (extracted_dir / "data.json").write_text("{}")
    (extracted_dir / "image.png").write_text("x")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    entries = {entry["path"].split("/")[-1] for entry in manifest["traceability"]}
    assert entries == {"notes.md", "data.json"}
    assert all(e["type"] == "extracted_traceability" for e in manifest["traceability"])


def test_build_rules_skips_extracted_dir_entirely_when_absent(tmp_path: Path, service):
    config = _config(tmp_path)  # extracted_dir not created
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["traceability"] == []


def test_build_rules_computes_contract_hashes(tmp_path: Path, service):
    contracts = {"intro": {"title": "Introducción", "required_content": ["objetivo"]}}
    config = _config(tmp_path, section_contracts=contracts)
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["section_contracts"] == contracts
    assert set(manifest["contract_hashes"]) == {"intro"}
    assert len(manifest["contract_hashes"]["intro"]) == 64


def test_build_rules_carries_policy_apa7_privacy_preliminaries_format(tmp_path: Path, service):
    config = _config(
        tmp_path,
        strict_policy={"draft": {"allow_pending": True}, "strict": {"allow_pending": False}},
        apa7={"enabled": True},
        privacy={"redact": True},
        preliminaries={"roman_pagination": {"enabled": True}},
        format={"page_margins_cm": {}},
        advisor_overrides=[{"id": "x", "status": "active"}],
    )
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert manifest["policy"]["draft_mode"] == {"allow_pending": True}
    assert manifest["policy"]["strict_mode"] == {"allow_pending": False}
    assert manifest["apa7"] == {"enabled": True}
    assert manifest["privacy"] == {"redact": True}
    assert manifest["preliminaries"] == {"roman_pagination": {"enabled": True}}
    assert manifest["format"] == {"page_margins_cm": {}}
    assert manifest["advisor_overrides"] == [{"id": "x", "status": "active"}]
    assert manifest["policy"]["advisor_overrides"] == [{"id": "x", "status": "active"}]


def test_build_rules_second_call_with_unchanged_inputs_does_not_rewrite_generated_at(tmp_path: Path, service):
    config = _config(tmp_path)
    path = service.build_rules(config)
    first = json.loads(path.read_text(encoding="utf-8"))
    path = service.build_rules(config)
    second = json.loads(path.read_text(encoding="utf-8"))
    assert first["generated_at"] == second["generated_at"]


def test_build_rules_second_call_with_new_manual_file_rewrites_manifest(tmp_path: Path, service):
    config = _config(tmp_path)
    service.build_rules(config)
    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-new.md").write_text("# Nuevo")
    path = service.build_rules(config)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert len(manifest["manual_files"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_evidence_service.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.application.evidence`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/evidence.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.evidence import ManualFileFact, TraceabilityFact, build_manifest
from docs.domain.markdown_text import clean_markdown_text, extract_markdown_headings
from docs.domain.ports.evidence_repository import EvidenceRepository

_TRACEABILITY_PATH_KEYS = [
    ("manual_pdf", "institutional_pdf"),
    ("example_pdf", "structural_example_pdf"),
]
_EXCERPT_LENGTH = 1200


class EvidenceService:
    def __init__(self, repository: EvidenceRepository) -> None:
        self.repository = repository

    def build_rules(self, config: dict[str, Any]) -> Path:
        manual_dir = Path(config["paths"]["manual_dir"])
        extracted_dir = Path(config["paths"]["extracted_dir"])

        manual_files: list[ManualFileFact] = []
        for path in self.repository.list_manual_files(manual_dir):
            text = self.repository.read_text(path)
            manual_files.append(
                ManualFileFact(
                    path=path.resolve().as_posix(),
                    name=path.name,
                    sha256=self.repository.hash_file(path),
                    headings=extract_markdown_headings(text),
                    excerpt=clean_markdown_text(text[:_EXCERPT_LENGTH]),
                )
            )

        traceability: list[TraceabilityFact] = []
        for key, source_type in _TRACEABILITY_PATH_KEYS:
            path_str = config["paths"].get(key, "")
            # Legacy reads Path("").exists() when the key is absent/empty, which is
            # always False — skip the empty-string case directly rather than making
            # a pointless file_exists() call through the port.
            if not path_str:
                continue
            path = Path(path_str)
            if self.repository.file_exists(path):
                traceability.append(
                    TraceabilityFact(
                        path=path.resolve().as_posix(),
                        type=source_type,
                        sha256=self.repository.hash_file(path),
                        size=self.repository.file_size(path),
                    )
                )

        if self.repository.file_exists(extracted_dir):
            for path in self.repository.list_traceability_files(extracted_dir):
                traceability.append(
                    TraceabilityFact(
                        path=path.resolve().as_posix(),
                        type="extracted_traceability",
                        sha256=self.repository.hash_file(path),
                        size=self.repository.file_size(path),
                    )
                )

        section_contracts = config.get("section_contracts", {})
        contract_hashes = {
            section_id: self.repository.hash_json(contract)
            for section_id, contract in section_contracts.items()
        }

        strict_policy = config.get("strict_policy", {})
        manifest = build_manifest(
            manual_files=manual_files,
            traceability=traceability,
            advisor_overrides=config.get("advisor_overrides", []),
            draft_mode=strict_policy.get("draft", {}),
            strict_mode=strict_policy.get("strict", {}),
            preliminaries=config.get("preliminaries", {}),
            format=config.get("format", {}),
            apa7=config.get("apa7", {}),
            privacy=config.get("privacy", {}),
            section_contracts=section_contracts,
            contract_hashes=contract_hashes,
        )

        path = Path(config["paths"]["rules_manifest"])
        self.repository.write_manifest(path, manifest)
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_evidence_service.py -v`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/evidence.py tests/integration/test_evidence_service.py
git commit -m "feat(application): add EvidenceService.build_rules replacing legacy build_rules"
```

---

## Full suite check (run after Task 4)

```bash
uv run pytest -W error -q
```

Expected: all tests pass (227 from Slices 1–3 plus this slice's 9 + 14 + 11 = 34 new tests → 261 total), zero warnings.

---

## Self-Review

- **Spec coverage (legacy `build_rules` and its direct helpers):**
  - Manual markdown hashing/heading/excerpt extraction ✅ Task 1 (pure assembly) + Task 3 (adapter glob/read/hash) + Task 4 (service wiring) — reuses Slice 3's `extract_markdown_headings`/`clean_markdown_text` rather than reimplementing text processing.
  - Traceability (manual/example PDF + extracted-dir hashing) ✅ Task 4 — exact key/type pairs (`manual_pdf`→`institutional_pdf`, `example_pdf`→`structural_example_pdf`, extracted-dir entries→`extracted_traceability`), exact empty-path skip, exact `.md`/`.json` suffix filter on `extracted_dir`.
  - `write_json_manifest` (skip-if-unchanged + `generated_at` stamping) ✅ Task 3 — `_strip_generated_at` comparison ported verbatim into the adapter.
  - `sha256_file`/`sha256_json` ✅ Task 3 — exact `hashlib.sha256(...).hexdigest()` over raw bytes / over `json.dumps(..., ensure_ascii=False, sort_keys=True)`.
  - Manifest dict shape (`schema`, `policy.*`, `manual_files`, `traceability`, `preliminaries`, `format`, `advisor_overrides` top-level duplicate, `apa7`, `privacy`, `section_contracts`, `contract_hashes`) ✅ Task 1, verbatim field set and the intentional `advisor_overrides` duplication.
- **Documented decisions (not silent gaps):**
  1. **`generated_at` excluded from the domain function (Task 1).** Legacy's write-skip optimization compares manifest content with `generated_at` stripped, and only stamps a *new* `generated_at` when an actual write happens. Modeling `generated_at` inside `build_manifest` would force the pure function to either take "current time" as an input (turning a pure function into an I/O-adjacent one) or omit it (matching legacy's actual comparison semantics). This slice chose the latter — `build_manifest` never produces a `generated_at` key at all; the adapter's `write_manifest` adds it only on actual writes. Verified equivalent to legacy via Task 3's two write-skip tests.
  2. **`config` stays an untyped `dict` in `EvidenceService.build_rules` (Task 4), not a `Template`.** Legacy's `config` parameter to `build_rules` is the full merged project config (paths + template + overrides), a different and broader shape than `domain.models.template.Template`. No task in this slice needs it typed — every field is read once by key, exactly as legacy does. A typed `ProjectConfig` is deferred to whichever future slice (likely the CLI slice, per `progress.md`) actually assembles this merged config from a `Template` plus project-level files.
  3. **`contract_hashes` computed in the service via the port's `hash_json`, not duplicated in `domain/evidence.py`.** `sha256_json` needs `hashlib`+`json.dumps`, the same I/O-adjacent primitive class as file hashing — keeping it in the adapter (Task 3) avoids a parallel hashing implementation living in two places.
  4. **Confirmed exclusion from this slice: legacy `review_document` orchestrator.** Slice 3's Self-Review already flagged this as deferred (not specifically to Slice 4) — re-confirmed here as **still not ported** by any task in this slice either. It is a distinct concern (walking `sections_dir`, calling `review_section_text` per file, two extra document-level strict-mode checks) from `build_rules`'s evidence/manifest concern, and remains the right scope for a focused follow-up slice once both Slice 3's review functions and this slice's evidence functions exist to be composed by it. Not silently dropped — explicitly flagged as an open dependency for that future slice.
  5. **Confirmed exclusion: `doctor`/CLI-level consumption of `manual-rules.json` contents** (e.g. legacy's `rules_manifest` existence `Check` at line ~2213). `review_rules` (Slice 3) already only reads `manifest_exists`/`manifest_size` — no Task 1–4 function in this slice needs to be consumed by a `doctor` command, and none is built. CLI wiring is Slice 10 per `progress.md`.
- **Placeholder scan:** no TBD/TODO/elisions; every Step 1/Step 3 across all 4 tasks shows complete, runnable code. Task 2 has no Step 1/Step 2 test code by design (a bare `Protocol` declaration has no independently-testable behavior) — explicitly justified, not a skipped step.
- **Type consistency:** `ManualFileFact`/`TraceabilityFact` (Task 1) flow unchanged into `build_manifest` (Task 1) and are constructed by `EvidenceService` (Task 4) using `EvidenceRepository` (Task 2) primitives implemented by `JsonEvidenceRepository` (Task 3) — one direction of dependency throughout (`application → domain` + `application → port`; `infrastructure → port` via structural typing), no task reaches back into an earlier task's internals.
