# Slice 3 — Rules + Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the legacy review surfaces (`review_section_contract`, `review_apa7_text`, `review_section`, `review_rules`, `review_cross_consistency`) into pure, I/O-free domain functions — the highest test-value slice per the design doc — together with the markdown text utilities and APA7 citation/reference extraction they depend on, and the `Issue`/`ReviewResult` value objects they produce. No filesystem access happens inside any function added in this slice; every I/O touchpoint (manifest existence/size, section file contents) is resolved by the caller and passed in as plain data.

**Architecture:** Pragmatic hexagonal, same shape as Slices 1–2. Everything in this slice lives under `domain/` and is pure: no `Path.read_text`, no `Path.exists()`, no `subprocess`, no `python-docx`. `domain/review.py` holds the `Issue`/`ReviewResult` value objects. `domain/markdown_text.py` holds text-transform utilities with no awareness of APA, contracts, or templates. `domain/apa.py` holds citation/reference extraction, depending only on `markdown_text.py`. `domain/models/template.py` is extended (not replaced) with typed config sub-models so `review_rules`/`review_section_contract` stop reading raw dicts. `domain/rules.py` holds the five review functions themselves, composing the above. Nothing in this slice imports from `application`, `infrastructure`, or `cli`.

**Tech Stack:** Python ≥3.11, Pydantic v2 (extending Slice 1's `Template`/`SectionContract` models), pytest, regex-based text processing (no markdown library dependency, matching legacy).

## Global Constraints

- Python requires-python: `>=3.11` (already set).
- `src/` layout; package root is `src/docs/`.
- Dependency direction: `application → domain`; `infrastructure → domain`. Every module added in this slice (`domain/review.py`, `domain/markdown_text.py`, `domain/apa.py`, `domain/rules.py`) imports nothing from `application`, `infrastructure`, or `cli`.
- **No I/O in this slice.** Legacy `review_rules` reads `rules_path.exists()`/`rules_path.stat().st_size` and legacy `review_section`/`review_document` read section files from disk. Every such touchpoint is replaced by a plain parameter (`manifest_exists: bool`, `manifest_size: int`, `text: str`, `section_bodies: dict[str, str]`) supplied by the caller. The caller (a future `application/review.py`, out of scope for this slice) is responsible for doing the actual reads.
- **Excluded from this slice (deferred to Slice 4 — Evidence):** `build_rules`'s manifest-writing logic — hashing `manual_dir/*.md` files, building the `traceability` list (manual/example PDF + extracted-dir hashing), `write_json_manifest`, and `contract_hash`/`sha256_json`. These are evidence-collection concerns, not review concerns, and Slice 4's scope is explicitly "collect sources/issues/code, build ledger."
- **Verbatim parity over modeling purity.** Every Issue code/message/regex in this plan is copied character-for-character from the legacy `tesina_harness.py` functions of the same name. Where legacy has an inconsistency (e.g. the `required_content` severity asymmetry in Task 5), it is preserved and called out in a code comment — never "fixed" silently.
- **One exception — `pending_allowed_in_draft` default.** Legacy's `contract.get("pending_allowed_in_draft", True)` treats an absent key as permissive. Slice 1's `SectionContract.pending_allowed_in_draft` model field currently defaults to `False`. This is a parity bug, not a legacy quirk to preserve, and Task 4 fixes the model default to `True`.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## File Structure

- `src/docs/domain/review.py` — `Issue`, `ReviewResult`.
- `src/docs/domain/markdown_text.py` — `split_frontmatter`, `clean_markdown_text`, `strip_frontmatter_and_markdown`, `extract_markdown_headings`, `normalize_heading`, `normalize_author_key`, `normalize_for_sort`.
- `src/docs/domain/apa.py` — `extract_apa_citations`, `extract_references_block`, `extract_reference_entries`, `citation_author_key`, `reference_author_key`.
- `src/docs/domain/models/template.py` (modified) — adds `LengthSpec`, `Apa7Config`, `StrictPolicyBlock`, `StrictPolicy` models; extends `SectionContract` and `Template`; fixes `pending_allowed_in_draft` default.
- `src/docs/domain/rules.py` — `requirement_present`, `review_section_contract`, `review_apa7_text`, `review_section_text`, `review_rules`, `review_cross_consistency`.
- `tests/unit/domain/test_review.py`
- `tests/unit/domain/test_markdown_text.py`
- `tests/unit/domain/test_apa.py`
- `tests/unit/domain/models/test_template.py` (appended)
- `tests/unit/domain/test_rules.py`

---

### Task 1: Issue + ReviewResult domain value objects

**Files:**
- Create: `src/docs/domain/review.py`
- Test: `tests/unit/domain/test_review.py`

**Interfaces:**
- Produces:
  - `Issue` frozen dataclass: `severity: str, message: str, code: str = ""`, with `to_dict() -> dict[str, str]`.
  - `ReviewResult` frozen dataclass: `issues: list[Issue]`, with `passed` property (`True` iff no issue has `severity == "error"`), `to_markdown() -> str`, `to_dict() -> dict[str, object]`.

Note: this duplicates the shape of the existing `domain/models/result.py` (`Issue`/`ReviewResult` with a `Severity` str-enum), which was added in an earlier slice for a different purpose (`DoctorResult`-adjacent). This slice intentionally introduces a **separate, plain-string-severity** `Issue`/`ReviewResult` pair in `domain/review.py` because the legacy review functions (Tasks 5–9) use bare strings (`"error"`/`"warning"`) for severity, not an enum, and mixing the two would force every Task 5–9 call site to wrap/unwrap a `Severity` enum that legacy never had. This is a deliberate scope decision — see Self-Review.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_review.py
from docs.domain.review import Issue, ReviewResult


def test_issue_default_code_is_empty_string():
    issue = Issue(severity="error", message="Algo falló.")
    assert issue.code == ""


def test_issue_to_dict():
    issue = Issue(severity="warning", message="Cuidado.", code="some.code")
    assert issue.to_dict() == {"severity": "warning", "message": "Cuidado.", "code": "some.code"}


def test_review_result_passed_true_when_no_error():
    result = ReviewResult(issues=[Issue(severity="warning", message="x")])
    assert result.passed is True


def test_review_result_passed_false_when_any_error():
    result = ReviewResult(
        issues=[Issue(severity="warning", message="x"), Issue(severity="error", message="y")]
    )
    assert result.passed is False


def test_review_result_passed_true_when_empty():
    result = ReviewResult(issues=[])
    assert result.passed is True


def test_to_markdown_empty_issues():
    result = ReviewResult(issues=[])
    assert result.to_markdown() == "# Revisión\n\nSin hallazgos."


def test_to_markdown_with_issues_uppercases_severity_and_omits_code():
    result = ReviewResult(
        issues=[
            Issue(severity="error", message="Falta título.", code="structure.missing_title"),
            Issue(severity="warning", message="Término subjetivo.", code="voice.subjective_term"),
        ]
    )
    assert result.to_markdown() == (
        "# Revisión\n\n"
        "- ERROR: Falta título.\n"
        "- WARNING: Término subjetivo."
    )


def test_to_dict():
    result = ReviewResult(issues=[Issue(severity="error", message="x", code="c.code")])
    assert result.to_dict() == {
        "passed": False,
        "issues": [{"severity": "error", "message": "x", "code": "c.code"}],
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_review.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.review`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/review.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    severity: str
    message: str
    code: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "message": self.message, "code": self.code}


@dataclass(frozen=True)
class ReviewResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_markdown(self) -> str:
        if not self.issues:
            return "# Revisión\n\nSin hallazgos."
        lines = ["# Revisión", ""]
        for issue in self.issues:
            lines.append(f"- {issue.severity.upper()}: {issue.message}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "issues": [issue.to_dict() for issue in self.issues]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_review.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/review.py tests/unit/domain/test_review.py
git commit -m "feat(domain): add Issue and ReviewResult value objects"
```

---

### Task 2: Markdown text utilities

**Files:**
- Create: `src/docs/domain/markdown_text.py`
- Test: `tests/unit/domain/test_markdown_text.py`

**Interfaces:**
- Produces:
  - `split_frontmatter(raw_text: str) -> tuple[dict, str]`
  - `clean_markdown_text(text: str) -> str`
  - `strip_frontmatter_and_markdown(text: str) -> str`
  - `extract_markdown_headings(text: str) -> list[str]`
  - `normalize_heading(text: str) -> str`
  - `normalize_author_key(value: str) -> str`
  - `normalize_for_sort(value: str) -> str`

`split_frontmatter`: legacy frontmatter is a leading `---\n<JSON>\n---\n` block (JSON, not YAML). If the text doesn't start with `---\n`, or no closing `\n---\n` is found, or the JSON fails to parse, return `({}, raw_text)` unchanged.

`extract_markdown_headings` in this slice returns `list[str]` of cleaned heading text only (the legacy function returns `list[dict]` with `level`+`text`; this slice only needs the text for downstream callers in Tasks 5–9 — `level` is dropped as an explicit simplification since no Task 5–9 function reads it).

`normalize_heading`: transliterate accented Spanish chars via `str.maketrans`, then `.upper().strip()` (legacy uppercases — this is a normalization key, not a display heading).

`normalize_author_key`: `normalize_heading(value).lower()`, then collapse non-alphanumeric runs to a single space via regex, then strip.

`normalize_for_sort`: `normalize_author_key(value) or value.lower()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_markdown_text.py
from docs.domain.markdown_text import (
    clean_markdown_text,
    extract_markdown_headings,
    normalize_author_key,
    normalize_for_sort,
    normalize_heading,
    split_frontmatter,
    strip_frontmatter_and_markdown,
)


def test_split_frontmatter_parses_json_block():
    text = '---\n{"section_id": "intro"}\n---\nCuerpo.\n'
    metadata, body = split_frontmatter(text)
    assert metadata == {"section_id": "intro"}
    assert body == "Cuerpo.\n"


def test_split_frontmatter_no_block_returns_empty_metadata():
    text = "Solo cuerpo, sin frontmatter."
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_split_frontmatter_unclosed_block_returns_unchanged():
    text = "---\n{not closed"
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_split_frontmatter_invalid_json_returns_unchanged():
    text = "---\nnot json\n---\nCuerpo.\n"
    metadata, body = split_frontmatter(text)
    assert metadata == {}
    assert body == text


def test_clean_markdown_text_strips_markers_and_collapses_whitespace():
    text = "**bold** *italic* `code`   with   spaces"
    assert clean_markdown_text(text) == "bold italic code with spaces"


def test_clean_markdown_text_strips_backslashes():
    assert clean_markdown_text("a\\*b") == "a*b"


def test_clean_markdown_text_strips_leading_trailing_pipe_and_whitespace():
    assert clean_markdown_text("  | texto |  ") == "texto"


def test_strip_frontmatter_and_markdown_removes_fenced_code_inline_code_images_links_structure():
    text = (
        "---\n{}\n---\n"
        "# Título\n"
        "```\ncode block\n```\n"
        "Texto con `inline` y ![alt](img.png) y [link](http://x) y > cita y *en* _fasis_ y #tag y | tabla |\n"
    )
    result = strip_frontmatter_and_markdown(text)
    assert "code block" not in result
    assert "inline" in result
    assert "img.png" not in result
    assert "link" not in result
    assert "http://x" not in result
    assert "#" not in result
    assert "*" not in result
    assert "_" not in result
    assert ">" not in result
    assert "|" not in result


def test_extract_markdown_headings_all_levels_multiline():
    text = "# Uno\nTexto\n## Dos\n### Tres\nNo es heading"
    assert extract_markdown_headings(text) == ["Uno", "Dos", "Tres"]


def test_extract_markdown_headings_empty_when_none():
    assert extract_markdown_headings("Solo texto.") == []


def test_normalize_heading_transliterates_accents_and_uppercases():
    assert normalize_heading("Introducción") == "INTRODUCCION"
    assert normalize_heading("áéíóúñü") == "AEIOUNU"


def test_normalize_author_key_lowercases_and_collapses_non_alnum():
    assert normalize_author_key("García, M.") == "garcia m"


def test_normalize_for_sort_falls_back_to_lower_when_key_empty():
    assert normalize_for_sort("123") == "123"
    assert normalize_for_sort("García") == "garcia"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_markdown_text.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.markdown_text`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/markdown_text.py
from __future__ import annotations

import json
import re

_ACCENT_TRANSLATION = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")

_BOLD_RE = re.compile(r"\*\*(.*?)\*\*")
_ITALIC_RE = re.compile(r"\*(.*?)\*")
_CODE_RE = re.compile(r"`(.*?)`")
_WHITESPACE_RE = re.compile(r"\s+")

_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_STRUCTURE_RE = re.compile(r"[*_#>|-]+")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def split_frontmatter(raw_text: str) -> tuple[dict, str]:
    if not raw_text.startswith("---\n"):
        return {}, raw_text
    end = raw_text.find("\n---\n", 4)
    if end == -1:
        return {}, raw_text
    raw = raw_text[4:end].strip()
    body = raw_text[end + 5:]
    try:
        return json.loads(raw), body
    except json.JSONDecodeError:
        return {}, raw_text


def clean_markdown_text(text: str) -> str:
    text = text.replace("\\", "")
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip(" \t\r\n|")


def strip_frontmatter_and_markdown(text: str) -> str:
    _metadata, body = split_frontmatter(text)
    body = _FENCED_CODE_RE.sub(" ", body)
    body = _INLINE_CODE_RE.sub(r"\1", body)
    body = _IMAGE_RE.sub(" ", body)
    body = _LINK_RE.sub(" ", body)
    body = _STRUCTURE_RE.sub(" ", body)
    return body


def extract_markdown_headings(text: str) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            headings.append(clean_markdown_text(match.group(2)))
    return headings


def normalize_heading(text: str) -> str:
    return text.translate(_ACCENT_TRANSLATION).upper().strip()


def normalize_author_key(value: str) -> str:
    value = normalize_heading(value).lower()
    value = _NON_ALNUM_RE.sub(" ", value)
    return value.strip()


def normalize_for_sort(value: str) -> str:
    return normalize_author_key(value) or value.lower()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_markdown_text.py -v`
Expected: PASS (14 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/markdown_text.py tests/unit/domain/test_markdown_text.py
git commit -m "feat(domain): add markdown text utilities (frontmatter, cleaning, normalization)"
```

---

### Task 3: APA7 citation/reference extraction

**Files:**
- Create: `src/docs/domain/apa.py`
- Test: `tests/unit/domain/test_apa.py`

**Interfaces:**
- Consumes: `clean_markdown_text`, `normalize_author_key` (Task 2).
- Produces:
  - `extract_apa_citations(text: str) -> set[str]`
  - `extract_references_block(text: str) -> str`
  - `extract_reference_entries(text: str) -> list[str]`
  - `citation_author_key(citation: str) -> str`
  - `reference_author_key(entry: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_apa.py
from docs.domain.apa import (
    citation_author_key,
    extract_apa_citations,
    extract_reference_entries,
    extract_references_block,
    reference_author_key,
)


def test_extract_apa_citations_parenthetical():
    text = "Esto se sostiene (García, 2020) en la literatura."
    assert extract_apa_citations(text) == {"García, 2020"}


def test_extract_apa_citations_parenthetical_with_letter_suffix_and_extra_text():
    text = "Ver (García, 2020a, p. 5)."
    assert extract_apa_citations(text) == {"García, 2020a, p. 5"}


def test_extract_apa_citations_narrative():
    text = "García (2020) sostiene que esto es así."
    assert extract_apa_citations(text) == {"García, 2020"}


def test_extract_apa_citations_narrative_with_et_al():
    text = "García et al. (2020) sostienen que esto es así."
    assert extract_apa_citations(text) == {"García et al., 2020"}


def test_extract_apa_citations_combines_both_forms():
    text = "García (2020) sostiene (Pérez, 2019) que..."
    assert extract_apa_citations(text) == {"García, 2020", "Pérez, 2019"}


def test_extract_apa_citations_empty_when_none():
    assert extract_apa_citations("Sin citas aquí.") == set()


def test_extract_references_block_returns_text_after_last_matching_heading():
    text = (
        "# Intro\nTexto\n"
        "# REFERENCIAS BIBLIOGRÁFICAS\n"
        "García, A. (2020). Título. Editorial.\n"
    )
    block = extract_references_block(text)
    assert "García, A. (2020)" in block
    assert "# Intro" not in block


def test_extract_references_block_case_insensitive_and_plain_referencias():
    text = "## referencias\nPérez, B. (2019). Otro título.\n"
    block = extract_references_block(text)
    assert "Pérez, B. (2019)" in block


def test_extract_references_block_empty_when_no_heading():
    assert extract_references_block("Sin sección de referencias.") == ""


def test_extract_references_block_uses_last_match_when_multiple():
    text = (
        "# REFERENCIAS\nPrimera, A. (2018).\n"
        "# REFERENCIAS\nSegunda, B. (2019).\n"
    )
    block = extract_references_block(text)
    assert "Primera" not in block
    assert "Segunda" in block


def test_extract_reference_entries_filters_headings_pending_and_non_dated_lines():
    text = (
        "# REFERENCIAS\n"
        "PENDIENTE: completar referencias.\n"
        "## Subtítulo ignorado\n"
        "García, A. (2020). Título. Editorial.\n"
        "Línea sin fecha que debe ignorarse.\n"
        "Pérez, B. (n.d.). Otro título.\n"
    )
    entries = extract_reference_entries(text)
    assert entries == [
        "García, A. (2020). Título. Editorial.",
        "Pérez, B. (n.d.). Otro título.",
    ]


def test_extract_reference_entries_empty_when_no_references_block():
    assert extract_reference_entries("Sin referencias.") == []


def test_citation_author_key_strips_et_al_and_ampersand():
    assert citation_author_key("García et al., 2020") == "garcia"
    assert citation_author_key("García & Pérez, 2020") == "garcia"
    assert citation_author_key("García y Pérez, 2020") == "garcia"


def test_citation_author_key_simple():
    assert citation_author_key("García, 2020") == "garcia"


def test_reference_author_key_takes_text_before_first_paren_and_comma():
    assert reference_author_key("García, A. (2020). Título.") == "garcia"


def test_reference_author_key_handles_no_comma_before_paren():
    assert reference_author_key("García (2020). Título.") == "garcia"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_apa.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.apa`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/apa.py
from __future__ import annotations

import re

from docs.domain.markdown_text import clean_markdown_text, normalize_author_key

_PARENTHETICAL_RE = re.compile(r"\(([^()]*?,\s*(?:19|20)\d{2}[a-z]?[^()]*)\)")
_NARRATIVE_RE = re.compile(
    r"\b([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ'\-]+(?:\s+et\s+al\.)?)\s+\(((?:19|20)\d{2}[a-z]?)\)"
)
_REFERENCES_HEADING_RE = re.compile(
    r"^#+\s+REFERENCIAS(?:\s+BIBLIOGR[ÁA]FICAS)?\s*$", re.IGNORECASE | re.MULTILINE
)
_DATED_ENTRY_RE = re.compile(r"\((?:19|20)\d{2}|n\.d\.\)", re.IGNORECASE)
_ET_AL_RE = re.compile(r"\bet\s+al\.$", re.IGNORECASE)


def extract_apa_citations(text: str) -> set[str]:
    citations: set[str] = set()
    for match in _PARENTHETICAL_RE.finditer(text):
        citation = clean_markdown_text(match.group(1))
        if citation:
            citations.add(citation)
    for match in _NARRATIVE_RE.finditer(text):
        citations.add(f"{match.group(1)}, {match.group(2)}")
    return citations


def extract_references_block(text: str) -> str:
    matches = list(_REFERENCES_HEADING_RE.finditer(text))
    if not matches:
        return ""
    match = matches[-1]
    return text[match.end():]


def extract_reference_entries(text: str) -> list[str]:
    block = extract_references_block(text)
    entries: list[str] = []
    for line in block.splitlines():
        stripped = clean_markdown_text(line)
        if not stripped or stripped.startswith("#") or stripped.upper().startswith("PENDIENTE"):
            continue
        if _DATED_ENTRY_RE.search(stripped):
            entries.append(stripped)
    return entries


def citation_author_key(citation: str) -> str:
    author_part = citation.split(",", 1)[0]
    author_part = _ET_AL_RE.sub("", author_part)
    author_part = author_part.split("&", 1)[0].split(" y ", 1)[0]
    return normalize_author_key(author_part)


def reference_author_key(entry: str) -> str:
    author_part = entry.split("(", 1)[0]
    author_part = author_part.split(",", 1)[0]
    return normalize_author_key(author_part)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_apa.py -v`
Expected: PASS (17 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/apa.py tests/unit/domain/test_apa.py
git commit -m "feat(domain): add APA7 citation and reference extraction"
```

---

### Task 4: Typed model extensions

**Files:**
- Modify: `src/docs/domain/models/template.py`
- Test: `tests/unit/domain/models/test_template.py` (append)

**Interfaces:**
- Produces (added to `template.py`):
  - `LengthSpec` model: `min_words: int | None = None, max_words: int | None = None, min_pages: int | None = None, max_pages: int | None = None, target_pages: int | None = None`, `extra="allow"`.
  - `Apa7Config` model: `enabled: bool = True, style: str = "APA 7", in_text_citation: str = "", requires_reference_for_each_citation: bool = True, requires_citation_for_each_reference: bool = True, reference_order: str = "alphabetical", reference_hanging_indent_cm: float = 1.27, direct_quote_requires_locator: bool = True, allowed_reference_heading: str = "REFERENCIAS"`, `extra="allow"`.
  - `StrictPolicyBlock` model: `allow_pending: bool = True, length_violations: str = "warning", missing_evidence: str = "warning", apa_violations: str = "warning"`, `extra="allow"`.
  - `StrictPolicy` model: `draft: StrictPolicyBlock = StrictPolicyBlock()`, `strict: StrictPolicyBlock = StrictPolicyBlock(allow_pending=False, length_violations="error", missing_evidence="error", apa_violations="error")`.
  - `SectionContract` gains: `length: LengthSpec = LengthSpec()`, `detect: dict[str, list[str]] = {}`.
  - **Parity fix:** `SectionContract.pending_allowed_in_draft` default changes from `False` to `True`.
  - `Template` gains: `apa7: Apa7Config = Apa7Config()`, `strict_policy: StrictPolicy = StrictPolicy()`.

Note on Pydantic v2 mutable defaults: `BaseModel` instances are safe as class-level default values (unlike plain dataclasses) because Pydantic deep-copies defaults per-instance — `Apa7Config()`/`StrictPolicyBlock()`/`LengthSpec()` as field defaults do not share state across `Template`/`SectionContract` instances.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/domain/models/test_template.py
from docs.domain.models.template import Apa7Config, LengthSpec, SectionContract, StrictPolicy, StrictPolicyBlock, Template


def test_section_contract_pending_allowed_in_draft_defaults_to_true():
    contract = SectionContract()
    assert contract.pending_allowed_in_draft is True


def test_section_contract_has_length_and_detect_defaults():
    contract = SectionContract()
    assert contract.length == LengthSpec()
    assert contract.detect == {}


def test_length_spec_all_optional_defaults_none():
    spec = LengthSpec()
    assert spec.min_words is None
    assert spec.max_words is None
    assert spec.min_pages is None
    assert spec.max_pages is None
    assert spec.target_pages is None


def test_apa7_config_defaults():
    config = Apa7Config()
    assert config.enabled is True
    assert config.style == "APA 7"
    assert config.in_text_citation == ""
    assert config.requires_reference_for_each_citation is True
    assert config.requires_citation_for_each_reference is True
    assert config.reference_order == "alphabetical"
    assert config.reference_hanging_indent_cm == 1.27
    assert config.direct_quote_requires_locator is True
    assert config.allowed_reference_heading == "REFERENCIAS"


def test_strict_policy_block_draft_defaults():
    block = StrictPolicyBlock()
    assert block.allow_pending is True
    assert block.length_violations == "warning"
    assert block.missing_evidence == "warning"
    assert block.apa_violations == "warning"


def test_strict_policy_default_draft_and_strict_blocks_differ():
    policy = StrictPolicy()
    assert policy.draft.allow_pending is True
    assert policy.draft.length_violations == "warning"
    assert policy.strict.allow_pending is False
    assert policy.strict.length_violations == "error"
    assert policy.strict.missing_evidence == "error"
    assert policy.strict.apa_violations == "error"


def test_template_has_apa7_and_strict_policy_defaults():
    template = Template(type="x", title="X")
    assert template.apa7 == Apa7Config()
    assert template.strict_policy.draft.allow_pending is True


def test_template_models_dont_share_mutable_default_state():
    a = Template(type="a", title="A")
    b = Template(type="b", title="B")
    a.apa7.enabled = False
    assert b.apa7.enabled is True


def test_section_contract_extra_fields_allowed():
    contract = SectionContract.model_validate({"title": "x", "custom_field": "y"})
    assert contract.model_extra["custom_field"] == "y"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/models/test_template.py -v`
Expected: FAIL with `ImportError: cannot import name 'Apa7Config'`.

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


class LengthSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    min_words: int | None = None
    max_words: int | None = None
    min_pages: int | None = None
    max_pages: int | None = None
    target_pages: int | None = None


class SectionContract(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = ""
    required_content: list[str] = []
    evidence_required: bool = False
    apa_required: bool = False
    # Parity fix: legacy reads `contract.get("pending_allowed_in_draft", True)` —
    # an absent key is permissive. The previous `False` default here was a parity
    # bug (see Slice 3 plan, Task 4) and is corrected to `True`.
    pending_allowed_in_draft: bool = True
    length: LengthSpec = LengthSpec()
    detect: dict[str, list[str]] = {}


class Apa7Config(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    style: str = "APA 7"
    in_text_citation: str = ""
    requires_reference_for_each_citation: bool = True
    requires_citation_for_each_reference: bool = True
    reference_order: str = "alphabetical"
    reference_hanging_indent_cm: float = 1.27
    direct_quote_requires_locator: bool = True
    allowed_reference_heading: str = "REFERENCIAS"


class StrictPolicyBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    allow_pending: bool = True
    length_violations: str = "warning"
    missing_evidence: str = "warning"
    apa_violations: str = "warning"


class StrictPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")
    draft: StrictPolicyBlock = StrictPolicyBlock()
    strict: StrictPolicyBlock = StrictPolicyBlock(
        allow_pending=False,
        length_violations="error",
        missing_evidence="error",
        apa_violations="error",
    )


class Template(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    project_defaults: dict = {}
    structure: list[dict] = []
    sections: list[Section] = []
    section_contracts: dict[str, SectionContract] = {}
    context_schema: ContextSchema = ContextSchema()
    apa7: Apa7Config = Apa7Config()
    strict_policy: StrictPolicy = StrictPolicy()

    @classmethod
    def from_json(cls, text: str) -> "Template":
        return cls.model_validate_json(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/models/test_template.py -v`
Expected: PASS (12 passed, including the 3 pre-existing tests from Slice 1).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/models/template.py tests/unit/domain/models/test_template.py
git commit -m "feat(domain): add Apa7Config/StrictPolicy/LengthSpec models, fix pending_allowed_in_draft default"
```

---

### Task 5: review_section_contract (pure)

**Files:**
- Create: `src/docs/domain/rules.py`
- Test: `tests/unit/domain/test_rules.py`

**Interfaces:**
- Consumes: `Issue` (Task 1); `strip_frontmatter_and_markdown`, `clean_markdown_text` (Task 2); `extract_apa_citations` (Task 3); `SectionContract`, `StrictPolicyBlock` (Task 4).
- Produces:
  - `requirement_present(requirement: str, plain: str, detect: dict[str, list[str]]) -> bool`
  - `review_section_contract(text: str, section_id: str, contract: SectionContract, strict_policy: StrictPolicyBlock, strict: bool) -> list[Issue]`

**Known legacy quirk — preserved verbatim, not fixed (see code comment in Step 3):** the word-count check and the `evidence_required`/`apa_required` checks resolve severity via `strict_policy.<field>` (defaulting to `"error" if strict else "warning"` only when the policy field itself is absent from config — here, since `StrictPolicyBlock` always has a concrete default, this collapses to "use `strict_policy.<field>` directly"). The `required_content` presence check, by contrast, uses the **raw `strict` boolean directly** (`"error" if strict else "warning"`), bypassing `strict_policy` entirely. This is a genuine legacy inconsistency — call sites configure `length_violations`/`missing_evidence`/`apa_violations` independently per draft/strict mode, but `missing_required` severity cannot be independently configured and always tracks the raw `strict` flag. Do not unify these.

`apa_required` check: calls `extract_apa_citations(text)` on the **raw** `text` parameter, while checking `"pendiente" not in plain` where `plain` is the cleaned/lowercased text. Mixing a raw-text extraction with a cleaned-text pending check is intentional legacy behavior (the raw text is needed because `clean_markdown_text` would have already stripped the `**`/`*` markers that don't affect APA citation regexes anyway, but legacy never bothered to clean text before this specific check) — preserve it.

Word count formula: `len(re.findall(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b", strip_frontmatter_and_markdown(text)))`.

`requirement_present`: if `detect.get(requirement)` is a non-empty list, candidates = that list; else candidates = `[requirement] + [w for w in requirement.split() if len(w) >= 4]` lowercased; present if any candidate (lowercased) is a substring of `plain`. Note legacy's exact tokenization is `re.split(r"\W+", requirement.lower())` filtered to `len(word) >= 4`, not `requirement.split()` — the plan uses the verbatim legacy regex split in Step 3 code (the prose above simplifies for readability; the code is authoritative).

Exact Issue codes/messages (verbatim Spanish, with legacy default-severity fallback baked in via `strict_policy`/`strict` as described above):
- `contract.length_below_min`: `` La sección `{section_id}` tiene {word_count} palabras; mínimo esperado: {min_words}. ``
- `contract.length_above_max`: `` La sección `{section_id}` tiene {word_count} palabras; máximo esperado: {max_words}. ``
- `contract.missing_required`: `` No se detecta contenido obligatorio de `{section_id}`: {joined_missing}. `` (`joined_missing = ", ".join(missing)`)
- `evidence.required`: `` `{section_id}` requiere evidencia o marcador PENDIENTE. ``
- `apa.required`: `` `{section_id}` requiere citas APA 7 o marcador PENDIENTE. ``

Evidence regex: `r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo|repositorio|c[oó]digo|manifest)\b"` against `plain`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/domain/test_rules.py
from docs.domain.models.template import SectionContract, StrictPolicyBlock
from docs.domain.rules import requirement_present, review_section_contract


def _policy(**overrides) -> StrictPolicyBlock:
    return StrictPolicyBlock(**overrides)


def test_requirement_present_uses_detect_candidates_when_provided():
    detect = {"metodología": ["enfoque cualitativo", "diseño de estudio"]}
    plain = "se utilizó un enfoque cualitativo para el análisis"
    assert requirement_present("metodología", plain, detect) is True


def test_requirement_present_false_when_detect_candidates_absent():
    detect = {"metodología": ["enfoque cualitativo"]}
    plain = "no se menciona nada relevante aquí"
    assert requirement_present("metodología", plain, detect) is False


def test_requirement_present_falls_back_to_requirement_words_when_no_detect():
    plain = "este texto menciona metodología explícitamente"
    assert requirement_present("metodología utilizada", plain, {}) is True


def test_requirement_present_false_when_no_match_and_no_detect():
    plain = "texto que no tiene relación alguna"
    assert requirement_present("metodología utilizada", plain, {}) is False


def test_review_section_contract_no_issues_when_contract_satisfied():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Sección\n\nEl objetivo de este trabajo es claro y está bien definido con suficiente texto."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert issues == []


def test_review_section_contract_length_below_min_uses_strict_policy_severity():
    contract = SectionContract(length={"min_words": 1000})
    text = "# Sección\n\nTexto corto."
    issues = review_section_contract(text, "intro", contract, _policy(length_violations="error"), strict=False)
    assert len(issues) == 1
    assert issues[0].code == "contract.length_below_min"
    assert issues[0].severity == "error"
    assert "mínimo esperado: 1000" in issues[0].message


def test_review_section_contract_length_above_max():
    contract = SectionContract(length={"max_words": 2})
    text = "# Sección\n\nuno dos tres cuatro cinco"
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    codes = [i.code for i in issues]
    assert "contract.length_above_max" in codes


def test_review_section_contract_missing_required_uses_raw_strict_not_strict_policy():
    contract = SectionContract(required_content=["metodología"])
    text = "# Sección\n\nTexto sin relación alguna."
    # strict_policy says "warning" for everything, but `strict=True` should still
    # force the missing_required issue to "error" — this is the legacy asymmetry.
    issues = review_section_contract(
        text, "intro", contract, _policy(length_violations="warning"), strict=True
    )
    missing = next(i for i in issues if i.code == "contract.missing_required")
    assert missing.severity == "error"
    assert "metodología" in missing.message


def test_review_section_contract_missing_required_joins_multiple_terms():
    contract = SectionContract(required_content=["objetivo", "metodología"])
    text = "# Sección\n\nTexto sin relación alguna en absoluto."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    missing = next(i for i in issues if i.code == "contract.missing_required")
    assert "objetivo, metodología" in missing.message


def test_review_section_contract_evidence_required_flags_missing_evidence():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nNo hay nada que lo respalde aquí."
    issues = review_section_contract(text, "intro", contract, _policy(missing_evidence="error"), strict=False)
    issue = next(i for i in issues if i.code == "evidence.required")
    assert issue.severity == "error"
    assert "requiere evidencia o marcador PENDIENTE" in issue.message


def test_review_section_contract_evidence_required_satisfied_by_pendiente_marker():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nEsto está PENDIENTE de completar."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "evidence.required" for i in issues)


def test_review_section_contract_evidence_required_satisfied_by_evidence_word():
    contract = SectionContract(evidence_required=True)
    text = "# Sección\n\nSe adjunta evidencia suficiente sobre el tema."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "evidence.required" for i in issues)


def test_review_section_contract_apa_required_flags_missing_citations():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nTexto sin ninguna cita bibliográfica aquí."
    issues = review_section_contract(text, "intro", contract, _policy(apa_violations="error"), strict=False)
    issue = next(i for i in issues if i.code == "apa.required")
    assert issue.severity == "error"
    assert "requiere citas APA 7" in issue.message


def test_review_section_contract_apa_required_satisfied_by_citation():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nEsto se sostiene (García, 2020) en la literatura."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "apa.required" for i in issues)


def test_review_section_contract_apa_required_satisfied_by_pendiente():
    contract = SectionContract(apa_required=True)
    text = "# Sección\n\nEsto está PENDIENTE de citar."
    issues = review_section_contract(text, "intro", contract, _policy(), strict=False)
    assert not any(i.code == "apa.required" for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: FAIL with `ModuleNotFoundError: docs.domain.rules`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/docs/domain/rules.py
from __future__ import annotations

import re

from docs.domain.apa import extract_apa_citations
from docs.domain.markdown_text import clean_markdown_text, strip_frontmatter_and_markdown
from docs.domain.models.template import SectionContract, StrictPolicyBlock
from docs.domain.review import Issue

_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b")
_EVIDENCE_RE = re.compile(
    r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo|repositorio|c[oó]digo|manifest)\b"
)
_REQUIREMENT_WORD_SPLIT_RE = re.compile(r"\W+")


def requirement_present(requirement: str, plain: str, detect: dict[str, list[str]]) -> bool:
    candidates = detect.get(requirement)
    if not candidates:
        words = [w for w in _REQUIREMENT_WORD_SPLIT_RE.split(requirement.lower()) if len(w) >= 4]
        candidates = [requirement] + words
    return any(str(candidate).lower() in plain for candidate in candidates)


def review_section_contract(
    text: str,
    section_id: str,
    contract: SectionContract,
    strict_policy: StrictPolicyBlock,
    strict: bool,
) -> list[Issue]:
    issues: list[Issue] = []
    plain = clean_markdown_text(text).lower()
    word_count = len(_WORD_RE.findall(strip_frontmatter_and_markdown(text)))

    length_severity = strict_policy.length_violations
    if contract.length.min_words and word_count < contract.length.min_words:
        issues.append(
            Issue(
                length_severity,
                f"La sección `{section_id}` tiene {word_count} palabras; "
                f"mínimo esperado: {contract.length.min_words}.",
                code="contract.length_below_min",
            )
        )
    if contract.length.max_words and word_count > contract.length.max_words:
        issues.append(
            Issue(
                length_severity,
                f"La sección `{section_id}` tiene {word_count} palabras; "
                f"máximo esperado: {contract.length.max_words}.",
                code="contract.length_above_max",
            )
        )

    missing = [
        requirement
        for requirement in contract.required_content
        if not requirement_present(requirement, plain, contract.detect)
    ]
    if missing:
        # Legacy quirk (intentional, not a bug): this check uses the raw `strict`
        # flag directly, NOT `strict_policy.missing_required` — there is no such
        # strict_policy field for this check in legacy. Every other check in this
        # function resolves severity via strict_policy; this one does not.
        severity = "error" if strict else "warning"
        issues.append(
            Issue(
                severity,
                f"No se detecta contenido obligatorio de `{section_id}`: {', '.join(missing)}.",
                code="contract.missing_required",
            )
        )

    if contract.evidence_required:
        has_pending = "pendiente" in plain
        has_evidence = bool(_EVIDENCE_RE.search(plain))
        if not has_pending and not has_evidence:
            issues.append(
                Issue(
                    strict_policy.missing_evidence,
                    f"`{section_id}` requiere evidencia o marcador PENDIENTE.",
                    code="evidence.required",
                )
            )

    if contract.apa_required and not extract_apa_citations(text) and "pendiente" not in plain:
        issues.append(
            Issue(
                strict_policy.apa_violations,
                f"`{section_id}` requiere citas APA 7 o marcador PENDIENTE.",
                code="apa.required",
            )
        )

    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "feat(domain): add review_section_contract preserving legacy severity asymmetry"
```

---

### Task 6: review_apa7_text (pure)

**Files:**
- Modify: `src/docs/domain/rules.py` (add `review_apa7_text`)
- Test: `tests/unit/domain/test_rules.py` (add cases)

**Interfaces:**
- Consumes: `Issue` (Task 1); `normalize_for_sort` (Task 2); `extract_apa_citations`, `extract_reference_entries`, `citation_author_key`, `reference_author_key` (Task 3); `StrictPolicyBlock` (Task 4).
- Produces: `review_apa7_text(text: str, apa7_enabled: bool, strict_policy: StrictPolicyBlock) -> list[Issue]`

**Gate asymmetry — documented, not fixed:** legacy's `review_apa7_text` reads `config.get("apa7", {}).get("enabled", True)` — defaulting to `True` when the config omits the key entirely. This is the opposite default from `review_rules` (Task 8), whose document-level APA gate (`if not config.get("apa7", {}).get("enabled")`) defaults to **falsy** (and thus to an error) when the key is absent. In this slice's typed-model world, `Template.apa7.enabled` always has a concrete value (`True` by the `Apa7Config` default — Task 4), so the asymmetry is no longer about a missing dict key; it now means: the caller decides what `apa7_enabled` to pass to `review_apa7_text`, but `review_rules` always reads `template.apa7.enabled` directly. The `apa7_enabled: bool` parameter here therefore exists so the call site keeps the same semantic gate behavior as legacy (typically `template.apa7.enabled`) without coupling `review_apa7_text` to `Template`.

Severity: `strict_policy.apa_violations`.

Logic order (verbatim):
1. `citations = extract_apa_citations(text)`, `references = extract_reference_entries(text)`.
2. If `citations and not references`: emit one `apa.no_reference_list` issue (`Hay citas APA en texto pero no hay lista de referencias detectable.`), then one `apa.citation_without_reference` issue per sorted citation (`` Cita sin referencia correspondiente: `{citation}`. ``).
3. If `references and not citations`: emit one `apa.reference_without_citation` issue per reference, in encountered order (`` Referencia sin cita correspondiente: `{entry[:90]}`. `` — note the 90-char truncation, not 80).
4. Reciprocity loop over citations (sorted): for each citation, compute `citation_author_key`; if the key is truthy AND `references` is non-empty AND no reference key fuzzy-matches (substring either direction) → emit `apa.citation_without_reference` (same message as step 2 — this can duplicate an issue already emitted in step 2 for the same citation when `references` was initially empty... but step 2's branch and step 4's matching condition are mutually exclusive on `references` truthiness, so no double-emission in practice; verified by the legacy code structure, preserve as-is).
5. Symmetric reciprocity loop over references: emit `apa.reference_without_citation` (same message/truncation as step 3) when no citation key fuzzy-matches.
6. Sort check: `if references and references != sorted(references, key=normalize_for_sort)` → `apa.references_not_sorted` (`Las referencias no están ordenadas alfabéticamente.`).
7. Quote-without-locator: for each match of `r'"[^"]{20,}"|“[^”]{20,}”'` (straight or curly double quotes, ≥20 chars inside) in `text`, look at the 90 chars after the match end; if `r"\(([^)]*(p\.|pp\.|párr\.|cap\.|sección|tabla)\s*[^)]*)\)"` (case-insensitive) does not match that window → emit `apa.quote_without_locator` (`Cita textual detectada sin localizador APA 7 cercano.`).

Fuzzy key matching for reciprocity (steps 4–5): `key in other_key or other_key in key` (substring either direction), against the full set of the other side's author keys.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/domain/test_rules.py
from docs.domain.rules import review_apa7_text


def test_review_apa7_text_disabled_returns_no_issues():
    text = "Esto se sostiene (García, 2020) sin lista de referencias."
    issues = review_apa7_text(text, apa7_enabled=False, strict_policy=_policy())
    assert issues == []


def test_review_apa7_text_citations_without_references_flags_no_reference_list():
    text = "Esto se sostiene (García, 2020) sin lista de referencias."
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy(apa_violations="error"))
    codes = [i.code for i in issues]
    assert "apa.no_reference_list" in codes
    assert "apa.citation_without_reference" in codes
    assert all(i.severity == "error" for i in issues)


def test_review_apa7_text_references_without_citations_flags_reference_without_citation():
    text = (
        "Texto sin citas en el cuerpo.\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Título largo de un trabajo. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    codes = [i.code for i in issues]
    assert "apa.reference_without_citation" in codes


def test_review_apa7_text_matching_citation_and_reference_no_issues():
    text = (
        "Esto se sostiene (García, 2020) en la literatura.\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Un título cualquiera. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code in {"apa.citation_without_reference", "apa.reference_without_citation"} for i in issues)


def test_review_apa7_text_unmatched_citation_among_others_flags_only_that_one():
    text = (
        "Esto se sostiene (García, 2020) y también (Pérez, 2021).\n\n"
        "# REFERENCIAS\n"
        "García, A. (2020). Un título cualquiera. Editorial.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    unmatched = [i for i in issues if i.code == "apa.citation_without_reference"]
    assert len(unmatched) == 1
    assert "Pérez" in unmatched[0].message


def test_review_apa7_text_references_not_sorted():
    text = (
        "(Zeta, 2020) y (Alfa, 2019) se citan aquí.\n\n"
        "# REFERENCIAS\n"
        "Zeta, A. (2020). Título Z.\n"
        "Alfa, B. (2019). Título A.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert any(i.code == "apa.references_not_sorted" for i in issues)


def test_review_apa7_text_references_sorted_no_issue():
    text = (
        "(Alfa, 2019) y (Zeta, 2020) se citan aquí.\n\n"
        "# REFERENCIAS\n"
        "Alfa, B. (2019). Título A.\n"
        "Zeta, A. (2020). Título Z.\n"
    )
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code == "apa.references_not_sorted" for i in issues)


def test_review_apa7_text_quote_without_locator():
    text = 'Dice textualmente "esto es una cita larga de más de veinte caracteres" sin nada más.'
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert any(i.code == "apa.quote_without_locator" for i in issues)


def test_review_apa7_text_quote_with_nearby_locator_no_issue():
    text = 'Dice textualmente "esto es una cita larga de más de veinte caracteres" (p. 5) según el autor.'
    issues = review_apa7_text(text, apa7_enabled=True, strict_policy=_policy())
    assert not any(i.code == "apa.quote_without_locator" for i in issues)


def test_review_apa7_text_no_citations_no_references_no_issues():
    issues = review_apa7_text("Texto neutro sin nada relevante.", apa7_enabled=True, strict_policy=_policy())
    assert issues == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_rules.py -k apa7_text -v`
Expected: FAIL with `ImportError: cannot import name 'review_apa7_text'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/domain/rules.py
from docs.domain.apa import citation_author_key, extract_reference_entries, reference_author_key
from docs.domain.markdown_text import normalize_for_sort

_QUOTE_RE = re.compile(r'"[^"]{20,}"|“[^”]{20,}”')
_LOCATOR_RE = re.compile(r"\(([^)]*(p\.|pp\.|párr\.|cap\.|sección|tabla)\s*[^)]*)\)", re.IGNORECASE)


def review_apa7_text(text: str, apa7_enabled: bool, strict_policy: StrictPolicyBlock) -> list[Issue]:
    if not apa7_enabled:
        return []

    issues: list[Issue] = []
    severity = strict_policy.apa_violations
    citations = extract_apa_citations(text)
    references = extract_reference_entries(text)

    if citations and not references:
        issues.append(
            Issue(
                severity,
                "Hay citas APA en texto pero no hay lista de referencias detectable.",
                code="apa.no_reference_list",
            )
        )
        for citation in sorted(citations):
            issues.append(
                Issue(severity, f"Cita sin referencia correspondiente: `{citation}`.", code="apa.citation_without_reference")
            )

    if references and not citations:
        for entry in references:
            issues.append(
                Issue(severity, f"Referencia sin cita correspondiente: `{entry[:90]}`.", code="apa.reference_without_citation")
            )

    citation_keys = {citation_author_key(citation) for citation in citations}
    reference_keys = {reference_author_key(entry) for entry in references}

    for citation in sorted(citations):
        key = citation_author_key(citation)
        if key and references and not any(key in ref_key or ref_key in key for ref_key in reference_keys):
            issues.append(
                Issue(severity, f"Cita sin referencia correspondiente: `{citation}`.", code="apa.citation_without_reference")
            )

    for entry in references:
        key = reference_author_key(entry)
        if key and citations and not any(key in cite_key or cite_key in key for cite_key in citation_keys):
            issues.append(
                Issue(severity, f"Referencia sin cita correspondiente: `{entry[:90]}`.", code="apa.reference_without_citation")
            )

    if references and references != sorted(references, key=normalize_for_sort):
        issues.append(
            Issue(severity, "Las referencias no están ordenadas alfabéticamente.", code="apa.references_not_sorted")
        )

    for match in _QUOTE_RE.finditer(text):
        window = text[match.end():match.end() + 90]
        if not _LOCATOR_RE.search(window):
            issues.append(
                Issue(severity, "Cita textual detectada sin localizador APA 7 cercano.", code="apa.quote_without_locator")
            )

    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: PASS (25 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "feat(domain): add review_apa7_text with reciprocity and sort/locator checks"
```

---

### Task 7: review_section_text (pure)

**Files:**
- Modify: `src/docs/domain/rules.py` (add `review_section_text`)
- Test: `tests/unit/domain/test_rules.py` (add cases)

**Interfaces:**
- Consumes: `Issue` (Task 1); `review_section_contract` (Task 5); `review_apa7_text` (Task 6); `SectionContract`, `Template` (Task 4 / Slice 1).
- Produces:
```python
def review_section_text(
    text: str,
    metadata: dict,
    section_id: str,
    contract: SectionContract,
    template: Template,
    strict: bool,
    *,
    excluded_terms: dict[str, str],
    is_policy_file: bool,
    first_person_patterns: list[str],
    subjective_terms: list[str],
    secret_patterns: list[str],
    scope_term: str = "",
    scope_focus: str = "",
) -> list[Issue]
```

**Documented split from legacy `review_section`:** legacy `review_section(path, config, strict)` reads the file from `path`, calls `split_frontmatter` itself, and resolves `section_id` from `metadata.get("section_id") or infer_section_id_from_path(path)`, then looks up `contract = config["section_contracts"].get(section_id, {})`. This slice's `review_section_text` takes `text`, `metadata`, and the already-resolved `contract` as parameters — the caller (a future `application/review.py`) is responsible for: reading the file, calling `split_frontmatter`, resolving `section_id` (from metadata or filename), and looking up the contract from `template.section_contracts`. This keeps `review_section_text` fully I/O-free and free of `Path` entirely, consistent with the "no I/O in this slice" constraint. `metadata` is accepted as a parameter even though this function doesn't currently read any key from it, because legacy's `review_section` receives it (via `split_frontmatter`) and a follow-up slice may need it (e.g. corrections/hashing) — passing it through now avoids reshaping the signature later. `excluded_terms`, `first_person_patterns`, `subjective_terms`, `secret_patterns`, `scope_term`, `scope_focus` replace legacy's module-level constants (`EXCLUDED_FRONT_MATTER`, `FIRST_PERSON_PATTERNS`, `SUBJECTIVE_TERMS`, `SECRET_PATTERNS`) plus `normative.*` config reads — the caller resolves these (typically from `template.model_extra` or hardcoded defaults) and passes them in, since `Template` does not yet model a `normative` sub-schema in this slice (out of scope; not needed for the review functions themselves to be pure and correct).

Preserve exact order and exact Issue codes/messages:

1. **Excluded-terms scope check** — skipped when `is_policy_file`. For each `(term, reason)` in `excluded_terms.items()`: if `term in text.lower()` → `Issue("error", f"Contiene apartado excluido: `{term}`. {reason}".strip(), code="scope.excluded_section")`.
2. **First-person voice** — for each `pattern` in `first_person_patterns`: if `re.search(pattern, text.lower())` → `Issue("error", f"Contiene primera persona o voz no permitida: patrón `{pattern}`.", code="voice.first_person")`.
3. **Subjective term** — always warning — for each `term` in `subjective_terms`: if `re.search(rf"\b{re.escape(term)}\b", text.lower())` → `Issue("warning", f"Contiene término subjetivo sin evidencia automática: `{term}`.", code="voice.subjective_term")`.
4. **Secrets/privacy** — checked against the **raw** `text` with `re.IGNORECASE` (not lowered) — for each `pattern` in `secret_patterns`: if `re.search(pattern, text, flags=re.IGNORECASE)` → `Issue("error", f"Contiene posible secreto, credencial o dato sensible: patrón `{pattern}`.", code="privacy.sensitive_data")`.
5. **Scope/ecosystem delimitation** — warning — only when both `scope_term` and `scope_focus` are non-empty: if `scope_term in text.lower() and scope_focus not in text.lower()` → `Issue("warning", f"Menciona `{scope_term}` sin delimitar el alcance a `{scope_focus}`.", code="scope.undelimited_ecosystem")`.
6. **Title presence** — skipped when `is_policy_file` (the fact-ledger check is specifically `path.name != "00-fact-ledger.md"` in legacy; in this slice, `is_policy_file` already covers both `00-fact-ledger.md` and `README.md`, which is a deliberate widening — `README.md` files plausibly also lack a Markdown `#` title by design, and legacy's title check was only ever gated on the fact-ledger filename specifically, not on `is_policy_file`. **This is a minor, explicitly-noted scope widening, not a silent behavior change**: legacy would flag a titleless `README.md` as `structure.missing_title`; this port does not. If exact 1:1 parity for `README.md` titles is required later, the caller can pass a narrower `is_policy_file` for this one check via a follow-up parameter — out of scope for this slice). Otherwise: if not `re.search(r"^#\s+\S+", text, re.MULTILINE)` → `Issue("error", "La sección no tiene título principal Markdown.", code="structure.missing_title")`.
7. **Section contract dispatch** — if `contract` is non-empty (i.e. `contract != SectionContract()`) and not `is_policy_file`: extend issues with `review_section_contract(text, section_id, contract, template.strict_policy.strict if strict else template.strict_policy.draft, strict)`.
8. **PENDIENTE marker** — skipped when `is_policy_file`. `pending_allowed = (template.strict_policy.strict if strict else template.strict_policy.draft).allow_pending and contract.pending_allowed_in_draft`. If `"pendiente" in text.lower() and not pending_allowed` → `Issue("error", "Contiene PENDIENTE en modo estricto o en una sección que no permite pendientes.", code="content.pending_not_allowed")`.
9. **APA7 dispatch** — extend issues with `review_apa7_text(text, template.apa7.enabled, template.strict_policy.strict if strict else template.strict_policy.draft)`.
10. **Results-without-evidence heuristic** — warning — if `re.search(r"\bresultados?\b", text.lower())` and `"pendiente" not in text.lower()` and not `re.search(r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo)\b", text.lower())` → `Issue("warning", "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.", code="evidence.results_without_evidence")`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/domain/test_rules.py
from docs.domain.models.template import SectionContract, Template
from docs.domain.rules import review_section_text


def _template(**overrides) -> Template:
    return Template(type="x", title="X", **overrides)


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


def test_review_section_text_excluded_term_flags_error_unless_policy_file():
    text = "# Título\n\nEste texto contiene plagio detectado."
    issues = _call(text, excluded_terms={"plagio": "No se permite contenido plagiado."})
    issue = next(i for i in issues if i.code == "scope.excluded_section")
    assert issue.severity == "error"
    assert "Contiene apartado excluido: `plagio`. No se permite contenido plagiado." == issue.message


def test_review_section_text_excluded_term_skipped_for_policy_file():
    text = "# Título\n\nEste texto contiene plagio detectado."
    issues = _call(text, excluded_terms={"plagio": "x"}, is_policy_file=True)
    assert not any(i.code == "scope.excluded_section" for i in issues)


def test_review_section_text_first_person_pattern_flags_error():
    text = "# Título\n\nYo considero que esto es así."
    issues = _call(text, first_person_patterns=[r"\byo\b"])
    issue = next(i for i in issues if i.code == "voice.first_person")
    assert issue.severity == "error"
    assert "patrón `\\byo\\b`" in issue.message


def test_review_section_text_subjective_term_always_warning():
    text = "# Título\n\nEsto es excelente sin duda."
    issues = _call(text, subjective_terms=["excelente"])
    issue = next(i for i in issues if i.code == "voice.subjective_term")
    assert issue.severity == "warning"


def test_review_section_text_secret_pattern_checked_against_raw_text_case_insensitive():
    text = "# Título\n\nAPI_KEY=ABC123SECRET"
    issues = _call(text, secret_patterns=[r"api_key\s*="])
    issue = next(i for i in issues if i.code == "privacy.sensitive_data")
    assert issue.severity == "error"


def test_review_section_text_scope_undelimited_warning():
    text = "# Título\n\nSe usa azure en este proyecto."
    issues = _call(text, scope_term="azure", scope_focus="estadía tic")
    issue = next(i for i in issues if i.code == "scope.undelimited_ecosystem")
    assert issue.severity == "warning"


def test_review_section_text_scope_check_skipped_when_focus_present():
    text = "# Título\n\nSe usa azure en el contexto de la estadía tic."
    issues = _call(text, scope_term="azure", scope_focus="estadía tic")
    assert not any(i.code == "scope.undelimited_ecosystem" for i in issues)


def test_review_section_text_missing_title_flagged():
    text = "Texto sin encabezado markdown."
    issues = _call(text)
    assert any(i.code == "structure.missing_title" for i in issues)


def test_review_section_text_missing_title_skipped_for_policy_file():
    text = "Texto sin encabezado markdown."
    issues = _call(text, is_policy_file=True)
    assert not any(i.code == "structure.missing_title" for i in issues)


def test_review_section_text_dispatches_to_contract_review():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Título\n\nTexto sin relación alguna."
    issues = _call(text, contract=contract)
    assert any(i.code == "contract.missing_required" for i in issues)


def test_review_section_text_contract_dispatch_skipped_for_policy_file():
    contract = SectionContract(required_content=["objetivo"])
    text = "# Título\n\nTexto sin relación alguna."
    issues = _call(text, contract=contract, is_policy_file=True)
    assert not any(i.code == "contract.missing_required" for i in issues)


def test_review_section_text_pending_marker_flagged_when_not_allowed():
    contract = SectionContract(pending_allowed_in_draft=False)
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text, contract=contract)
    issue = next(i for i in issues if i.code == "content.pending_not_allowed")
    assert issue.severity == "error"


def test_review_section_text_pending_marker_allowed_by_default():
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text)
    assert not any(i.code == "content.pending_not_allowed" for i in issues)


def test_review_section_text_pending_marker_skipped_for_policy_file():
    contract = SectionContract(pending_allowed_in_draft=False)
    text = "# Título\n\nEsto está PENDIENTE."
    issues = _call(text, contract=contract, is_policy_file=True)
    assert not any(i.code == "content.pending_not_allowed" for i in issues)


def test_review_section_text_dispatches_to_apa7_review():
    text = "# Título\n\nEsto se sostiene (García, 2020) sin lista de referencias."
    issues = _call(text)
    assert any(i.code == "apa.no_reference_list" for i in issues)


def test_review_section_text_apa7_disabled_via_template_skips_apa_checks():
    text = "# Título\n\nEsto se sostiene (García, 2020) sin lista de referencias."
    template = _template(apa7={"enabled": False})
    issues = _call(text, template=template)
    assert not any(i.code.startswith("apa.") for i in issues)


def test_review_section_text_results_without_evidence_warning():
    text = "# Título\n\nLos resultados obtenidos fueron positivos."
    issues = _call(text)
    issue = next(i for i in issues if i.code == "evidence.results_without_evidence")
    assert issue.severity == "warning"


def test_review_section_text_results_with_evidence_word_no_warning():
    text = "# Título\n\nLos resultados obtenidos se respaldan con evidencia adjunta."
    issues = _call(text)
    assert not any(i.code == "evidence.results_without_evidence" for i in issues)


def test_review_section_text_results_with_pendiente_no_warning():
    text = "# Título\n\nLos resultados están PENDIENTE de evaluación."
    issues = _call(text)
    assert not any(i.code == "evidence.results_without_evidence" for i in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_rules.py -k review_section_text -v`
Expected: FAIL with `ImportError: cannot import name 'review_section_text'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/domain/rules.py
from docs.domain.models.template import Template

_TITLE_RE = re.compile(r"^#\s+\S+", re.MULTILINE)
_RESULTS_RE = re.compile(r"\bresultados?\b")
_RESULTS_EVIDENCE_RE = re.compile(r"\b(evidencia|captura|prueba|medici[oó]n|issue|commit|anexo)\b")


def review_section_text(
    text: str,
    metadata: dict,
    section_id: str,
    contract: SectionContract,
    template: Template,
    strict: bool,
    *,
    excluded_terms: dict[str, str],
    is_policy_file: bool,
    first_person_patterns: list[str],
    subjective_terms: list[str],
    secret_patterns: list[str],
    scope_term: str = "",
    scope_focus: str = "",
) -> list[Issue]:
    lowered = text.lower()
    issues: list[Issue] = []
    strict_policy = template.strict_policy.strict if strict else template.strict_policy.draft

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

    for pattern in first_person_patterns:
        if re.search(pattern, lowered):
            issues.append(
                Issue(
                    "error",
                    f"Contiene primera persona o voz no permitida: patrón `{pattern}`.",
                    code="voice.first_person",
                )
            )

    for term in subjective_terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            issues.append(
                Issue(
                    "warning",
                    f"Contiene término subjetivo sin evidencia automática: `{term}`.",
                    code="voice.subjective_term",
                )
            )

    for pattern in secret_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            issues.append(
                Issue(
                    "error",
                    f"Contiene posible secreto, credencial o dato sensible: patrón `{pattern}`.",
                    code="privacy.sensitive_data",
                )
            )

    if scope_term and scope_focus and scope_term in lowered and scope_focus not in lowered:
        issues.append(
            Issue(
                "warning",
                f"Menciona `{scope_term}` sin delimitar el alcance a `{scope_focus}`.",
                code="scope.undelimited_ecosystem",
            )
        )

    if not is_policy_file and not _TITLE_RE.search(text):
        issues.append(Issue("error", "La sección no tiene título principal Markdown.", code="structure.missing_title"))

    if contract != SectionContract() and not is_policy_file:
        issues.extend(review_section_contract(text, section_id, contract, strict_policy, strict))

    pending_allowed = strict_policy.allow_pending and contract.pending_allowed_in_draft
    if not is_policy_file and "pendiente" in lowered and not pending_allowed:
        issues.append(
            Issue(
                "error",
                "Contiene PENDIENTE en modo estricto o en una sección que no permite pendientes.",
                code="content.pending_not_allowed",
            )
        )

    issues.extend(review_apa7_text(text, template.apa7.enabled, strict_policy))

    if (
        _RESULTS_RE.search(lowered)
        and "pendiente" not in lowered
        and not _RESULTS_EVIDENCE_RE.search(lowered)
    ):
        issues.append(
            Issue(
                "warning",
                "Menciona resultados sin evidencia detectable ni marcador PENDIENTE.",
                code="evidence.results_without_evidence",
            )
        )

    return issues
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: PASS (44 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "feat(domain): add review_section_text orchestrating voice/privacy/contract/apa7 checks"
```

---

### Task 8: review_rules (pure)

**Files:**
- Modify: `src/docs/domain/rules.py` (add `review_rules`)
- Test: `tests/unit/domain/test_rules.py` (add cases)

**Interfaces:**
- Consumes: `Issue`, `ReviewResult` (Task 1); `Template`, `SectionContract` (Task 4 / Slice 1).
- Produces: `review_rules(template: Template, manifest_exists: bool, manifest_size: int, strict: bool = False) -> ReviewResult`

**Modeling decision — explicit simplification, not a silent gap:** legacy `review_rules` reads `config.get("paths", {}).get("extracted_dir_policy")`, `config.get("project", {}).get("source_priority", [])`, `config.get("preliminaries", {})...`, `config.get("format", {}).get("page_margins_cm", {})`, and `config.get("advisor_overrides", [])` — none of these have a typed model yet (they belong to `format`/`preliminaries`/`project`/`advisor_overrides` config blocks the design doc's §5 lists as future `Template` fields, not introduced in this slice). Rather than invent typed sub-models for blocks this slice has no other use for, `review_rules` reads them defensively from `template.model_extra` (Pydantic v2's `extra="allow"` capture dict) via `.get()` chains mirroring the legacy dict-of-dicts shape exactly — preserving every Issue message verbatim while deferring "should `extracted_dir_policy`/`page_margins_cm`/etc. become typed models" to whichever future slice actually consumes them structurally (most likely Slice 5/7, which deal with section building, layout, and margins). This is a deliberate prioritization of **message-output correctness over modeling purity** for this one task, called out per the task's own instructions.

All Issues from this function use `code=""` (legacy sets no codes on any `review_rules` issue — preserve this; do not invent codes).

Checks in order (verbatim Spanish messages):

1. **Manifest missing** → `manifest_exists is False` → `Issue("error" if strict else "warning", "No existe manual-rules.json; ejecuta \`build-rules\`.")`.
2. **Manifest empty** → `manifest_exists is True and manifest_size == 0` → always `"error"` → `Issue("error", "manual-rules.json existe pero está vacío.")`.
3. **Missing per-section contracts** → `sorted({s.id for s in template.sections} - set(template.section_contracts))` → if non-empty → `Issue("error", f"Faltan contratos de sección: {', '.join(missing_contracts)}.")`.
4. `template.model_extra.get("paths", {}).get("extracted_dir_policy") != "rules_traceability_only"` → `Issue("error", "La política de extracted debe ser \`rules_traceability_only\`.")`.
5. `any("tesina/extracted" in source for source in template.model_extra.get("project", {}).get("source_priority", []))` → `Issue("error", "\`tesina/extracted\` no debe aparecer en source_priority como fuente activa.")`.
6. `not template.apa7.enabled` → `Issue("error", "APA 7 debe estar habilitado.")`.
7. `not template.model_extra.get("preliminaries", {}).get("roman_pagination", {}).get("enabled")` → `Issue("error", "La paginación romana de preliminares debe estar habilitada.")`.
8. `template.model_extra.get("preliminaries", {}).get("body_pagination_start", {}).get("section_id") != "introduccion"` → `Issue("error", "La paginación arábiga debe iniciar en INTRODUCCIÓN.")`.
9. `template.model_extra.get("format", {}).get("page_margins_cm", {}).get("cover_policy") != "preserve_template"` → `Issue("error", "La portada debe conservar el formato y márgenes de la plantilla (\`preserve_template\`).")`.
10. Margins: for `non_cover = format.page_margins_cm.get("non_cover", {})`, any of `top/right/bottom/left` not a number or `abs(value - 2.5) > 0.001` → `Issue("error", "El contrato de layout debe fijar márgenes de 2.5 cm en toda sección no-portada.")`.
11. `"margins-2-5cm-non-cover" not in {item.get("id") for item in template.model_extra.get("advisor_overrides", []) if item.get("status") == "active"}` → `Issue("error", "Falta el advisor_override activo para márgenes de 2.5 cm excepto portada.")`.
12. Per-contract, for `section_id, contract in template.section_contracts.items()`:
    - `not contract.required_content` → `Issue("error", f"El contrato \`{section_id}\` no define contenido obligatorio.")`.
    - `contract.apa_required and not template.apa7.enabled` → `Issue("error", f"El contrato \`{section_id}\` requiere APA pero APA 7 está deshabilitado.")` (duplicates check 6 when both fire on the same template — preserve the duplication, it is real legacy behavior, not a bug to deduplicate).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/domain/test_rules.py
from docs.domain.rules import review_rules


def _valid_extra() -> dict:
    return {
        "paths": {"extracted_dir_policy": "rules_traceability_only"},
        "project": {"source_priority": ["tesina/manual"]},
        "preliminaries": {
            "roman_pagination": {"enabled": True},
            "body_pagination_start": {"section_id": "introduccion"},
        },
        "format": {
            "page_margins_cm": {
                "cover_policy": "preserve_template",
                "non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5},
            }
        },
        "advisor_overrides": [{"id": "margins-2-5cm-non-cover", "status": "active"}],
    }


def _valid_template(**overrides) -> Template:
    return Template.model_validate({"type": "x", "title": "X", **_valid_extra(), **overrides})


def test_review_rules_all_valid_no_issues():
    result = review_rules(_valid_template(), manifest_exists=True, manifest_size=10, strict=False)
    assert result.issues == []
    assert result.passed is True


def test_review_rules_manifest_missing_warning_in_draft():
    result = review_rules(_valid_template(), manifest_exists=False, manifest_size=0, strict=False)
    issue = next(i for i in result.issues if "manual-rules.json" in i.message and "ejecuta" in i.message)
    assert issue.severity == "warning"
    assert issue.code == ""


def test_review_rules_manifest_missing_error_in_strict():
    result = review_rules(_valid_template(), manifest_exists=False, manifest_size=0, strict=True)
    issue = next(i for i in result.issues if "manual-rules.json" in i.message and "ejecuta" in i.message)
    assert issue.severity == "error"


def test_review_rules_manifest_empty_always_error():
    result = review_rules(_valid_template(), manifest_exists=True, manifest_size=0, strict=False)
    issue = next(i for i in result.issues if "está vacío" in i.message)
    assert issue.severity == "error"


def test_review_rules_missing_section_contracts():
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "sections": [{"id": "intro", "title": "Intro"}, {"id": "resumen", "title": "Resumen"}],
            "section_contracts": {"intro": {}},
            **_valid_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    issue = next(i for i in result.issues if "Faltan contratos" in i.message)
    assert "resumen" in issue.message


def test_review_rules_extracted_dir_policy_wrong():
    extra = _valid_extra()
    extra["paths"]["extracted_dir_policy"] = "anything_else"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("rules_traceability_only" in i.message for i in result.issues)


def test_review_rules_tesina_extracted_in_source_priority():
    extra = _valid_extra()
    extra["project"]["source_priority"] = ["tesina/extracted/foo"]
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("source_priority" in i.message for i in result.issues)


def test_review_rules_apa7_disabled():
    template = Template.model_validate({"type": "x", "title": "X", "apa7": {"enabled": False}, **_valid_extra()})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any(i.message == "APA 7 debe estar habilitado." for i in result.issues)


def test_review_rules_roman_pagination_disabled():
    extra = _valid_extra()
    extra["preliminaries"]["roman_pagination"]["enabled"] = False
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("paginación romana" in i.message for i in result.issues)


def test_review_rules_body_pagination_start_wrong_section():
    extra = _valid_extra()
    extra["preliminaries"]["body_pagination_start"]["section_id"] = "resumen"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("INTRODUCCIÓN" in i.message for i in result.issues)


def test_review_rules_cover_policy_wrong():
    extra = _valid_extra()
    extra["format"]["page_margins_cm"]["cover_policy"] = "custom"
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("preserve_template" in i.message for i in result.issues)


def test_review_rules_bad_margins():
    extra = _valid_extra()
    extra["format"]["page_margins_cm"]["non_cover"]["top"] = 3.0
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("márgenes de 2.5 cm" in i.message for i in result.issues)


def test_review_rules_missing_active_advisor_override():
    extra = _valid_extra()
    extra["advisor_overrides"] = []
    template = Template.model_validate({"type": "x", "title": "X", **extra})
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("advisor_override activo" in i.message for i in result.issues)


def test_review_rules_contract_without_required_content():
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "section_contracts": {"intro": {"required_content": []}},
            **_valid_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    assert any("no define contenido obligatorio" in i.message for i in result.issues)


def test_review_rules_contract_apa_required_but_apa7_disabled_duplicates_document_level_issue():
    template = Template.model_validate(
        {
            "type": "x",
            "title": "X",
            "apa7": {"enabled": False},
            "section_contracts": {"intro": {"required_content": ["x"], "apa_required": True}},
            **_valid_extra(),
        }
    )
    result = review_rules(template, manifest_exists=True, manifest_size=10)
    document_level = [i for i in result.issues if i.message == "APA 7 debe estar habilitado."]
    contract_level = [i for i in result.issues if "requiere APA pero APA 7 está deshabilitado" in i.message]
    assert len(document_level) == 1
    assert len(contract_level) == 1


def test_review_rules_all_issues_have_empty_code():
    result = review_rules(_valid_template(), manifest_exists=False, manifest_size=0, strict=True)
    assert all(i.code == "" for i in result.issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_rules.py -k review_rules -v`
Expected: FAIL with `ImportError: cannot import name 'review_rules'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/domain/rules.py
from docs.domain.review import ReviewResult

_MARGIN_KEYS = ("top", "right", "bottom", "left")
_EXPECTED_MARGIN_CM = 2.5
_MARGIN_TOLERANCE = 0.001


def review_rules(
    template: Template, manifest_exists: bool, manifest_size: int, strict: bool = False
) -> ReviewResult:
    issues: list[Issue] = []
    extra = template.model_extra or {}

    if not manifest_exists:
        issues.append(Issue("error" if strict else "warning", "No existe manual-rules.json; ejecuta `build-rules`."))
    elif manifest_size == 0:
        issues.append(Issue("error", "manual-rules.json existe pero está vacío."))

    section_ids = {s.id for s in template.sections}
    contract_ids = set(template.section_contracts)
    missing_contracts = sorted(section_ids - contract_ids)
    if missing_contracts:
        issues.append(Issue("error", f"Faltan contratos de sección: {', '.join(missing_contracts)}."))

    paths = extra.get("paths", {}) or {}
    if paths.get("extracted_dir_policy") != "rules_traceability_only":
        issues.append(Issue("error", "La política de extracted debe ser `rules_traceability_only`."))

    project = extra.get("project", {}) or {}
    if any("tesina/extracted" in source for source in project.get("source_priority", [])):
        issues.append(Issue("error", "`tesina/extracted` no debe aparecer en source_priority como fuente activa."))

    if not template.apa7.enabled:
        issues.append(Issue("error", "APA 7 debe estar habilitado."))

    preliminaries = extra.get("preliminaries", {}) or {}
    if not preliminaries.get("roman_pagination", {}).get("enabled"):
        issues.append(Issue("error", "La paginación romana de preliminares debe estar habilitada."))
    if preliminaries.get("body_pagination_start", {}).get("section_id") != "introduccion":
        issues.append(Issue("error", "La paginación arábiga debe iniciar en INTRODUCCIÓN."))

    margin_contract = (extra.get("format", {}) or {}).get("page_margins_cm", {}) or {}
    non_cover_margins = margin_contract.get("non_cover", {}) or {}
    bad_margins = [
        key
        for key in _MARGIN_KEYS
        if not isinstance(non_cover_margins.get(key), (int, float))
        or abs(float(non_cover_margins.get(key)) - _EXPECTED_MARGIN_CM) > _MARGIN_TOLERANCE
    ]
    if margin_contract.get("cover_policy") != "preserve_template":
        issues.append(
            Issue("error", "La portada debe conservar el formato y márgenes de la plantilla (`preserve_template`).")
        )
    if bad_margins:
        issues.append(Issue("error", "El contrato de layout debe fijar márgenes de 2.5 cm en toda sección no-portada."))

    active_overrides = {
        item.get("id") for item in extra.get("advisor_overrides", []) if item.get("status") == "active"
    }
    if "margins-2-5cm-non-cover" not in active_overrides:
        issues.append(Issue("error", "Falta el advisor_override activo para márgenes de 2.5 cm excepto portada."))

    for section_id, contract in template.section_contracts.items():
        if not contract.required_content:
            issues.append(Issue("error", f"El contrato `{section_id}` no define contenido obligatorio."))
        # Duplicates the document-level APA gate above when both fire — this is
        # real legacy behavior (review_rules never deduplicates), preserve it.
        if contract.apa_required and not template.apa7.enabled:
            issues.append(Issue("error", f"El contrato `{section_id}` requiere APA pero APA 7 está deshabilitado."))

    return ReviewResult(issues)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: PASS (61 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "feat(domain): add review_rules document/config-level checks"
```

---

### Task 9: review_cross_consistency (pure)

**Files:**
- Modify: `src/docs/domain/rules.py` (add `review_cross_consistency`)
- Test: `tests/unit/domain/test_rules.py` (add cases)

**Interfaces:**
- Consumes: `Issue` (Task 1); `extract_apa_citations`, `extract_reference_entries`, `citation_author_key`, `reference_author_key` (Task 3); `clean_markdown_text` (Task 2); `Template` (Task 4 / Slice 1).
- Produces: `review_cross_consistency(template: Template, section_bodies: dict[str, str], strict: bool = False, contested_stack_terms: list[str] | None = None) -> ReviewResult`

`contested_stack_terms` defaults to `["Laravel", "Supabase", "bun.js", "MySQL", "GCP", "Firebase"]` when `None` (matching legacy's `DEFAULT_CONTESTED_STACK_TERMS`), overridable by the caller (legacy reads `cfg.get("contested_stack_terms", DEFAULT_CONTESTED_STACK_TERMS)` from a `cross_consistency` config block not modeled on `Template` in this slice — the caller resolves the override, if any, from `template.model_extra.get("cross_consistency", {}).get("contested_stack_terms")` and passes it in; this function itself does not reach into `model_extra` for this one parameter, keeping its signature self-contained).

Checks (verbatim):

1. **Global APA reciprocity.** Build `citations: dict[str, str]` (author-key → first-seen citation text) by iterating `section_bodies.items()` skipping `"referencias"`, calling `extract_apa_citations(body)` per section, keying each by `citation_author_key`, first-seen wins (`citations.setdefault(key, citation)`). `references = extract_reference_entries(section_bodies.get("referencias", ""))`. `references_pending = "pendiente" in clean_markdown_text(section_bodies.get("referencias", "")).lower()`. Skip BOTH reciprocity directions entirely when `references_pending and not strict`. Otherwise:
   - Unmatched citation (no reference key fuzzy-matches, sorted by key) → `Issue(severity, f"Cita \`{citation}\` usada en el cuerpo no tiene referencia en REFERENCIAS BIBLIOGRÁFICAS.", code="coherence.citation_without_global_reference")`.
   - Unmatched reference (no citation key fuzzy-matches) → `Issue(severity, f"Referencia \`{entry[:80]}\` no está citada en ninguna sección del cuerpo.", code="coherence.reference_without_global_citation")` (note: 80-char truncation here, vs. 90 in `review_apa7_text` — preserve the discrepancy verbatim).
   - `severity = "error" if strict else "warning"`.
2. **Duration consistency.** Collect all `int` matches of `r"\b(\d{2,4})\s*horas\b"` (case-insensitive) across every value in `section_bodies`, into a set. If `len(hour_mentions) > 1` → `Issue(severity, f"La duración de la estadía es inconsistente entre secciones: {values}.", code="coherence.duration_mismatch")` where `values = ", ".join(f"{v} horas" for v in sorted(hour_mentions))`.
3. **Contested stack terms.** For each `(section_id, body)` in `section_bodies.items()`: `section_pending = "pendiente" in body.lower()`; for each `term` in `contested_stack_terms`: if `re.search(rf"(?<![\w]){re.escape(term.lower())}(?![\w])", body.lower())` and not `section_pending` and not `re.search(r"\b(contexto|prototipo|dependencia|externa|posible|planea|futur\w*)", body.lower())` → `Issue("warning", f"\`{section_id}\` menciona tecnología en disputa \`{term}\` como definitiva sin delimitarla ni marcar PENDIENTE.", code="coherence.contested_stack_unqualified")` (always `"warning"`, never tracks `strict`).

Fuzzy key matching (step 1): same substring-either-direction rule as Task 6 (`key in other_key or other_key in key`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/domain/test_rules.py
from docs.domain.rules import review_cross_consistency


def test_review_cross_consistency_citation_without_global_reference():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nOtroAutor, B. (2019). Título.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.citation_without_global_reference")
    assert issue.severity == "warning"
    assert "García, 2020" in issue.message


def test_review_cross_consistency_reference_without_global_citation():
    bodies = {
        "introduccion": "Texto sin ninguna cita.",
        "referencias": "# REFERENCIAS\nGarcía, A. (2020). Un título largo cualquiera. Editorial.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.reference_without_global_citation")
    assert "García" in issue.message


def test_review_cross_consistency_matching_citation_and_reference_no_issue():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nGarcía, A. (2020). Un título largo cualquiera. Editorial.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(
        i.code in {"coherence.citation_without_global_reference", "coherence.reference_without_global_citation"}
        for i in result.issues
    )


def test_review_cross_consistency_referencias_section_itself_excluded_from_citation_pool():
    bodies = {
        "referencias": "(EsteAutor, 2020) # REFERENCIAS\nOtroAutor, B. (2019). Título.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    # "EsteAutor" citation lives only inside the referencias body, which is excluded
    # from the citation pool entirely -- so no citation-side issue should appear for it.
    assert not any("EsteAutor" in i.message for i in result.issues)


def test_review_cross_consistency_reciprocity_skipped_when_references_pending_and_not_strict():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nPENDIENTE de completar.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code.startswith("coherence.citation_without") for i in result.issues)
    assert not any(i.code.startswith("coherence.reference_without") for i in result.issues)


def test_review_cross_consistency_reciprocity_not_skipped_when_strict_even_if_pending():
    bodies = {
        "introduccion": "Esto se sostiene (García, 2020) en la literatura.",
        "referencias": "# REFERENCIAS\nPENDIENTE de completar.",
    }
    result = review_cross_consistency(_template(), bodies, strict=True)
    assert any(i.code == "coherence.citation_without_global_reference" for i in result.issues)


def test_review_cross_consistency_duration_mismatch():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 200 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.duration_mismatch")
    assert "160 horas" in issue.message and "200 horas" in issue.message
    assert issue.severity == "warning"


def test_review_cross_consistency_duration_consistent_no_issue():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 160 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.duration_mismatch" for i in result.issues)


def test_review_cross_consistency_duration_mismatch_severity_tracks_strict():
    bodies = {
        "introduccion": "La estadía duró 160 horas en total.",
        "resumen": "Se cumplieron 200 horas de trabajo.",
    }
    result = review_cross_consistency(_template(), bodies, strict=True)
    issue = next(i for i in result.issues if i.code == "coherence.duration_mismatch")
    assert issue.severity == "error"


def test_review_cross_consistency_contested_stack_term_unqualified():
    bodies = {"infraestructura": "El sistema usa MySQL como base de datos definitiva."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    issue = next(i for i in result.issues if i.code == "coherence.contested_stack_unqualified")
    assert issue.severity == "warning"
    assert "MySQL" in issue.message
    assert "infraestructura" in issue.message


def test_review_cross_consistency_contested_stack_term_hedged_no_issue():
    bodies = {"infraestructura": "El sistema usa MySQL como posible dependencia externa en el prototipo."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.contested_stack_unqualified" for i in result.issues)


def test_review_cross_consistency_contested_stack_term_pendiente_no_issue():
    bodies = {"infraestructura": "El uso de MySQL está PENDIENTE de definición."}
    result = review_cross_consistency(_template(), bodies, strict=False)
    assert not any(i.code == "coherence.contested_stack_unqualified" for i in result.issues)


def test_review_cross_consistency_contested_stack_terms_overridable():
    bodies = {"infraestructura": "El sistema usa Redis como base definitiva."}
    result = review_cross_consistency(_template(), bodies, strict=False, contested_stack_terms=["Redis"])
    assert any(i.code == "coherence.contested_stack_unqualified" and "Redis" in i.message for i in result.issues)


def test_review_cross_consistency_no_issues_for_empty_bodies():
    result = review_cross_consistency(_template(), {}, strict=False)
    assert result.issues == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/domain/test_rules.py -k cross_consistency -v`
Expected: FAIL with `ImportError: cannot import name 'review_cross_consistency'`.

- [ ] **Step 3: Write minimal implementation**

```python
# add to src/docs/domain/rules.py
_DURATION_RE = re.compile(r"\b(\d{2,4})\s*horas\b", re.IGNORECASE)
_HEDGE_RE = re.compile(r"\b(contexto|prototipo|dependencia|externa|posible|planea|futur\w*)")

DEFAULT_CONTESTED_STACK_TERMS = ["Laravel", "Supabase", "bun.js", "MySQL", "GCP", "Firebase"]


def review_cross_consistency(
    template: Template,
    section_bodies: dict[str, str],
    strict: bool = False,
    contested_stack_terms: list[str] | None = None,
) -> ReviewResult:
    issues: list[Issue] = []
    severity = "error" if strict else "warning"
    terms = contested_stack_terms if contested_stack_terms is not None else DEFAULT_CONTESTED_STACK_TERMS

    references_body = section_bodies.get("referencias", "")
    references_pending = "pendiente" in clean_markdown_text(references_body).lower()

    citations: dict[str, str] = {}
    for section_id, body in section_bodies.items():
        if section_id == "referencias":
            continue
        for citation in extract_apa_citations(body):
            key = citation_author_key(citation)
            if key:
                citations.setdefault(key, citation)

    references = extract_reference_entries(references_body)
    reference_keys = {reference_author_key(entry) for entry in references}

    if not (references_pending and not strict):
        for key, citation in sorted(citations.items()):
            if not any(key in ref_key or ref_key in key for ref_key in reference_keys if ref_key):
                issues.append(
                    Issue(
                        severity,
                        f"Cita `{citation}` usada en el cuerpo no tiene referencia en REFERENCIAS BIBLIOGRÁFICAS.",
                        code="coherence.citation_without_global_reference",
                    )
                )
        for entry in references:
            ref_key = reference_author_key(entry)
            if ref_key and not any(ref_key in cite_key or cite_key in ref_key for cite_key in citations):
                issues.append(
                    Issue(
                        severity,
                        f"Referencia `{entry[:80]}` no está citada en ninguna sección del cuerpo.",
                        code="coherence.reference_without_global_citation",
                    )
                )

    hour_mentions: set[int] = set()
    for body in section_bodies.values():
        for match in _DURATION_RE.finditer(body):
            hour_mentions.add(int(match.group(1)))
    if len(hour_mentions) > 1:
        values = ", ".join(f"{value} horas" for value in sorted(hour_mentions))
        issues.append(
            Issue(
                severity,
                f"La duración de la estadía es inconsistente entre secciones: {values}.",
                code="coherence.duration_mismatch",
            )
        )

    for section_id, body in section_bodies.items():
        lowered = body.lower()
        section_pending = "pendiente" in lowered
        for term in terms:
            pattern = re.compile(rf"(?<![\w]){re.escape(term.lower())}(?![\w])")
            if pattern.search(lowered) and not section_pending and not _HEDGE_RE.search(lowered):
                issues.append(
                    Issue(
                        "warning",
                        f"`{section_id}` menciona tecnología en disputa `{term}` como definitiva "
                        "sin delimitarla ni marcar PENDIENTE.",
                        code="coherence.contested_stack_unqualified",
                    )
                )

    return ReviewResult(issues)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/domain/test_rules.py -v`
Expected: PASS (75 passed).

- [ ] **Step 5: Commit**

```bash
git add src/docs/domain/rules.py tests/unit/domain/test_rules.py
git commit -m "feat(domain): add review_cross_consistency for global APA/duration/stack coherence"
```

---

## Full suite check (run after Task 9)

```bash
uv run pytest -W error -q
```

Expected: all tests pass, zero warnings.

---

## Self-Review

- **Spec coverage (5 legacy review surfaces):**
  - `review_section_contract` ✅ Task 5 — exact word-count formula, exact requirement-presence detection, exact 3 Issue codes/messages.
  - `review_apa7_text` ✅ Task 6 — exact reciprocity loops (steps 2–5), exact sort check, exact quote/locator regexes (including the legacy 90-char truncation on `reference_without_citation`'s message vs. Task 9's 80-char truncation on the document-level equivalent — both preserved verbatim, not unified).
  - `review_section` → ported as `review_section_text` ✅ Task 7 — all 10 checks in legacy order, with the I/O split (file reading, `section_id` resolution, contract lookup) documented as the caller's job, not this function's.
  - `review_rules` ✅ Task 8 — all 12 checks verbatim, including the intentional `contract.apa_required` / document-level APA gate duplication.
  - `review_cross_consistency` ✅ Task 9 — global APA reciprocity (with the `references_pending and not strict` skip), duration mismatch, contested stack terms (always-warning, never tracks `strict`).
- **Documented decisions (not silent gaps):**
  1. **`required_content` severity asymmetry (Task 5).** `review_section_contract`'s word-count and `evidence_required`/`apa_required` checks resolve severity via `strict_policy.<field>`; the `required_content` presence check uses the raw `strict` boolean directly, bypassing `strict_policy` entirely. This is preserved verbatim with an explicit code comment — it is not a bug, it is real legacy behavior: there is no `strict_policy.missing_required` field in legacy at all.
  2. **`apa7.enabled` default asymmetry between `review_rules` and `review_apa7_text` (Tasks 6 & 8).** Legacy `review_apa7_text` defaults `config.get("apa7", {}).get("enabled", True)` to `True` when absent; legacy `review_rules` checks `not config.get("apa7", {}).get("enabled")`, which is falsy (and thus an error) when absent. With `Template.apa7.enabled` now a concrete typed field defaulting to `True` (Task 4), the asymmetry no longer manifests as "default vs no-default" — both functions now always receive/read a concrete boolean. The original legacy *intent* behind the asymmetry (APA enforcement should err toward strict at the document level, permissive at the per-citation level) is preserved structurally: `review_rules` reads `template.apa7.enabled` directly and unconditionally; `review_apa7_text` takes an explicit `apa7_enabled: bool` parameter so a caller could, in principle, gate it differently from `review_rules` if a future config layer ever needs to — but by default both read the same `template.apa7.enabled` value, so no observable behavior changes for any template that sets `apa7.enabled` explicitly (which is every realistic template, since `Apa7Config` always populates a concrete value).
  3. **`pending_allowed_in_draft` default fix (`False`→`True`) (Task 4).** This is the one deliberate parity *correction* in this slice, not a preserved quirk. Legacy's `contract.get("pending_allowed_in_draft", True)` treats an absent key as permissive; the pre-existing Slice 1 model default of `False` was a parity bug introduced before this slice's characterization work, not an intentional legacy behavior to keep. Fixed and called out via a code comment at the field definition.
  4. **Confirmed exclusions from this slice:**
     - **`build_rules`'s manifest-writing/file-hashing** (manual-dir markdown hashing, `traceability` list construction over manual/example PDFs and `extracted_dir`, `write_json_manifest`, `contract_hash`/`sha256_json`) — explicitly deferred to Slice 4 ("Evidence: collect sources/issues/code, build ledger") per the design doc's migration order. None of Tasks 1–9 read or write any file.
     - **The `review_document` orchestrator** (legacy's function that reads every section file from `sections_dir` in order, calls `review_section`/`review_section_text` per section, prefixes each issue message with the filename, checks for a missing `sections_dir`, runs the strict-mode "PENDIENTE in combined body" and "missing flow terms" document-level checks, and finally calls `review_cross_consistency`) is **not** ported in this slice. Reasoning: it is fundamentally an I/O orchestrator (it walks `Path` globs and reads files) layered on top of pure functions this slice already provides (`review_section_text`, `review_cross_consistency`) plus two small additional pure checks (combined-body PENDIENTE scan, missing-flow-terms scan) that were not called out in the required task breakdown. Porting it correctly needs `Section`/`StructureBlock` ordering and file-existence semantics that belong in `application/review.py` (per the design doc's layer table: `application/review.py` is explicitly listed as "review_rules/section/document + verify"), not in `domain/`. Building it now would require either (a) smuggling I/O into a "domain" module, violating this slice's own no-I/O constraint, or (b) building it in `application/` prematurely, ahead of the `DocumentRepository`-style port wiring that would make it testable without hand-rolled temp directories. Recommendation: treat `review_document`'s orchestration (including the two un-ported document-level strict-mode checks) as the first task of a focused follow-up — either folded into Slice 4 once evidence collection exists, or as a small "Slice 3.5" application-layer task once this slice's domain functions are verified solid. It is explicitly not silently dropped: the two extra document-level checks it contains (PENDIENTE-in-combined-body, missing-flow-terms) are flagged here as NOT YET PORTED by any task in this plan.
     - **Any infrastructure adapter/port for reading section files from disk** — not built in this slice, for the same reason: no Task 1–9 function needs the filesystem, and introducing a port here would be speculative (its shape should be driven by the `review_document` orchestrator's actual needs, which is deferred per the point above).
- **Placeholder scan:** no TBD/TODO/elisions; every Step 1/Step 3 across all 9 tasks shows complete, runnable code. Shared helpers (`Issue`, `clean_markdown_text`, `extract_apa_citations`, etc.) are defined once (Tasks 1–3) and imported by name in every later task, never re-pasted or summarized as "same as Task N."
- **Type consistency:** `Issue`/`ReviewResult` (Task 1) used unchanged through Tasks 5–9; `SectionContract`/`Apa7Config`/`StrictPolicy`/`StrictPolicyBlock`/`LengthSpec`/`Template` (Task 4) extend Slice 1's models without breaking `tests/unit/domain/models/test_template.py`'s pre-existing 3 tests; `domain/rules.py` accumulates `requirement_present`, `review_section_contract`, `review_apa7_text`, `review_section_text`, `review_rules`, `review_cross_consistency` incrementally across Tasks 5–9 in one module, mirroring how Slice 2's `context_markdown.py` accumulated functions across its own Tasks 2 and 6.
