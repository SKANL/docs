# Slice 6 — Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the legacy hash/provenance subsystem that Slices 4 and 5 explicitly deferred: `rules_hash`, `contract_hash`, `manifest_hash`, `_hash_files` (the composite hash functions that consume Slice 4's already-ported `sha256_file`/`sha256_json` primitives), plus `stamp_section` (provenance stamping of an externally-authored section file). This slice does **not** re-port `sha256_text`/`sha256_file`/`sha256_json` as standalone domain functions — those primitives already exist as `hash_file`/`hash_json` methods on Slice 4's `EvidenceRepository` port and `JsonEvidenceRepository` adapter. This slice adds the one primitive that's still missing (`sha256_text`, needed by `rules_hash`'s fallback branch and by `stamp_section`'s `body_hash` field) as a new `hash_text` method on the same port, then builds the composite hash functions and `stamp_section` on top.

**Explicit exclusion — `source_hash`, `prompt_hash`, `build_section`:** confirmed out of scope for this slice (see Self-Review for full justification). `source_hash` reads `config["paths"]["context_dir"]` and `config["sections"]` — a project-config shape this codebase has never modeled (no `context_dir` concept exists anywhere in `Workspace`/`ContextRepository`; Slice 2's `ContextService` manages topics, not raw markdown files under a hashed `context_dir`). `prompt_hash` reads `config["paths"]["prompts_dir"]`, a directory this codebase has no representation of at all — no prompts subsystem has been ported in any prior slice. `build_section` depends on `render_fact_ledger`, `render_section_draft`, and `load_context`/`load_context_for` — an LLM-prompt-driven section-scaffolding subsystem that is a different, much larger concern (prompt templating + generation) than hashing/provenance, and itself depends on `source_hash`/`prompt_hash` being resolved first. Porting any of the three now would mean inventing project-config shapes with no other consumer in this codebase, which is speculative modeling, not parity work. All three are deferred to a future slice, once the underlying `context_dir`/`prompts_dir`/generation concepts are themselves ported (or explicitly redesigned) elsewhere.

**Architecture:** Pragmatic hexagonal, same shape as Slices 1–5. `domain/evidence.py` (Slice 4, extended in this slice) gains pure composite-hash assembly functions (`build_rules_hash_payload`, `build_section_provenance`) that accept pre-computed file-fact lists/hashes and decide the inputs to the next hash, exactly like `build_manifest` decides the manifest dict shape — they never touch the filesystem themselves. The `EvidenceRepository` port (Slice 4) gains three new methods (`hash_text`, `read_rules_manifest_bytes`/reuses `file_exists`+`file_size`, and a manifest-or-fallback resolver is kept in the service, not the port — see Task 2 rationale) needed to compute `rules_hash`/`contract_hash`/`manifest_hash` without new filesystem primitives beyond what hashing already requires. `JsonEvidenceRepository` (Slice 4) implements the one new method. `application/evidence.py`'s `EvidenceService` (Slice 4) gains `rules_hash`, `contract_hash`, and `manifest_hash` methods that orchestrate port + domain exactly as `build_rules` already does. For section provenance, `SectionRepository` (Slice 5) gains a `write_section` method — Slice 5's port was deliberately read-only because `review_document` only reads section files; `stamp_section` is this slice's first use case that needs to *write* an existing section file back to disk with updated frontmatter, so the port grows the one write method the use case needs, following the same "one port per aggregate, write methods added when a use case needs them" pattern Slice 4 used for `EvidenceRepository.write_manifest`. `application/review.py`'s `ReviewService` (Slice 5) gains `stamp_section`, composing the port (read + write) with a new pure domain function (`domain/sections.py`'s `apply_stamp`) that computes the updated metadata dict. Nothing in `domain/evidence.py` or `domain/sections.py` imports from `application`, `infrastructure`, or `cli`.

**Tech Stack:** Python ≥3.11, Pydantic v2 (no new models needed), `hashlib.sha256` (verbatim legacy algorithm, reusing Slice 4's existing `hash_file`/`hash_json` and this slice's new `hash_text`), pytest with `tmp_path` for adapter/integration tests (no test touches the real legacy file tree).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. `domain/evidence.py` and `domain/sections.py` import nothing from `application`, `infrastructure`, or `cli`.
- **Hash algorithm parity, confirmed from legacy source (`tesina_harness.py` lines 365–374):**
  ```python
  def sha256_text(text: str) -> str:
      return hashlib.sha256(text.encode("utf-8")).hexdigest()

  def sha256_file(path: Path) -> str:
      return hashlib.sha256(path.read_bytes()).hexdigest()

  def sha256_json(value: Any) -> str:
      return sha256_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
  ```
  Note legacy's `sha256_json` is defined *in terms of* `sha256_text` (dump then hash the text). Slice 4's `JsonEvidenceRepository.hash_json` already reproduces the same byte-for-byte result by inlining `hashlib.sha256(text.encode("utf-8")).hexdigest()` directly rather than calling a `hash_text` method — this is a pre-existing, already-shipped implementation and is **not** being changed by this slice (changing Task 1's working `hash_json` to call the new `hash_text` would touch already-approved Slice 4 code for a purely cosmetic reason; the byte-for-byte output is identical either way, since both paths reduce to `hashlib.sha256(json.dumps(...).encode("utf-8")).hexdigest()`). This slice only **adds** `hash_text` as a new sibling method for the call sites that need to hash raw text directly (`rules_hash`'s fallback branch, `stamp_section`'s `body_hash`) — it does not refactor `hash_json`.
- **`rules_hash` parity, confirmed from legacy source (`tesina_harness.py` lines 442–457):**
  ```python
  def rules_hash(config: dict[str, Any]) -> str:
      rules_path = Path(config["paths"]["rules_manifest"])
      if rules_path.exists():
          return sha256_file(rules_path)
      manual_dir = config["paths"].get("manual_dir")
      manual_files = _hash_files(Path(manual_dir).glob("*.md")) if manual_dir and Path(manual_dir).exists() else []
      return sha256_json(
          {
              "manual_dir": manual_files,
              "section_contracts": config.get("section_contracts", {}),
              "format": config.get("format", {}),
              "apa7": config.get("apa7", {}),
              "structure": config.get("structure", []),
              "preliminaries": config.get("preliminaries", {}),
          }
      )
  ```
  Two-branch quirk preserved verbatim: if the manifest file exists on disk, hash the **file bytes** directly (ignoring everything else — `section_contracts`/`format`/`apa7`/`structure`/`preliminaries` are not even read in this branch); only when the manifest is absent does it fall back to hashing a synthesized payload built from `_hash_files` over `manual_dir`'s markdown files plus the raw config dicts. This is not a bug to "fix" by always using the synthesized form — it is legacy's actual selection logic and must stay.
- **`_hash_files` parity, confirmed from legacy source (`tesina_harness.py` lines 471–472):**
  ```python
  def _hash_files(paths: Any) -> list[dict[str, str]]:
      return [{"path": _as_posix(path), "sha256": sha256_file(path)} for path in sorted(Path(p) for p in paths)]
  ```
  Note: `sorted(Path(p) for p in paths)` sorts by `Path` natural ordering (which sorts lexicographically on the string form of the path), not by filename alone — applied here to whatever iterable of glob results is passed in.
- **`contract_hash` parity, confirmed from legacy source (`tesina_harness.py` lines 460–461):**
  ```python
  def contract_hash(config: dict[str, Any], section_id: str) -> str:
      return sha256_json(config.get("section_contracts", {}).get(section_id, {}))
  ```
  Trivial wrapper: hash whatever section-contract dict is found for `section_id`, or hash `{}` if the section has no contract at all (not an error case — same permissive `.get(..., {})` pattern legacy uses everywhere for optional config blocks).
- **`manifest_hash` parity, confirmed from legacy source (`tesina_harness.py` lines 464–468):**
  ```python
  def manifest_hash(path_value: str | None) -> str:
      if not path_value:
          return ""
      path = Path(path_value)
      return sha256_file(path) if path.exists() else ""
  ```
  Three-way short-circuit preserved verbatim: empty/`None` path → `""`; non-empty path that doesn't exist on disk → `""` (same value as the empty-path case — legacy treats "no manifest configured" and "manifest configured but missing" identically, returning an empty-string hash rather than raising); only an existing path gets a real hash.
- **`stamp_section` parity, confirmed from legacy source (`tesina_harness.py` lines 3324–3339):**
  ```python
  def stamp_section(config: dict[str, Any], section_id: str, authored_by: str, model: str = "") -> Path:
      section = section_by_id(config, section_id)
      path = section_path_for(config, section)
      if not path.exists():
          raise FileNotFoundError(f"No existe la sección a sellar: {path}")
      metadata, body = split_frontmatter(path.read_text(encoding="utf-8"))
      if not metadata:
          metadata = {"managed_by": "tesina-harness", "schema": 3, "section_id": section_id, "title": section["title"]}
      metadata["authored_by"] = authored_by
      if model:
          metadata["model"] = model
      metadata["body_hash"] = sha256_text(body)
      metadata["stamped_at"] = datetime.now().isoformat(timespec="seconds")
      path.write_text(with_frontmatter(body, metadata), encoding="utf-8")
      return path
  ```
  Five-step sequence preserved verbatim: (1) raise if the section file doesn't exist (no silent no-op); (2) if the existing file had no frontmatter at all, synthesize a minimal default metadata dict (`managed_by`/`schema`/`section_id`/`title`) rather than stamping onto an empty dict; (3) always set `authored_by`; (4) set `model` only if a non-empty string was passed (legacy's `if model:` — an empty string leaves any pre-existing `model` key untouched, it does not delete it); (5) always recompute `body_hash` from the **current** body text and always stamp a fresh `stamped_at` timestamp, then write back with `with_frontmatter`. `with_frontmatter` itself (`tesina_harness.py` lines 413–414, not yet ported in this codebase) is needed here and is ported as a small pure domain helper in Task 1 of this slice (it has no I/O of its own — it is a string-formatting function, like `clean_markdown_text` was correctly placed in `domain/markdown_text.py` rather than an adapter).
- **`SectionRepository` port write extension is deliberate, not scope creep:** Slice 5's Self-Review explicitly flagged the port as "intentionally read-only... extensible later without breaking this contract" precisely for this slice. `write_section(doc_id, order, section_id, raw_text) -> None` is added — a single, narrow write method (write the rendered frontmatter+body string to the section's path, creating the `sections/` directory if needed, mirroring `JsonContextRepository`'s mkdir-per-write precedent from Slice 2) — not a generic file-write method and not a scaffolding (`build_section`-shaped) method. This follows the established pattern: Slice 4's `EvidenceRepository` got `write_manifest` only when `EvidenceService.build_rules` (its first and only write-needing use case) needed it; here, `stamp_section`'s `ReviewService.stamp_section` is the first and only Slice-5/6 use case that needs to write a section file back, so `SectionRepository` grows exactly the one method that use case needs.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/domain/evidence.py` — extended with `ManualHashFact`, `build_rules_hash_payload` (existing `ManualFileFact`/`TraceabilityFact`/`build_manifest` untouched).
- `src/docs/domain/sections.py` — extended with `with_frontmatter`, `default_section_metadata`, `apply_stamp` (existing `infer_section_id_from_path` untouched).
- `src/docs/domain/ports/evidence_repository.py` — `EvidenceRepository` Protocol gains `hash_text`.
- `src/docs/domain/ports/section_repository.py` — `SectionRepository` Protocol gains `write_section`.
- `src/docs/infrastructure/persistence/json_evidence_repository.py` — `JsonEvidenceRepository` implements `hash_text`.
- `src/docs/infrastructure/persistence/json_section_repository.py` — `JsonSectionRepository` implements `write_section`.
- `src/docs/application/evidence.py` — `EvidenceService` gains `rules_hash`, `contract_hash`, `manifest_hash`.
- `src/docs/application/review.py` — `ReviewService` gains `stamp_section`.
- `tests/unit/domain/test_evidence.py` — extended.
- `tests/unit/domain/test_sections.py` — extended.
- `tests/unit/infrastructure/test_json_evidence_repository.py` — extended.
- `tests/unit/infrastructure/test_json_section_repository.py` — extended.
- `tests/integration/test_evidence_service.py` — extended.
- `tests/integration/test_review_service.py` — extended.

---

### Task 1: Pure domain additions — rules-hash payload assembly + section provenance stamping

**Files:**
- Modify: `src/docs/domain/evidence.py`
- Modify: `src/docs/domain/sections.py`
- Modify: `tests/unit/domain/test_evidence.py`
- Modify: `tests/unit/domain/test_sections.py`

**Interfaces:**
- Consumes: nothing new from other domain modules.
- Produces in `domain/evidence.py`:
  - `ManualHashFact` frozen dataclass: `path: str, sha256: str` — the pre-computed per-file fact `_hash_files` assembles, kept distinct from `ManualFileFact` (which additionally carries `name`/`headings`/`excerpt`, none of which `rules_hash`'s fallback branch needs).
  - `build_rules_hash_payload(manual_files: list[ManualHashFact], section_contracts: dict[str, dict], format: dict, apa7: dict, structure: list[dict], preliminaries: dict) -> dict[str, Any]` — pure assembly of the dict legacy passes to `sha256_json` in `rules_hash`'s fallback branch. Hashing the result is the adapter/service's job (Task 2/3), not this function's — mirrors `build_manifest`'s split (assemble dict here, hash there).
- Produces in `domain/sections.py`:
  - `with_frontmatter(body: str, metadata: dict[str, Any]) -> str` — verbatim port of legacy's pure string-formatting helper (`"---\n" + json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n---\n" + body`).
  - `default_section_metadata(section_id: str, title: str) -> dict[str, Any]` — the minimal metadata dict legacy synthesizes when stamping a frontmatter-less file (`{"managed_by": "tesina-harness", "schema": 3, "section_id": section_id, "title": title}`).
  - `apply_stamp(metadata: dict[str, Any], section_id: str, title: str, body: str, body_hash: str, authored_by: str, model: str, stamped_at: str) -> dict[str, Any]` — pure decision function: given the *current* metadata dict (possibly empty) and the already-computed `body_hash`/`stamped_at` (both I/O-adjacent — hashing and current-time — and therefore computed by the caller, not this function, exactly as Slice 4's `build_manifest` never computes `generated_at` itself), returns the new metadata dict with `authored_by` always set, `model` set only if non-empty (preserving legacy's `if model:` guard — an empty string leaves the existing key, if any, untouched rather than deleting it), and `body_hash`/`stamped_at` always overwritten. Starts from `default_section_metadata(section_id, title)` if the incoming `metadata` is empty, exactly like legacy's `if not metadata:` branch.

**Why `body_hash`/`stamped_at` are passed in, not computed inside `apply_stamp`:** identical reasoning to Slice 4's Task 1 note on why `generated_at` isn't computed inside `build_manifest` — `sha256_text` and "current time" are both I/O-adjacent primitives (hashing needs `hashlib`, timestamping needs `datetime.now()`), and keeping them out of the pure function is what makes `apply_stamp` deterministically testable without monkeypatching `datetime`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_evidence.py — ADD to existing file (does not modify existing tests)
from docs.domain.evidence import ManualHashFact, build_rules_hash_payload


def test_build_rules_hash_payload_assembles_expected_keys():
    fact = ManualHashFact(path="/repo/manual/00-intro.md", sha256="a" * 64)
    payload = build_rules_hash_payload(
        manual_files=[fact],
        section_contracts={"intro": {"title": "Introducción"}},
        format={"page_margins_cm": {}},
        apa7={"enabled": True},
        structure=[{"type": "cover"}],
        preliminaries={"roman_pagination": {"enabled": True}},
    )
    assert payload == {
        "manual_dir": [{"path": fact.path, "sha256": fact.sha256}],
        "section_contracts": {"intro": {"title": "Introducción"}},
        "format": {"page_margins_cm": {}},
        "apa7": {"enabled": True},
        "structure": [{"type": "cover"}],
        "preliminaries": {"roman_pagination": {"enabled": True}},
    }


def test_build_rules_hash_payload_empty_inputs():
    payload = build_rules_hash_payload(
        manual_files=[], section_contracts={}, format={}, apa7={}, structure=[], preliminaries={}
    )
    assert payload == {
        "manual_dir": [],
        "section_contracts": {},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }


def test_build_rules_hash_payload_preserves_manual_files_order():
    first = ManualHashFact(path="/repo/manual/00-a.md", sha256="a" * 64)
    second = ManualHashFact(path="/repo/manual/01-b.md", sha256="b" * 64)
    payload = build_rules_hash_payload(
        manual_files=[first, second], section_contracts={}, format={}, apa7={}, structure=[], preliminaries={}
    )
    assert [f["path"] for f in payload["manual_dir"]] == [first.path, second.path]
```

```python
# tests/unit/domain/test_sections.py — ADD to existing file (does not modify existing tests)
from docs.domain.sections import apply_stamp, default_section_metadata, with_frontmatter


def test_with_frontmatter_formats_metadata_and_body():
    text = with_frontmatter("# Cuerpo\n", {"b": 2, "a": 1})
    assert text.startswith("---\n")
    assert '"a": 1' in text
    assert text.index('"a"') < text.index('"b"')  # sort_keys=True
    assert text.endswith("---\n# Cuerpo\n")


def test_default_section_metadata_shape():
    metadata = default_section_metadata("introduccion", "Introducción")
    assert metadata == {
        "managed_by": "tesina-harness",
        "schema": 3,
        "section_id": "introduccion",
        "title": "Introducción",
    }


def test_apply_stamp_synthesizes_default_metadata_when_empty():
    result = apply_stamp(
        metadata={},
        section_id="introduccion",
        title="Introducción",
        body="texto",
        body_hash="b" * 64,
        authored_by="agent-x",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["managed_by"] == "tesina-harness"
    assert result["schema"] == 3
    assert result["section_id"] == "introduccion"
    assert result["title"] == "Introducción"
    assert result["authored_by"] == "agent-x"
    assert result["body_hash"] == "b" * 64
    assert result["stamped_at"] == "2026-06-21T00:00:00"
    assert "model" not in result


def test_apply_stamp_preserves_existing_metadata_fields():
    existing = {"managed_by": "tesina-harness", "schema": 3, "section_id": "introduccion", "title": "Introducción", "custom": "kept"}
    result = apply_stamp(
        metadata=existing,
        section_id="introduccion",
        title="Introducción",
        body="texto",
        body_hash="c" * 64,
        authored_by="agent-y",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["custom"] == "kept"
    assert result["authored_by"] == "agent-y"


def test_apply_stamp_sets_model_when_provided():
    result = apply_stamp(
        metadata={"managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X"},
        section_id="x",
        title="X",
        body="texto",
        body_hash="d" * 64,
        authored_by="agent-z",
        model="opus",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["model"] == "opus"


def test_apply_stamp_empty_model_does_not_delete_existing_model_key():
    existing = {"managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X", "model": "previous-model"}
    result = apply_stamp(
        metadata=existing,
        section_id="x",
        title="X",
        body="texto",
        body_hash="e" * 64,
        authored_by="agent-w",
        model="",
        stamped_at="2026-06-21T00:00:00",
    )
    assert result["model"] == "previous-model"


def test_apply_stamp_always_overwrites_body_hash_and_stamped_at():
    existing = {
        "managed_by": "tesina-harness", "schema": 3, "section_id": "x", "title": "X",
        "body_hash": "stale", "stamped_at": "2020-01-01T00:00:00",
    }
    result = apply_stamp(
        metadata=existing,
        section_id="x",
        title="X",
        body="nuevo texto",
        body_hash="f" * 64,
        authored_by="agent-v",
        model="",
        stamped_at="2026-06-21T12:00:00",
    )
    assert result["body_hash"] == "f" * 64
    assert result["stamped_at"] == "2026-06-21T12:00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_evidence.py tests/unit/domain/test_sections.py -v`
Expected: FAIL with `ImportError: cannot import name 'ManualHashFact'` (and similarly for `with_frontmatter`/`default_section_metadata`/`apply_stamp`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/evidence.py — ADD to existing file (existing ManualFileFact/TraceabilityFact/build_manifest untouched)

@dataclass(frozen=True)
class ManualHashFact:
    path: str
    sha256: str


def build_rules_hash_payload(
    manual_files: list[ManualHashFact],
    section_contracts: dict[str, dict],
    format: dict,
    apa7: dict,
    structure: list[dict],
    preliminaries: dict,
) -> dict[str, Any]:
    return {
        "manual_dir": [{"path": fact.path, "sha256": fact.sha256} for fact in manual_files],
        "section_contracts": section_contracts,
        "format": format,
        "apa7": apa7,
        "structure": structure,
        "preliminaries": preliminaries,
    }
```

```python
# src/docs/domain/sections.py — ADD to existing file (existing infer_section_id_from_path untouched)
import json as _json
from typing import Any


def with_frontmatter(body: str, metadata: dict[str, Any]) -> str:
    return "---\n" + _json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n---\n" + body


def default_section_metadata(section_id: str, title: str) -> dict[str, Any]:
    return {
        "managed_by": "tesina-harness",
        "schema": 3,
        "section_id": section_id,
        "title": title,
    }


def apply_stamp(
    metadata: dict[str, Any],
    section_id: str,
    title: str,
    body: str,
    body_hash: str,
    authored_by: str,
    model: str,
    stamped_at: str,
) -> dict[str, Any]:
    new_metadata = dict(metadata) if metadata else default_section_metadata(section_id, title)
    new_metadata["authored_by"] = authored_by
    if model:
        new_metadata["model"] = model
    new_metadata["body_hash"] = body_hash
    new_metadata["stamped_at"] = stamped_at
    return new_metadata
```

Note: `body` is accepted as a parameter for interface symmetry with the legacy call site (`stamp_section` reads body before calling, and `body_hash` is derived from it) but is not read inside `apply_stamp` itself — the hash is precomputed by the caller. Kept as a parameter so the function signature documents the relationship even though the value isn't used internally; an alternative was to drop the unused parameter, but keeping it makes the call site at `ReviewService.stamp_section` (Task 4) self-documenting about what `body_hash` was derived from. (Marked here, not silently passed — see Self-Review for the explicit judgment call.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_evidence.py tests/unit/domain/test_sections.py -v`
Expected: PASS. `test_evidence.py`: 9 pre-existing (Slice 4) + 3 new = 12. `test_sections.py`: 5 pre-existing (Slice 5) + 7 new = 12.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/evidence.py src/docs/domain/sections.py tests/unit/domain/test_evidence.py tests/unit/domain/test_sections.py
git commit -m "feat(domain): add rules-hash payload assembly and section provenance stamping (pure)"
```

---

### Task 2: Port extensions — `EvidenceRepository.hash_text` + `SectionRepository.write_section`

**Files:**
- Modify: `src/docs/domain/ports/evidence_repository.py`
- Modify: `src/docs/domain/ports/section_repository.py`
- Test: none (extending an existing `Protocol` with a new method signature has nothing to unit test on its own — same precedent as Slice 4 Task 2 and Slice 5 Task 2; the new methods are exercised by Task 3's adapter tests).

**Interfaces:**
- `EvidenceRepository` gains: `hash_text(text: str) -> str` — sha256 of UTF-8-encoded text, the missing primitive needed by `rules_hash`'s fallback branch (hashing the `build_rules_hash_payload` JSON — actually routed through `hash_json`, see Task 3 note) and by `stamp_section`'s `body_hash` field (hashing the raw section body text directly).
- `SectionRepository` gains: `write_section(doc_id: str, order: int, section_id: str, raw_text: str) -> None` — writes `raw_text` verbatim to the section's path (`{order:03d}-{section_id}.md` under the document's `sections/` directory), creating the `sections/` directory if it doesn't exist yet (mirrors `JsonContextRepository`'s per-write mkdir, a documented non-blocking pattern since Slice 2).

**Why `hash_text` is a new method rather than reusing `hash_json`:** `rules_hash`'s file-exists branch hashes raw file *bytes* (already covered by `hash_file`); its fallback branch hashes a JSON-serialized dict (covered by `hash_json`); but `stamp_section`'s `body_hash` hashes a section's raw Markdown *body text* directly — `sha256_text(body)` in legacy, not `sha256_json(body)`. `hash_json` would incorrectly re-serialize the string through `json.dumps`, double-quoting and escaping it, producing a different hash than legacy's direct `text.encode("utf-8")`. `hash_text` is the correct, distinct primitive for this call site.

- [ ] **Step 1: Write the failing test**

No test in this task (Protocol-only extension, per established precedent). Skip directly to Step 3.

- [ ] **Step 2: Run test to verify it fails**

N/A — no test file in this task.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/ports/evidence_repository.py — MODIFY existing Protocol, add one method
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class EvidenceRepository(Protocol):
    def hash_file(self, path: Path) -> str: ...
    def hash_json(self, value: Any) -> str: ...
    def hash_text(self, text: str) -> str: ...
    def list_manual_files(self, manual_dir: Path) -> list[Path]: ...
    def read_text(self, path: Path) -> str: ...
    def file_exists(self, path: Path) -> bool: ...
    def file_size(self, path: Path) -> int: ...
    def list_traceability_files(self, extracted_dir: Path) -> list[Path]: ...
    def read_manifest(self, path: Path) -> dict[str, Any] | None: ...
    def write_manifest(self, path: Path, payload: dict[str, Any]) -> None: ...
```

```python
# src/docs/domain/ports/section_repository.py — MODIFY existing Protocol, add one method
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SectionRepository(Protocol):
    def section_path(self, doc_id: str, order: int, section_id: str) -> Path: ...
    def sections_dir_exists(self, doc_id: str) -> bool: ...
    def section_exists(self, doc_id: str, order: int, section_id: str) -> bool: ...
    def read_section(self, doc_id: str, order: int, section_id: str) -> tuple[dict, str]: ...
    def write_section(self, doc_id: str, order: int, section_id: str, raw_text: str) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

N/A — no test in this task. Sanity-check both modules still import cleanly:

Run: `uv run python -c "from docs.domain.ports.evidence_repository import EvidenceRepository; from docs.domain.ports.section_repository import SectionRepository; print(EvidenceRepository, SectionRepository)"`
Expected: prints both Protocol classes, no import error.

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/ports/evidence_repository.py src/docs/domain/ports/section_repository.py
git commit -m "feat(domain): extend EvidenceRepository with hash_text and SectionRepository with write_section"
```

---

### Task 3: Adapter implementations — `JsonEvidenceRepository.hash_text` + `JsonSectionRepository.write_section`

**Files:**
- Modify: `src/docs/infrastructure/persistence/json_evidence_repository.py`
- Modify: `src/docs/infrastructure/persistence/json_section_repository.py`
- Modify: `tests/unit/infrastructure/test_json_evidence_repository.py`
- Modify: `tests/unit/infrastructure/test_json_section_repository.py`

**Interfaces:**
- Consumes: `EvidenceRepository`/`SectionRepository` (Task 2, structurally).
- Produces: `hash_text` on `JsonEvidenceRepository`; `write_section` on `JsonSectionRepository`.

**Hash parity (confirmed, `tesina_harness.py` line 365–366):** `sha256_text(text) = hashlib.sha256(text.encode("utf-8")).hexdigest()` — identical encoding to `hash_file`'s `path.read_bytes()` path, just operating on a string's UTF-8 bytes instead of a file's raw bytes.

**Write parity:** legacy's `stamp_section`/`build_section` both do a bare `path.write_text(generated, encoding="utf-8")` with no explicit `mkdir` call at the point of writing (the `sections_dir` is already guaranteed to exist by the time `stamp_section` runs, because it raises `FileNotFoundError` first if the target section file itself doesn't exist — and a section file can't exist without its parent directory existing). `write_section`'s own `mkdir(parents=True, exist_ok=True)` is therefore defensive (matches Slice 2/4's established mkdir-per-write precedent) rather than required for `stamp_section`'s own call path; it does mean `write_section` is safely reusable by a future write-needing use case that doesn't have that same existence guarantee.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/infrastructure/test_json_evidence_repository.py — ADD to existing file
import hashlib


def test_hash_text_matches_raw_sha256_of_utf8_bytes(repo):
    text = "café con PENDIENTE"
    assert repo.hash_text(text) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_hash_text_matches_hash_file_for_same_bytes(tmp_path, repo):
    text = "contenido idéntico"
    path = tmp_path / "f.md"
    path.write_text(text, encoding="utf-8")
    assert repo.hash_text(text) == repo.hash_file(path)
```

```python
# tests/unit/infrastructure/test_json_section_repository.py — ADD to existing file
def test_write_section_creates_sections_dir_and_writes_file(workspace, repo):
    repo.write_section("doc-1", 1, "introduccion", "---\n{}\n---\n# Introducción\n")
    path = workspace.doc_root("doc-1") / "sections" / "001-introduccion.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "---\n{}\n---\n# Introducción\n"


def test_write_section_overwrites_existing_file(workspace, repo):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    path = sections_dir / "002-objetivos.md"
    path.write_text("vieja version", encoding="utf-8")
    repo.write_section("doc-1", 2, "objetivos", "nueva version")
    assert path.read_text(encoding="utf-8") == "nueva version"


def test_write_section_path_matches_section_path(workspace, repo):
    repo.write_section("doc-1", 3, "metodologia", "contenido")
    expected_path = repo.section_path("doc-1", 3, "metodologia")
    assert expected_path.read_text(encoding="utf-8") == "contenido"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/test_json_evidence_repository.py tests/unit/infrastructure/test_json_section_repository.py -v`
Expected: FAIL with `AttributeError: 'JsonEvidenceRepository' object has no attribute 'hash_text'` (and similarly `'JsonSectionRepository' object has no attribute 'write_section'`).

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/infrastructure/persistence/json_evidence_repository.py — ADD method to existing class
    def hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
```

```python
# src/docs/infrastructure/persistence/json_section_repository.py — ADD method to existing class
    def write_section(self, doc_id: str, order: int, section_id: str, raw_text: str) -> None:
        path = self.section_path(doc_id, order, section_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw_text, encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/test_json_evidence_repository.py tests/unit/infrastructure/test_json_section_repository.py -v`
Expected: PASS. `test_json_evidence_repository.py`: 14 pre-existing (Slice 4) + 2 new = 16. `test_json_section_repository.py`: 9 pre-existing (Slice 5) + 3 new = 12.

- [ ] **Step 5: Commit**

```bash
git add src/docs/infrastructure/persistence/json_evidence_repository.py src/docs/infrastructure/persistence/json_section_repository.py tests/unit/infrastructure/test_json_evidence_repository.py tests/unit/infrastructure/test_json_section_repository.py
git commit -m "feat(infrastructure): implement hash_text on JsonEvidenceRepository and write_section on JsonSectionRepository"
```

---

### Task 4: `EvidenceService.rules_hash` / `contract_hash` / `manifest_hash`

**Files:**
- Modify: `src/docs/application/evidence.py`
- Modify: `tests/integration/test_evidence_service.py`

**Interfaces:**
- Consumes: `EvidenceRepository` (Task 2/3); `ManualHashFact`, `build_rules_hash_payload` (Task 1); existing `EvidenceService.build_rules` (Slice 4, untouched).
- Produces: three new `EvidenceService` methods:
  - `rules_hash(self, config: dict[str, Any]) -> str`
  - `contract_hash(self, config: dict[str, Any], section_id: str) -> str`
  - `manifest_hash(self, path_value: str | None) -> str`

**Exact orchestration (verbatim from legacy, now expressed via the port):**

`rules_hash`:
1. `rules_path = Path(config["paths"]["rules_manifest"])`.
2. If `self.repository.file_exists(rules_path)`: return `self.repository.hash_file(rules_path)` — **stop here, do not read any other config fields** (legacy parity: this branch never touches `manual_dir`/`section_contracts`/etc.).
3. Else: `manual_dir_str = config["paths"].get("manual_dir")`; if truthy and `self.repository.file_exists(Path(manual_dir_str))`, build `manual_files = [ManualHashFact(path=path.resolve().as_posix(), sha256=self.repository.hash_file(path)) for path in self.repository.list_manual_files(Path(manual_dir_str))]` (reuses Slice 4's existing `list_manual_files`/`hash_file` — no new port method needed for this branch); else `manual_files = []`.
4. `payload = build_rules_hash_payload(manual_files=manual_files, section_contracts=config.get("section_contracts", {}), format=config.get("format", {}), apa7=config.get("apa7", {}), structure=config.get("structure", []), preliminaries=config.get("preliminaries", {}))`.
5. Return `self.repository.hash_json(payload)`.

`contract_hash`:
1. Return `self.repository.hash_json(config.get("section_contracts", {}).get(section_id, {}))`.

`manifest_hash`:
1. If not `path_value`: return `""`.
2. `path = Path(path_value)`.
3. Return `self.repository.hash_file(path) if self.repository.file_exists(path) else ""`.

**Why `_hash_files`'s `sorted(Path(p) for p in paths)` collapses to `list_manual_files`'s existing sorted glob:** legacy's `_hash_files` takes an arbitrary iterable and sorts it; its only call site in `rules_hash` passes `Path(manual_dir).glob("*.md")` — the exact same glob `EvidenceRepository.list_manual_files` already performs (sorted `*.md` glob, Slice 4 Task 2). No new port method is needed for this call site; the service reuses `list_manual_files` directly, exactly as `EvidenceService.build_rules` already does for its own manual-file loop.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_evidence_service.py — ADD to existing file (uses existing `service`/`_config` fixtures)
import hashlib
import json


def test_rules_hash_returns_file_hash_when_manifest_exists(tmp_path, service):
    config = _config(tmp_path)
    rules_path = service.build_rules(config)  # creates the manifest on disk
    expected = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    assert service.rules_hash(config) == expected


def test_rules_hash_ignores_other_config_fields_when_manifest_exists(tmp_path, service):
    config = _config(tmp_path, section_contracts={"intro": {"title": "Should not matter"}})
    rules_path = service.build_rules(config)
    expected = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    assert service.rules_hash(config) == expected


def test_rules_hash_falls_back_to_synthesized_payload_when_manifest_absent(tmp_path, service):
    config = _config(tmp_path)  # rules_manifest never built
    from pathlib import Path

    manual_dir = Path(config["paths"]["manual_dir"])
    (manual_dir / "00-intro.md").write_text("# Intro", encoding="utf-8")
    result = service.rules_hash(config)
    manual_path = (manual_dir / "00-intro.md").resolve().as_posix()
    manual_sha = hashlib.sha256((manual_dir / "00-intro.md").read_bytes()).hexdigest()
    expected_payload = {
        "manual_dir": [{"path": manual_path, "sha256": manual_sha}],
        "section_contracts": {},
        "format": {},
        "apa7": {},
        "structure": [],
        "preliminaries": {},
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_rules_hash_fallback_with_missing_manual_dir_produces_empty_manual_list(tmp_path, service):
    config = _config(tmp_path, paths={"manual_dir": str(tmp_path / "does-not-exist")})
    result = service.rules_hash(config)
    expected_payload = {
        "manual_dir": [], "section_contracts": {}, "format": {}, "apa7": {}, "structure": [], "preliminaries": {},
    }
    expected = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert result == expected


def test_contract_hash_hashes_existing_contract(tmp_path, service):
    contracts = {"intro": {"title": "Introducción", "required_content": ["objetivo"]}}
    config = _config(tmp_path, section_contracts=contracts)
    expected = hashlib.sha256(
        json.dumps(contracts["intro"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert service.contract_hash(config, "intro") == expected


def test_contract_hash_hashes_empty_dict_when_section_unknown(tmp_path, service):
    config = _config(tmp_path)
    expected = hashlib.sha256(json.dumps({}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    assert service.contract_hash(config, "unknown") == expected


def test_manifest_hash_empty_string_when_path_value_falsy(service):
    assert service.manifest_hash(None) == ""
    assert service.manifest_hash("") == ""


def test_manifest_hash_empty_string_when_path_missing(tmp_path, service):
    assert service.manifest_hash(str(tmp_path / "missing.json")) == ""


def test_manifest_hash_returns_file_hash_when_path_exists(tmp_path, service):
    path = tmp_path / "source-manifest.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert service.manifest_hash(str(path)) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_evidence_service.py -v`
Expected: FAIL with `AttributeError: 'EvidenceService' object has no attribute 'rules_hash'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/evidence.py — ADD imports + methods to existing EvidenceService
from docs.domain.evidence import ManualFileFact, ManualHashFact, TraceabilityFact, build_manifest, build_rules_hash_payload
# (replaces the existing `from docs.domain.evidence import ManualFileFact, TraceabilityFact, build_manifest` import line)

# ... inside class EvidenceService, alongside the existing build_rules method:

    def rules_hash(self, config: dict[str, Any]) -> str:
        rules_path = Path(config["paths"]["rules_manifest"])
        if self.repository.file_exists(rules_path):
            return self.repository.hash_file(rules_path)

        manual_dir_str = config["paths"].get("manual_dir")
        manual_files: list[ManualHashFact] = []
        if manual_dir_str and self.repository.file_exists(Path(manual_dir_str)):
            for path in self.repository.list_manual_files(Path(manual_dir_str)):
                manual_files.append(
                    ManualHashFact(path=path.resolve().as_posix(), sha256=self.repository.hash_file(path))
                )

        payload = build_rules_hash_payload(
            manual_files=manual_files,
            section_contracts=config.get("section_contracts", {}),
            format=config.get("format", {}),
            apa7=config.get("apa7", {}),
            structure=config.get("structure", []),
            preliminaries=config.get("preliminaries", {}),
        )
        return self.repository.hash_json(payload)

    def contract_hash(self, config: dict[str, Any], section_id: str) -> str:
        section_contracts = config.get("section_contracts", {})
        return self.repository.hash_json(section_contracts.get(section_id, {}))

    def manifest_hash(self, path_value: str | None) -> str:
        if not path_value:
            return ""
        path = Path(path_value)
        return self.repository.hash_file(path) if self.repository.file_exists(path) else ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_evidence_service.py -v`
Expected: PASS. 11 pre-existing (Slice 4) + 9 new = 20.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/evidence.py tests/integration/test_evidence_service.py
git commit -m "feat(application): add EvidenceService.rules_hash/contract_hash/manifest_hash"
```

---

### Task 5: `ReviewService.stamp_section`

**Files:**
- Modify: `src/docs/application/review.py`
- Modify: `tests/integration/test_review_service.py`

**Interfaces:**
- Consumes: `SectionRepository` (Task 2/3, now with `write_section`); `apply_stamp`, `with_frontmatter` (Task 1); existing `ReviewService.review_document` (Slice 5, untouched); `Template`, `Section` (Slice 1/3).
- Produces: `ReviewService.stamp_section(self, doc_id: str, template: Template, section_id: str, authored_by: str, model: str = "", *, now: str) -> Path`.

**`now` is an explicit parameter, not computed inside the service:** legacy calls `datetime.now().isoformat(timespec="seconds")` directly inside `stamp_section`. Hiding a wall-clock read inside the service would make `ReviewService` untestable without monkeypatching `datetime`, and no other ported service in this codebase reaches for wall-clock time internally (`JsonEvidenceRepository.write_manifest`, the only prior call site that stamps a timestamp, does so in the *adapter*, where real I/O already lives — not in the *application* layer). Since `stamp_section` is an application-layer method, not an adapter method, the timestamp is supplied by the caller (the future CLI command, per the `tesina_harness.py` `command_stamp_section` call site) exactly as `build_section`'s caller will eventually supply `now` too. This keeps `ReviewService` deterministic and matches the "I/O-adjacent values are passed in, not computed" rule already established by Slice 4's `build_manifest`/`generated_at` and this slice's own `apply_stamp`/`body_hash` (Task 1).

**Exact orchestration (verbatim from legacy `stamp_section`, `tesina_harness.py` lines 3324–3339, now expressed via the port and Task 1's pure helpers):**

1. Resolve `section = next(s for s in template.sections if s.id == section_id)` — equivalent to legacy's `section_by_id(config, section_id)`; if no such section exists, let the `StopIteration`/lookup fail naturally (legacy's `section_by_id` itself raises on an unknown id — out of scope to re-derive that exact error message here since no prior slice ported `section_by_id`'s error text; a `KeyError`/`StopIteration` surfacing is acceptable parity for an internal precondition violation, not a user-facing validation path).
2. If not `self.repository.section_exists(doc_id, section.order, section.id)`: raise `FileNotFoundError` with a message naming the section path (mirrors legacy's `if not path.exists(): raise FileNotFoundError(...)`).
3. `metadata, body = self.repository.read_section(doc_id, section.order, section.id)`.
4. `body_hash = ...` computed via the repository's hashing — **note:** `SectionRepository` has no `hash_text` method (that lives on `EvidenceRepository`, Task 2); rather than adding a duplicate hashing primitive to `SectionRepository`, `body_hash` is computed with Python's `hashlib` directly inside `ReviewService` itself. This is the one deliberate exception to "all hashing goes through a port" in this slice — see Self-Review for the explicit judgment call and why it's preferable to either (a) injecting an `EvidenceRepository` into `ReviewService` just for one hash call, or (b) duplicating `hash_text` onto `SectionRepository`.
5. `new_metadata = apply_stamp(metadata, section.id, section.title, body, body_hash, authored_by, model, now)`.
6. `raw_text = with_frontmatter(body, new_metadata)`.
7. `self.repository.write_section(doc_id, section.order, section.id, raw_text)`.
8. Return `self.repository.section_path(doc_id, section.order, section.id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_review_service.py — ADD to existing file (uses existing `workspace`/`service`/`_template`/`_write_section` fixtures)
import json

import pytest

from docs.domain.models.template import Section


def test_stamp_section_raises_when_section_file_missing(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")


def test_stamp_section_sets_authored_by_and_body_hash(workspace, service):
    import hashlib

    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    text = result_path.read_text(encoding="utf-8")
    metadata_json = text.split("---\n")[1]
    metadata = json.loads(metadata_json)
    assert metadata["authored_by"] == "agent-x"
    assert metadata["stamped_at"] == "2026-06-21T00:00:00"
    assert metadata["body_hash"] == hashlib.sha256("# Introducción\n\nTexto.\n".encode("utf-8")).hexdigest()


def test_stamp_section_sets_model_when_provided(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section(
        "doc-1", template, "introduccion", "agent-x", model="opus", now="2026-06-21T00:00:00"
    )
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    assert json.loads(metadata_json)["model"] == "opus"


def test_stamp_section_synthesizes_metadata_when_file_has_no_frontmatter(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(workspace, "doc-1", 1, "introduccion", body="# Introducción\n\nSin metadata.\n", metadata=None)
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    metadata = json.loads(metadata_json)
    assert metadata["managed_by"] == "tesina-harness"
    assert metadata["schema"] == 3
    assert metadata["section_id"] == "introduccion"
    assert metadata["title"] == "Introducción"
    assert metadata["authored_by"] == "agent-x"


def test_stamp_section_preserves_unrelated_existing_metadata_fields(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion", "custom_field": "preserved"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    metadata_json = result_path.read_text(encoding="utf-8").split("---\n")[1]
    assert json.loads(metadata_json)["custom_field"] == "preserved"


def test_stamp_section_returns_section_path(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    written_path = _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nTexto.\n",
        metadata={"section_id": "introduccion"},
    )
    result_path = service.stamp_section("doc-1", template, "introduccion", "agent-x", now="2026-06-21T00:00:00")
    assert result_path == written_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_review_service.py -v`
Expected: FAIL with `AttributeError: 'ReviewService' object has no attribute 'stamp_section'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/application/review.py — ADD imports + method to existing ReviewService
import hashlib
from pathlib import Path

from docs.domain.sections import apply_stamp, infer_section_id_from_path, with_frontmatter
# (replaces the existing `from docs.domain.sections import infer_section_id_from_path` import line)

# ... inside class ReviewService, alongside the existing review_document method:

    def stamp_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        authored_by: str,
        model: str = "",
        *,
        now: str,
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        if not self.repository.section_exists(doc_id, section.order, section.id):
            path = self.repository.section_path(doc_id, section.order, section.id)
            raise FileNotFoundError(f"No existe la sección a sellar: {path}")

        metadata, body = self.repository.read_section(doc_id, section.order, section.id)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        new_metadata = apply_stamp(metadata, section.id, section.title, body, body_hash, authored_by, model, now)
        raw_text = with_frontmatter(body, new_metadata)
        self.repository.write_section(doc_id, section.order, section.id, raw_text)
        return self.repository.section_path(doc_id, section.order, section.id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_review_service.py -v`
Expected: PASS. 8 pre-existing (Slice 5) + 6 new = 14.

- [ ] **Step 5: Commit**

```bash
git add src/docs/application/review.py tests/integration/test_review_service.py
git commit -m "feat(application): add ReviewService.stamp_section replacing legacy stamp_section"
```

---

## Full suite check (run after Task 5)

```bash
uv run pytest -W error -q
```

Expected: all tests pass. Baseline 283 (Slices 1–5) plus this slice's new tests:
- Task 1: 3 (`test_evidence.py`) + 7 (`test_sections.py`) = 10
- Task 3: 2 (`test_json_evidence_repository.py`) + 3 (`test_json_section_repository.py`) = 5
- Task 4: 9 (`test_evidence_service.py`)
- Task 5: 6 (`test_review_service.py`)

Total new tests: 10 + 5 + 9 + 6 = 30. **Expected final count: 283 + 30 = 313 passed**, zero warnings.

(Task 2 adds no tests, per established Protocol-extension precedent from Slices 4/5.)

---

## Self-Review

- **Spec coverage (legacy hash/provenance functions named in this slice's scope):**
  - `rules_hash` ✅ Task 1 (pure payload assembly via `build_rules_hash_payload`) + Task 4 (service orchestration, two-branch file-exists short-circuit preserved verbatim).
  - `contract_hash` ✅ Task 4 — trivial `hash_json` wrapper, permissive `.get(..., {})` fallback preserved.
  - `manifest_hash` ✅ Task 4 — three-way short-circuit (`falsy path_value` / `non-existent path` / `existing path`) preserved, both non-hash branches returning `""` exactly as legacy does.
  - `_hash_files` ✅ folded into Task 4's `rules_hash` fallback branch via the existing `list_manual_files` port method (Slice 4) — confirmed its only call site's glob (`Path(manual_dir).glob("*.md")`, sorted) is identical to what `list_manual_files` already does; no new port method needed, no behavior gap.
  - `sha256_text` ✅ Task 2/3, as the new `hash_text` port method/adapter implementation — the one missing hashing primitive this slice needed beyond Slice 4's existing `hash_file`/`hash_json`.
  - `stamp_section` ✅ Task 1 (pure `apply_stamp`/`with_frontmatter`/`default_section_metadata`) + Task 2/3 (`SectionRepository.write_section` port/adapter) + Task 5 (service orchestration) — every one of the five legacy steps (raise-if-missing, synthesize-default-metadata-if-empty, always-set-`authored_by`, conditionally-set-`model`, always-overwrite-`body_hash`-and-`stamped_at`) ported with an explicit test pinning each branch.
- **Confirmed exclusions (explicit judgment calls, not silent gaps):**
  1. **`source_hash` and `prompt_hash` excluded entirely.** Both depend on project-config path keys (`context_dir`, `prompts_dir`) that have no representation anywhere in this codebase's ported domain model. `source_hash` also reads `config["sections"]` directly as a raw list of dicts, a shape this codebase has replaced with the typed `Template.sections: list[Section]` — porting `source_hash` verbatim would require either reintroducing an untyped sections list (regressing Slice 1/3's typed model) or inventing a new conversion with no legacy precedent to verify against. `prompt_hash`'s `prompts_dir` concept has zero prior-slice context (`progress.md` never mentions a prompts subsystem). Porting either now would be speculative modeling — inventing a `context_dir`/`prompts_dir` config shape with no consumer beyond the hash function itself — which the project's own conventions (see Slice 4 Self-Review's `ProjectConfig` deferral) explicitly reject as out of scope until a real consumer needs it. Deferred to whichever future slice actually ports the context-file-hashing or prompts subsystem.
  2. **`build_section` excluded entirely.** Verified directly against `tesina_harness.py` lines 1157–1207: it depends on `render_fact_ledger`, `render_section_draft`, `load_context`/`load_context_for`, and (transitively) `source_hash`/`prompt_hash` — none of which exist in this codebase. This is not primarily a hashing concern; it's an LLM-prompt-driven section-scaffolding/generation subsystem that happens to also stamp provenance metadata using hashes. Slice 5's Self-Review already flagged `build_section` as deferred pending exactly this slice's hash functions — but having now read `build_section` directly (not just `stamp_section`), it's clear the hash functions alone are insufficient to port it; `render_fact_ledger`/`render_section_draft`/`load_context_for` are themselves substantial, undefined-in-this-codebase subsystems. Re-deferred, with this additional finding documented so the next slice doesn't assume "Slice 6 unblocked `build_section`" — it only unblocked the *hashing* half, not the *rendering* half.
  3. **`generated_metadata_changed` (the helper `build_section` uses to decide whether to rewrite an existing managed section) excluded.** It is `build_section`-only — no other call site — and ports trivially once `build_section` itself is in scope; including it now with no caller would be dead code.
  4. **`run_doctor`/`verify_all`/CLI commands (`command_doctor`, `command_build_section`, `command_verify`, `command_stamp_section`) excluded**, confirmed via direct read (`tesina_harness.py` lines 2185–2270, 3307–3321, 3355+). `run_doctor` reads `rules_manifest`'s mere existence (already covered by Slice 3's `review_rules` taking `manifest_exists`/`manifest_size` as caller-supplied facts) plus a long list of external-tool checks (`pandoc`, `libreoffice`, `pypdfium2`, `poppler`) entirely unrelated to hashing — explicitly out of scope, CLI-layer concern per `progress.md`'s repeated "Slice 10 CLI" deferral marker. `verify_all` composes `review_rules` + `review_document` (both already ported) + a DOCX-rendering/QA pipeline (`format_audit_docx`, `qa_docx`) that is a separate, large, unported subsystem — not a hashing concern, not pulled in. All four `command_*` functions are argparse-glue calling into functions already covered or already excluded above.
- **Judgment call — `ReviewService.stamp_section` computes its own `hashlib.sha256` instead of injecting `EvidenceRepository`:** documented inline in Task 5. The alternative (giving `ReviewService` a second constructor dependency on `EvidenceRepository` purely to reach `hash_text`, or duplicating `hash_text` as a second method on `SectionRepository`) was rejected: the first muddies `ReviewService`'s single-port dependency shape that Slice 5 established; the second creates two near-identical hashing primitives living on two different ports for no behavioral reason. A single inline `hashlib.sha256(...).hexdigest()` call, identical to the one already inlined in Task 1's test assertions and in `JsonEvidenceRepository.hash_text`'s implementation, is the smallest correct option. Flagged here explicitly as a deliberate exception to "always hash through a port," not an oversight.
- **Judgment call — `apply_stamp`'s unused `body` parameter:** documented inline in Task 1. Kept for call-site self-documentation; an implementer could reasonably argue for dropping it. Flagged so a future reviewer doesn't "clean it up" without re-reading this rationale.
- **Placeholder scan:** no TBD/TODO/elisions; every Step 1/Step 3 across all 5 tasks shows complete, runnable code. Task 2 has no Step 1/Step 2 test code by design (bare `Protocol` extension, no independently-testable behavior), consistent with Slice 4/5 Task 2 precedent.
- **Type consistency:** `ManualHashFact`/`build_rules_hash_payload` (Task 1) flow only into `EvidenceService.rules_hash` (Task 4), never touching `build_manifest`/`ManualFileFact`/`EvidenceService.build_rules` (Slice 4, confirmed untouched by this slice — Task 4 only adds a new import name to the existing import line, no existing line is rewritten). `apply_stamp`/`with_frontmatter`/`default_section_metadata` (Task 1) flow only into `ReviewService.stamp_section` (Task 5), never touching `review_document`/`review_section_text` (Slice 5, confirmed untouched). One direction of dependency throughout (`application → domain` + `application → port`; `infrastructure → port` via structural typing), no task reaches back into an earlier task's internals beyond appending new methods to already-existing classes.
- **Test count verification method:** every test count claim above (Task 1: 3 + 7; Task 3: 2 + 3; Task 4: 9; Task 5: 6; total 30; final 313) was produced by writing out each Step 1 code block in full above and then directly counting `def test_` occurrences in each block by eye, cross-checked a second time by counting again after the fact — not estimated. Per-file breakdown: `test_evidence.py` Task 1 block has 3 `def test_` (`test_build_rules_hash_payload_assembles_expected_keys`, `test_build_rules_hash_payload_empty_inputs`, `test_build_rules_hash_payload_preserves_manual_files_order`). `test_sections.py` Task 1 block has 7 (`test_with_frontmatter_formats_metadata_and_body`, `test_default_section_metadata_shape`, `test_apply_stamp_synthesizes_default_metadata_when_empty`, `test_apply_stamp_preserves_existing_metadata_fields`, `test_apply_stamp_sets_model_when_provided`, `test_apply_stamp_empty_model_does_not_delete_existing_model_key`, `test_apply_stamp_always_overwrites_body_hash_and_stamped_at`). `test_json_evidence_repository.py` Task 3 block has 2 (`test_hash_text_matches_raw_sha256_of_utf8_bytes`, `test_hash_text_matches_hash_file_for_same_bytes`). `test_json_section_repository.py` Task 3 block has 3 (`test_write_section_creates_sections_dir_and_writes_file`, `test_write_section_overwrites_existing_file`, `test_write_section_path_matches_section_path`). `test_evidence_service.py` Task 4 block has 9 (`test_rules_hash_returns_file_hash_when_manifest_exists`, `test_rules_hash_ignores_other_config_fields_when_manifest_exists`, `test_rules_hash_falls_back_to_synthesized_payload_when_manifest_absent`, `test_rules_hash_fallback_with_missing_manual_dir_produces_empty_manual_list`, `test_contract_hash_hashes_existing_contract`, `test_contract_hash_hashes_empty_dict_when_section_unknown`, `test_manifest_hash_empty_string_when_path_value_falsy`, `test_manifest_hash_empty_string_when_path_missing`, `test_manifest_hash_returns_file_hash_when_path_exists`). `test_review_service.py` Task 5 block has 6 (`test_stamp_section_raises_when_section_file_missing`, `test_stamp_section_sets_authored_by_and_body_hash`, `test_stamp_section_sets_model_when_provided`, `test_stamp_section_synthesizes_metadata_when_file_has_no_frontmatter`, `test_stamp_section_preserves_unrelated_existing_metadata_fields`, `test_stamp_section_returns_section_path`). Sum: 3+7+2+3+9+6 = 30. Baseline 283 + 30 = 313, matching the "Full suite check" section above exactly — written to avoid the prose/code test-count mismatch documented as a recurring bug in Slices 3 and 4's progress log.
