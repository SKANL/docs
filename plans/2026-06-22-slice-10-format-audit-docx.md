# Slice 10 — Format Audit DOCX · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 2016–2184 (`format_audit_docx`
through `_table_has_vertical_borders_or_shading`), plus four pure helpers
pulled forward from Slice 11's range (`_structure_parts` 2342–2363,
`_resolve_part_text` 2366–2372, `paragraph_has_numbering` 2563–2565,
`normalize_heading` 2753–2755).

## Overview / Scope

This slice ports the harness's DOCX format-compliance auditor — the
single capability that opens a rendered `.docx` file (already produced by
`build_docx`, Slice 11) and checks it against the manual's layout
contract: page margins, pagination/section-restart, footer page-number
fields, heading casing/numbering, table border/shading rules, figure
captions, and (in `strict` mode) paragraph-level line spacing/indentation.

This is the **first slice in this codebase to introduce `python-docx` as
a real dependency** (already added to `pyproject.toml`:
`python-docx>=1.2.0`; `uv run pytest` confirmed 504 passed with it
present, no regressions). Every design decision below is shaped by one
question: where does code that constructs/inspects real `python-docx`
objects belong in this codebase's hexagonal layering — and the answer,
argued in Design Decision 3, is that most of it belongs in
**infrastructure**, as a deliberate, flagged exception to this
codebase's usual "thin adapter, business logic in domain/application"
split.

Ported in this slice (all from legacy lines 2016–2184, plus four helpers
forward-pulled from Slice 11's range — see "Cross-slice dependency"
below):

- `format_audit_docx` (impure: opens a `.docx` via `python-docx`,
  traverses paragraphs/tables/sections, reads raw XML parts via
  `zipfile`, builds a `ReviewResult`) — ported as a new
  `DocxAuditPort` Protocol method backed by a
  `PythonDocxAuditAdapter`, with a thin `ReviewService.audit_format`
  application-layer entry point (see Design Decision 3).
- `non_cover_margin_emu` (impure only because of its `from docx.shared
  import Cm` import — otherwise pure EMU arithmetic) — ported as a
  **pure domain function** `non_cover_margin_emu`, replacing `Cm(...)`
  with a pure EMU-per-centimeter constant (see Design Decision 4).
- `section_margin_emu` (impure: takes a real `python-docx` `Section`
  object) — ported as an infrastructure-only helper, called from inside
  `PythonDocxAuditAdapter`.
- `margins_match` (pure: dict comparison only) — ported as a pure domain
  function.
- `list_docx_parts` / `read_docx_xml` (impure: `zipfile` I/O on the
  path) — ported as `DocxAuditPort` methods, backed by the same
  filesystem-level adapter.
- `_table_has_vertical_borders_or_shading` (impure: takes a real
  `python-docx` `Table` object, reads its `_tbl.xml`) — ported as an
  infrastructure-only helper inside the adapter (public name
  `table_has_vertical_borders_or_shading`, dropping the leading
  underscore per this codebase's established convention).

### Cross-slice dependency — four helpers pulled forward from Slice 11

`format_audit_docx` calls four small functions that live later in
`tesina_harness.py`, inside what the roadmap calls Slice 11 (DOCX
Assembly, lines 2297–2862). All four are pure (no I/O, no
`python-docx` `Document` construction) and are pulled forward into this
slice as domain helpers, since `format_audit_docx` cannot function
without them:

- `_structure_parts` (2342–2363) — synthesizes the typed "structure
  parts" list from `config["structure"]` or `config["preliminaries"]`.
- `_resolve_part_text` (2366–2372) — resolves a structure part's literal
  or templated text.
- `paragraph_has_numbering` (2563–2565) — inspects a `python-docx`
  `Paragraph`'s `pPr.numPr` to detect list numbering. **Note**: this one
  *does* take a real `python-docx` `Paragraph` object, so unlike the
  other three it cannot be a pure domain function — see Design Decision 1
  for where it lands.
- `normalize_heading` (2753–2755) — **already ported** in Slice 5/9 as
  `docs.domain.markdown_text.normalize_heading` (confirmed identical
  behavior: accent-folding translation table + `.upper().strip()`). This
  slice does **not** re-port it; `format_audit_docx`'s call site simply
  imports the existing function. No change needed to `markdown_text.py`.

When Slice 11 (DOCX Assembly) is planned later, it must **not** re-port
`_structure_parts`, `_resolve_part_text`, or `paragraph_has_numbering` —
treat them as already satisfied by this slice, exactly like the
`section_by_id`/`section_path_for` precedent established since Slice 5/8.

Explicitly **not** ported in this slice (see "Out of scope" below):

- `section_by_id` (legacy line 598) — not re-ported; satisfied by
  `Template.sections` lookup
  (`next((s for s in template.sections if s.id == section_id), None)`),
  per the precedent established since Slice 5/8/9.
- `normalize_heading` (2753–2755) — already exists verbatim in
  `domain/markdown_text.py` since Slice 5/9; not re-ported.
- Everything else in `tesina_harness.py` outside lines 2016–2184 and the
  four forward-pulled helpers — in particular `build_docx`,
  `assemble_structure`, `insert_toc_field`, `_cover_base_document`,
  `set_bullet_numbering`, `clear_story_part`, and the rest of Slice 11's
  DOCX-assembly machinery (2297–2862, minus the three forward-pulled
  pure helpers) remain entirely out of scope here.

## Legacy code blocks

### `format_audit_docx` (lines 2016–2137)

```python
def format_audit_docx(docx_path: Path, strict: bool = False, config: dict[str, Any] | None = None) -> ReviewResult:
    try:
        from docx import Document
        from docx.shared import Cm, Pt
    except Exception as exc:
        raise RuntimeError(f"python-docx no está disponible: {exc}") from exc

    if not docx_path.exists():
        raise FileNotFoundError(f"No existe DOCX para auditar: {docx_path}")

    config = config or (load_document() if active_doc_id() else {})
    document = Document(str(docx_path))
    issues: list[Issue] = []
    headings = [(p.style.name if p.style else "", p.text.strip()) for p in document.paragraphs if p.text.strip()]
    heading_texts = [text for style, text in headings if style.startswith("Heading")]

    parts = _structure_parts(config)
    sections_part = next((p for p in parts if p.get("type") == "sections"), {})
    fixed_texts = [_resolve_part_text(config, p) for p in parts if p.get("type") == "fixed_text_page"]
    prelim_pag = sections_part.get("preliminary_pagination", {})
    body_pag = sections_part.get("body_pagination", {})
    restart_id = sections_part.get("body_restart_section", "")
    restart_title = ""
    if restart_id:
        try:
            restart_title = section_by_id(config, restart_id)["title"]
        except ValueError:
            restart_title = restart_id

    if strict and restart_id and len(document.sections) < 2:
        issues.append(Issue("error", "El DOCX no tiene secciones suficientes para el reinicio de paginación del cuerpo."))
    if strict and restart_title and not any(normalize_heading(restart_title) in normalize_heading(text) for text in heading_texts):
        issues.append(Issue("warning", f"No se detectó el título `{restart_title}`; no puede verificarse el reinicio de paginación."))
    if strict:
        docx_xml = read_docx_xml(docx_path, "word/document.xml")
        footer_xml = "\n".join(read_docx_xml(docx_path, name) for name in list_docx_parts(docx_path, "word/footer"))
        for fixed_text in fixed_texts:
            if fixed_text and fixed_text not in docx_xml:
                issues.append(Issue("error", "No se encontró una página de texto fijo declarada en la estructura."))
        paginated = 0
        if prelim_pag.get("format"):
            paginated += 1
            start = prelim_pag.get("start", 2)
            fmt = prelim_pag["format"]
            if not re.search(rf"<w:pgNumType\b[^>]*w:start=\"{start}\"[^>]*w:fmt=\"{fmt}\"|<w:pgNumType\b[^>]*w:fmt=\"{fmt}\"[^>]*w:start=\"{start}\"", docx_xml):
                issues.append(Issue("error", "No se detectó la paginación de preliminares declarada en la estructura."))
        if body_pag.get("format"):
            paginated += 1
            if not re.search(rf"<w:pgNumType\b[^>]*w:start=\"{body_pag.get('start', 1)}\"", docx_xml):
                issues.append(Issue("error", "La sección del cuerpo no reinicia la paginación según la estructura."))
        if paginated:
            if "PAGE" not in footer_xml:
                issues.append(Issue("error", "No se encontró campo PAGE en el pie de página de las secciones numeradas."))
            if "w:jc w:val=\"right\"" not in footer_xml:
                issues.append(Issue("error", "El campo de paginación no está alineado a la derecha."))
            if footer_xml.count("PAGE") < paginated:
                issues.append(Issue("error", "Faltan campos PAGE para las secciones paginadas declaradas."))
        expected_margins = non_cover_margin_emu(config)
        if expected_margins:
            for section_index, section in enumerate(document.sections):
                if section_index == 0:
                    continue
                actual_margins = section_margin_emu(section)
                if not margins_match(actual_margins, expected_margins):
                    issues.append(
                        Issue(
                            "error",
                            f"La sección {section_index + 1} no conserva márgenes de 2.5 cm en todos los lados.",
                        )
                    )
                    break

    for style, text in headings:
        if style == "Heading 1" and text != text.upper():
            issues.append(Issue("warning", f"Título de primer orden no está en mayúsculas sostenidas: `{text}`."))
        if style == "Heading 1" and re.match(r"^\d+(\.\d+)*\s+", text):
            issues.append(Issue("warning", f"Título de primer orden parece numerado manualmente: `{text}`."))

    for idx, table in enumerate(document.tables, start=1):
        if _table_has_vertical_borders_or_shading(table):
            issues.append(Issue("error", f"Tabla {idx} contiene bordes verticales o sombreado; el manual exige sólo líneas horizontales sin colores."))

    body_start = 0
    for i, paragraph in enumerate(document.paragraphs):
        if paragraph.style and paragraph.style.name == "Heading 1":
            body_start = i
            break
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

    if strict:
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

    return ReviewResult(issues)
```

### `non_cover_margin_emu` (lines 2140–2149)

```python
def non_cover_margin_emu(config: dict[str, Any]) -> dict[str, int]:
    from docx.shared import Cm

    margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
    expected: dict[str, int] = {}
    for key in ["top", "right", "bottom", "left"]:
        value = margins.get(key)
        if isinstance(value, (int, float)):
            expected[key] = int(Cm(float(value)))
    return expected
```

### `section_margin_emu` (lines 2152–2158)

```python
def section_margin_emu(section: Any) -> dict[str, int]:
    return {
        "top": int(section.top_margin or 0),
        "right": int(section.right_margin or 0),
        "bottom": int(section.bottom_margin or 0),
        "left": int(section.left_margin or 0),
    }
```

### `margins_match` (lines 2161–2162)

```python
def margins_match(actual: dict[str, int], expected: dict[str, int], tolerance: int = 10000) -> bool:
    return all(key in actual and key in expected and abs(actual[key] - expected[key]) <= tolerance for key in expected)
```

### `list_docx_parts` (lines 2165–2167)

```python
def list_docx_parts(docx_path: Path, prefix: str) -> list[str]:
    with zipfile.ZipFile(docx_path) as archive:
        return sorted(name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".xml"))
```

### `read_docx_xml` (lines 2170–2175)

```python
def read_docx_xml(docx_path: Path, part_name: str) -> str:
    with zipfile.ZipFile(docx_path) as archive:
        try:
            return archive.read(part_name).decode("utf-8")
        except KeyError:
            return ""
```

### `_table_has_vertical_borders_or_shading` (lines 2178–2182)

```python
def _table_has_vertical_borders_or_shading(table: Any) -> bool:
    xml = table._tbl.xml
    if re.search(r"<w:(left|right|insideV)\b", xml):
        return True
    return "<w:shd" in xml
```

### Forward-pulled helper: `_structure_parts` (lines 2342–2363)

```python
def _structure_parts(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Devuelve la lista de partes tipadas. Si no hay `structure`, la sintetiza desde `preliminaries` (legacy)."""
    structure = config.get("structure")
    if structure:
        return structure
    prelim = config.get("preliminaries", {})
    parts: list[dict[str, Any]] = [{"type": "cover_from_template"}]
    if prelim.get("blank_page", {}).get("enabled"):
        parts.append({"type": "blank_page"})
    if prelim.get("responsibility_page", {}).get("enabled"):
        parts.append({"type": "fixed_text_page", "text": prelim["responsibility_page"].get("text", RESPONSIBILITY_TEXT)})
    roman = prelim.get("roman_pagination", {})
    body_start = prelim.get("body_pagination_start", {})
    parts.append(
        {
            "type": "sections",
            "preliminary_pagination": ({"format": "lowerRoman", "start": int(prelim.get("blank_page", {}).get("start", 2))} if roman.get("enabled") else {}),
            "body_restart_section": body_start.get("section_id", ""),
            "body_pagination": {"format": body_start.get("format", "decimal"), "start": int(body_start.get("start", 1))},
        }
    )
    return parts
```

> Note: this references `RESPONSIBILITY_TEXT`, a module-level legacy
> constant. See Design Decision 1 for how this slice handles it.

### Forward-pulled helper: `_resolve_part_text` (lines 2366–2372)

```python
def _resolve_part_text(config: dict[str, Any], part: dict[str, Any]) -> str:
    if part.get("text"):
        return part["text"]
    field = part.get("text_field")
    if field:
        return str(config.get("project", {}).get(field, ""))
    return ""
```

### Forward-pulled helper: `paragraph_has_numbering` (lines 2563–2565)

```python
def paragraph_has_numbering(paragraph: Any) -> bool:
    p_pr = paragraph._p.pPr
    return bool(p_pr is not None and p_pr.numPr is not None)
```

## Verified context (read directly before writing this plan)

- `docs.domain.markdown_text.normalize_heading` (confirmed by direct
  read, lines 67–68) already matches legacy's `normalize_heading`
  byte-for-byte: same accent-folding translation table
  (`"ÁÉÍÓÚÜÑáéíóúüñ"` → `"AEIOUUNaeiouun"`), same `.translate(...)
  .upper().strip()` chain. No changes needed; this slice's
  `format_audit_docx` port imports it directly.
- `docs.domain.markdown_text.keyword_set` / `matches_keywords` (Slice 9)
  confirm the "drop the leading underscore on port" convention this
  slice follows for `paragraph_has_numbering` (already public in
  legacy, no change) and `_table_has_vertical_borders_or_shading` →
  `table_has_vertical_borders_or_shading`.
- `docs.domain.review.Issue` / `ReviewResult` (confirmed,
  `src/docs/domain/review.py`): `Issue(severity, message, code="")`
  frozen dataclass; `ReviewResult(issues: list[Issue])` frozen dataclass
  with `.passed` / `.to_markdown()` / `.to_dict()`. Both reused as-is —
  no new fields needed for this slice's issue shapes (legacy's
  `format_audit_docx` constructs every `Issue` with a positional
  `severity`/`message` and no `code=` kwarg at all — confirmed by
  re-reading every `issues.append(Issue(...))` call site above; this
  port preserves that — no codes are invented that legacy didn't have).
- `Template` (`src/docs/domain/models/template.py`, confirmed): has a
  `structure: list[dict] = []` field already (line 101) — **this
  resolves the `_structure_parts`/`config["structure"]` input question
  from the task brief**: legacy's `config.get("structure")` /
  `config.get("preliminaries")` map directly onto
  `template.structure` / `template.model_extra.get("preliminaries")`
  (since `Template` has `model_config = ConfigDict(extra="allow")` and
  no typed `preliminaries` field, `preliminaries` is `extra` data
  reachable via `template.model_extra`). However, per this codebase's
  config-as-dict convention (confirmed absent through all 9 prior
  slices), `_structure_parts`/`_resolve_part_text` are ported taking
  `config: dict[str, Any]` exactly like legacy, NOT a typed `Template`
  parameter — see Design Decision 0 below for why `config` stays the
  dict-shaped caller-supplied parameter rather than reading off
  `Template`, even though `Template.structure` exists.
- `Workspace` (confirmed, `src/docs/domain/workspace.py`): only
  `documents_dir`, `templates_dir`, `registry_path`, `doc_root(doc_id)`,
  `assets_dir(doc_id)` (the latter added in Slice 9). No DOCX-path
  concept exists. This slice does not need to add one — `audit_format`
  takes a caller-supplied `docx_path: Path`, mirroring legacy's own
  signature exactly.
- `AssetRepository` Protocol (`src/docs/domain/ports/asset_repository.py`,
  confirmed, Slice 9) — naming-convention precedent: a Protocol with
  thin, dumb I/O primitives (`ensure_dir`, `is_file`, `copy_file`,
  `glob_docx`, `remove_file`, `file_exists`), no business logic baked
  in. This slice's new `DocxAuditPort` follows the identical "thin
  primitives, business logic stays in the caller" shape — except, per
  Design Decision 3, in this slice the "caller" is the adapter itself,
  not the application layer, because the primitives needed are
  `python-docx` object accessors, not filesystem I/O verbs.
- `EvidenceRepository` Protocol (confirmed, `read_text`/`file_exists`
  already cover generic text/path I/O) — confirms no existing port
  already covers DOCX introspection; a new port is justified, not a
  reuse of an existing one.
- `ReviewService` (`src/docs/application/review.py`, confirmed):
  currently depends on exactly one port, `SectionRepository`
  (`__init__(self, repository: SectionRepository)`), and already has
  five methods: `review_document`, `review_section`, `stamp_section`,
  `build_section`, `resolve_section_path`. Adding a *second*
  constructor dependency (`DocxAuditPort`) to `ReviewService` for one
  new method would repeat Slice 9's "first service to break the
  single-port rule" precedent (`ContextPackService`) a second time —
  flagged explicitly in Design Decision 3 as the reason this slice adds
  a **new**, separate service instead of growing `ReviewService`.
- Test fixture conventions (confirmed via `tests/integration/
  test_asset_service.py`, `test_context_pack_service.py`): real
  adapters constructed directly (no mocks), `tmp_path`-based fixtures,
  `Workspace(documents_dir=..., templates_dir=...)`. No existing test in
  this codebase constructs a real `.docx` file — this slice is the
  first to need that. See Design Decision 5 for the fixture-building
  approach.
- `pyproject.toml` (confirmed): `python-docx>=1.2.0` already present;
  `uv run pytest` already run by the orchestrator with the dependency
  installed — 504 passed, no regressions, confirming the dependency is
  safe to import in both source and test code.

## Design decisions

0. **`config: dict[str, Any]` stays the parameter shape for
   `_structure_parts`/`_resolve_part_text`/`non_cover_margin_emu`/
   `format_audit_docx`'s top-level signature — not a typed `Template`
   parameter, despite `Template.structure` already existing as a typed
   field.** This is worth calling out explicitly because it could look
   inconsistent: `Template` *does* have `structure: list[dict]`, so one
   might expect this slice to take `template: Template` and read
   `template.structure` directly. Decision: keep `config: dict[str,
   Any]` everywhere, exactly mirroring every prior slice's
   "config-as-dict, no typed Config model" convention (confirmed absent
   through Slices 1–9 by direct reads of `application/evidence.py` and
   `application/review.py` in this slice and prior slices). Reasoning:
   `format_audit_docx`'s `config` parameter in legacy is **not** just
   the template — it is the full per-document config dict, which also
   carries `format.page_margins_cm` (used by `non_cover_margin_emu`)
   and `preliminaries`/`project` (used by `_structure_parts`/
   `_resolve_part_text`), none of which live on `Template` as typed
   fields (`preliminaries` is `extra` data on `Template`; `project` and
   `format` are not `Template` fields at all — confirmed by re-reading
   `template.py`'s full field list above). Introducing a typed
   `Template`-only parameter would only cover `structure` and silently
   drop the other three config namespaces this function needs — not a
   valid simplification, just a partial port. The ported signatures
   keep `config: dict[str, Any]` end to end, identical to every other
   service method in this codebase that touches `config["paths"][...]`
   /`config["format"][...]`/etc.

1. **The four forward-pulled helpers land in
   `src/docs/domain/docx_structure.py` (new module), public names,
   except `paragraph_has_numbering` which lands in the infrastructure
   adapter (Design Decision 3) because it takes a real `python-docx`
   object.** `_structure_parts` and `_resolve_part_text` are pure
   dict-in/dict-out (or dict-in/str-out) functions with zero I/O and zero
   `python-docx` object dependency — confirmed by re-reading both: every
   input is `config: dict[str, Any]` or `part: dict[str, Any]`, every
   output is a `list[dict]` or `str`. They are not generic string/markdown
   utilities (the `markdown_text.py` precedent), and they are not
   review-rule logic (the `rules.py` precedent) — they are specifically
   about interpreting the document-*structure* config shape (cover page,
   blank page, fixed-text pages, section pagination). This is a new,
   distinct concern that doesn't fit any existing domain module, which
   justifies a new module rather than bolting it onto `markdown_text.py`
   or `rules.py`. Decision: new `src/docs/domain/docx_structure.py` with
   `structure_parts(config: dict[str, Any]) -> list[dict[str, Any]]` and
   `resolve_part_text(config: dict[str, Any], part: dict[str, Any]) ->
   str` (both public, dropping legacy's leading underscore, consistent
   with `keyword_set`/`matches_keywords` in Slice 9). The
   `RESPONSIBILITY_TEXT` module-level constant `_structure_parts`
   references is ported alongside it as
   `docx_structure.DEFAULT_RESPONSIBILITY_TEXT` (legacy's exact string,
   confirmed needed since `_structure_parts` calls
   `prelim["responsibility_page"].get("text", RESPONSIBILITY_TEXT)` as a
   fallback default — this constant cannot be dropped without changing
   behavior when no `text` key is configured).

   `paragraph_has_numbering` is **not** placed in `docx_structure.py`
   despite being one of the four forward-pulled helpers, because unlike
   the other two it takes a real `python-docx` `Paragraph` object
   (`paragraph._p.pPr`) — putting it in `domain/` would mean `domain/`
   imports/depends on `python-docx` object shapes, which this codebase
   has never done and which Design Decision 3 explicitly rules out for
   exactly this reason. It is ported instead as a method/function inside
   the infrastructure adapter (Design Decision 3), public name
   `paragraph_has_numbering` unchanged (already public in legacy).

2. **New `DocxAuditPort` Protocol, minimal shape, NOT a 1:1
   `python-docx` wrapper.** The application layer (or, per Design
   Decision 3, the thin `ReviewService.audit_format` entry point) needs
   exactly one capability from this port: *"audit this DOCX file
   against this config and return the issues."* Decision: the port
   exposes a single method:

   ```python
   class DocxAuditPort(Protocol):
       def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]: ...
   ```

   This is deliberately **not** a granular wrapper exposing
   `get_paragraphs`/`get_tables`/`get_sections`/`read_xml_part` as
   separate Protocol methods. Reasoning: legacy's `format_audit_docx`
   logic is not "call port method A, then apply business rule B to the
   result" in the way `AssetService.add_asset` calls
   `AssetRepository.copy_file` — it is one continuous traversal where
   each `python-docx` object (a `Paragraph`, a `Table`, a `Section`)
   is inspected and immediately judged in the same loop iteration (e.g.
   the `Heading 1` casing check reads `style`/`text` directly off the
   same paragraph object it's iterating, with no reusable "fact"
   extracted first). Decomposing this into 10+ granular Protocol methods
   would force the application layer to re-implement legacy's traversal
   order, indexing (`body_start`, `image_paragraphs`), and cross-checks
   (figure caption = next paragraph's text) using only primitive
   accessors — which is both a much larger surface and *more* likely to
   drift from legacy's exact behavior than keeping the traversal whole.
   The single coarse `audit(...)` method is the right grain here,
   matching Design Decision 3's framing: the traversal **is** the
   capability, not a sequence of smaller ones.

   `list_docx_parts`/`read_docx_xml` (the `zipfile`-based raw XML
   readers) are exposed as two more port methods, since they operate on
   the **path**, not on a `Document` object already opened by `audit`,
   and `format_audit_docx`'s own strict-mode block calls them
   independently of the `Document` traversal:

   ```python
   class DocxAuditPort(Protocol):
       def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]: ...
       def list_parts(self, docx_path: Path, prefix: str) -> list[str]: ...
       def read_xml(self, docx_path: Path, part_name: str) -> str: ...
   ```

   `list_parts`/`read_xml` are *not* folded into `audit`'s internals only
   — they stay as separate Protocol methods because `audit` itself needs
   to call them internally too (the strict-mode footer/document XML
   checks), so exposing them lets a future caller (or test) invoke them
   independently without needing a full `Document` traversal, mirroring
   how `EvidenceRepository.read_text`/`file_exists` are independently
   useful primitives beyond any single service method.

3. **Most of `format_audit_docx`'s orchestration logic lives directly in
   the infrastructure adapter (`PythonDocxAuditAdapter.audit(...)`), NOT
   split into a "thin port call + application-layer business logic"
   shape — this is a deliberate, flagged exception to this codebase's
   usual layering, made explicit here rather than buried.** Every prior
   slice's services (`AssetService`, `ContextPackService`,
   `ReviewService`) have a clean split: ports expose dumb I/O primitives,
   and the *business logic* (which checks to run, what severity to use,
   how to build messages) lives in the application or domain layer,
   calling the port only for raw reads/writes. `format_audit_docx` does
   not have that shape. Re-reading the full legacy function: nearly every
   line **is** a `python-docx` object traversal — `document.paragraphs`,
   `paragraph.style.name`, `document.tables`, `table._tbl.xml`,
   `document.sections`, `section.top_margin`, `paragraph.paragraph_format
   .line_spacing` — interleaved with the issue-building logic, not
   separable from it the way e.g. `AssetService.add_asset`'s validation
   logic (`source.suffix.lower() != ".docx"`) is cleanly separable from
   its I/O calls (`copy_file`). Trying to force a split here — e.g. an
   adapter method that returns "raw facts" (margins, heading list, table
   border flags) for an application-layer function to then judge — would
   require inventing an intermediate DTO shape for every fact category
   this function checks (margins, headings, tables, figures, paragraph
   formatting), which is significant new surface that does not exist in
   legacy and whose only purpose would be preserving a layering purity
   that does not fit this function's actual shape. Decision: the
   `PythonDocxAuditAdapter.audit(...)` method **is** the full port of
   `format_audit_docx`'s body — it opens the `Document`, traverses it,
   and returns the complete `list[Issue]`, exactly mirroring legacy
   line-for-line. **This is flagged explicitly as the highest-judgment,
   most unusual call in this plan**: it puts substantially more logic in
   `infrastructure/` than any prior slice, and if rejected, the fallback
   is decomposing `audit` into ~6 granular port methods (one per fact
   category: paragraph headings, table border flags, section margins,
   raw XML parts, paragraph formatting, image/figure pairs) with the
   issue-building logic moved to a new `application/format_audit.py`
   module — at the cost of a much larger Protocol surface and a new DTO
   per fact category, none of which exist in legacy.

   The thin remainder lives in a new `ReviewService.audit_format`
   method, **not** growing `ReviewService`'s constructor with a second
   port dependency (which would repeat Slice 9's `ContextPackService`
   precedent a second time, this time without the "compose another
   service" justification Slice 9 used — there is no other service's
   logic to reuse here). Decision: add a **new**, separate
   `FormatAuditService` (`application/format_audit.py`) depending only on
   `DocxAuditPort`, mirroring `AssetService`'s single-new-port-per-service
   shape. `FormatAuditService.audit_format(docx_path: Path, config:
   dict[str, Any], strict: bool = False) -> ReviewResult` does exactly
   two things: the `docx_path.exists()` existence check (legacy's own
   guard, lines 2023–2024 — this one IS appropriately application-layer,
   since it's a precondition check before delegating, not a
   `python-docx` traversal) and wraps `self.port.audit(...)` in a
   `ReviewResult`. This keeps `ReviewService` untouched (no new
   constructor dependency, no precedent repetition) and gives format
   auditing its own clearly-named service, consistent with
   `AssetService` being separate from `ReviewService` despite both being
   "review-adjacent" capabilities.

4. **`non_cover_margin_emu`'s `Cm(float(value))` is replaced with pure EMU
   math — a domain function, not infrastructure.** `Cm` from
   `docx.shared` is a thin unit-conversion helper; 1 centimeter is
   **exactly** 360,000 EMU (English Metric Units) by definition in the
   OOXML spec — this is not an approximation or a `python-docx`-specific
   convention, it is the same conversion `python-docx`'s own `Cm` class
   performs internally (confirmed: `python-docx`'s `Cm(value)` is
   `Emu(int(round(value * 360000)))`). Decision: port
   `non_cover_margin_emu` as a **pure domain function** in
   `src/docs/domain/docx_structure.py` (same module as the other two
   forward-pulled pure helpers, since margin-EMU conversion is
   structurally adjacent to "interpreting document-structure config"),
   using a local constant `EMU_PER_CM = 360000` instead of importing
   `Cm` from `docx.shared`. This removes the `python-docx` import
   entirely from this function, making it as pure as `margins_match`
   (which already has no `python-docx` import) and consistent with this
   codebase's strong preference for pure, dependency-free domain
   functions wherever the underlying math doesn't actually require the
   library. The conversion is `int(round(float(value) * 360000))`
   — `round()` is added because legacy's `int(Cm(float(value)))`
   truncates via `int()` on a value `Cm` already rounded internally
   (`Cm`'s own implementation rounds to the nearest EMU before `int()`
   sees it, so the two-step `int(Cm(x))` already produces a rounded
   integer, not a truncated one) — using `round()` directly in the pure
   replacement preserves that exact numeric behavior rather than
   silently switching to truncation. **Flagged for reviewer**: verify
   `int(round(value * 360000))` produces byte-identical output to
   `int(Cm(value))` for the specific margin values this manual uses
   (2.5 cm primarily) before treating this as fully settled — the
   reasoning above is sound from `python-docx`'s documented `Cm`
   implementation, but a direct numeric comparison test (Task 1) closes
   the loop.

5. **Test strategy for the infrastructure adapter: build real, minimal
   `.docx` fixtures in-memory via `python-docx`'s own `Document()`
   API, written to `tmp_path`.** This is confirmed feasible:
   `python-docx`'s `Document()` constructor with no path argument
   creates a blank in-memory document; `document.add_heading(text,
   level=1)`, `document.add_paragraph(text)`, `document.add_table(rows,
   cols)`, and `document.save(path)` are all part of `python-docx`'s
   public API and require no external template file. Decision: a
   per-test or shared `tests/integration` helper builds a `Document()`,
   adds the specific paragraphs/headings/tables/sections the test case
   needs to exercise one check (e.g. a single `Heading 1` paragraph with
   lowercase text, to test the "not in mayúsculas sostenidas" warning),
   saves it via `document.save(tmp_path / "fixture.docx")`, then the
   test instantiates `PythonDocxAuditAdapter()` and calls
   `.audit(path, config, strict)` against the saved file. This mirrors
   the existing "no mocks, real adapters, `tmp_path`-based fixtures"
   convention (confirmed via `test_asset_service.py`/
   `test_context_pack_service.py`) — just with `python-docx`'s
   `Document()` API standing in for the manual `Path.write_text(...)`
   fixture-building every prior slice's tests use for JSON/Markdown.
   Margin/section tests use `document.sections[0].top_margin = Cm(2.5)`
   (etc.) before saving, since `python-docx` exposes section margins as
   settable attributes on the in-memory `Document` before `.save()`.
   Raw-XML-part tests (`list_parts`/`read_xml`) don't need
   `python-docx` at all — they can `zipfile.ZipFile(path, "w")` a
   minimal `.docx`-shaped zip directly, or more simply reuse a
   `python-docx`-saved document and assert against its real
   `word/document.xml` content, which is simpler and preferred since it
   avoids hand-constructing OOXML zip internals.

6. **Out-of-scope confirmation: this slice is a complete, self-contained
   port of the full 2016–2184 range plus the three domain-eligible
   forward-pulled helpers (`_structure_parts`, `_resolve_part_text`,
   `non_cover_margin_emu`'s pure-math replacement) and one
   infrastructure-eligible forward-pulled helper
   (`paragraph_has_numbering`).** Nothing in 2016–2184 is excluded:
   `format_audit_docx` (2016–2137), `non_cover_margin_emu` (2140–2149),
   `section_margin_emu` (2152–2158), `margins_match` (2161–2162),
   `list_docx_parts` (2165–2167), `read_docx_xml` (2170–2175),
   `_table_has_vertical_borders_or_shading` (2178–2182) are all
   accounted for in the task breakdown below. `normalize_heading`
   (2753–2755) is confirmed already ported (Slice 5/9) and is reused,
   not re-ported. Slice 11 retains everything else in its 2297–2862
   range (`build_docx`, `assemble_structure`, `insert_toc_field`,
   `_cover_base_document`, `set_bullet_numbering`, `clear_story_part`,
   and the rest) minus the three now-satisfied pure helpers.

## Task breakdown

### Task 1 — Pure domain functions: `docx_structure.py` module

**Files to create/modify:**
- Create `src/docs/domain/docx_structure.py`.
- Create `tests/unit/domain/test_docx_structure.py`.

**Verbatim legacy reference:** `_structure_parts` (2342–2363),
`_resolve_part_text` (2366–2372), `non_cover_margin_emu` (2140–2149,
EMU-math replacement per Design Decision 4), `margins_match`
(2161–2162).

**Planned implementation:**

```python
# src/docs/domain/docx_structure.py
from __future__ import annotations

from typing import Any

EMU_PER_CM = 360000

DEFAULT_RESPONSIBILITY_TEXT = (
    "Declaro que el presente trabajo es de mi autoría, que no ha sido "
    "presentado previamente para ningún otro título o calificación "
    "profesional, y que las fuentes de información utilizadas han sido "
    "debidamente citadas y referenciadas."
)
# Implementer note: confirm this string against legacy's actual
# RESPONSIBILITY_TEXT module-level constant before finalizing — not
# re-derived here since its definition site (outside 2016–2184) was not
# read in full for this plan; treat the above as a placeholder needing
# verification, not a settled value.

_MARGIN_KEYS = ("top", "right", "bottom", "left")


def structure_parts(config: dict[str, Any]) -> list[dict[str, Any]]:
    structure = config.get("structure")
    if structure:
        return structure
    prelim = config.get("preliminaries", {})
    parts: list[dict[str, Any]] = [{"type": "cover_from_template"}]
    if prelim.get("blank_page", {}).get("enabled"):
        parts.append({"type": "blank_page"})
    if prelim.get("responsibility_page", {}).get("enabled"):
        parts.append(
            {
                "type": "fixed_text_page",
                "text": prelim["responsibility_page"].get("text", DEFAULT_RESPONSIBILITY_TEXT),
            }
        )
    roman = prelim.get("roman_pagination", {})
    body_start = prelim.get("body_pagination_start", {})
    parts.append(
        {
            "type": "sections",
            "preliminary_pagination": (
                {"format": "lowerRoman", "start": int(prelim.get("blank_page", {}).get("start", 2))}
                if roman.get("enabled")
                else {}
            ),
            "body_restart_section": body_start.get("section_id", ""),
            "body_pagination": {
                "format": body_start.get("format", "decimal"),
                "start": int(body_start.get("start", 1)),
            },
        }
    )
    return parts


def resolve_part_text(config: dict[str, Any], part: dict[str, Any]) -> str:
    if part.get("text"):
        return part["text"]
    field = part.get("text_field")
    if field:
        return str(config.get("project", {}).get(field, ""))
    return ""


def non_cover_margin_emu(config: dict[str, Any]) -> dict[str, int]:
    margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
    expected: dict[str, int] = {}
    for key in _MARGIN_KEYS:
        value = margins.get(key)
        if isinstance(value, (int, float)):
            expected[key] = int(round(float(value) * EMU_PER_CM))
    return expected


def margins_match(actual: dict[str, int], expected: dict[str, int], tolerance: int = 10000) -> bool:
    return all(
        key in actual and key in expected and abs(actual[key] - expected[key]) <= tolerance
        for key in expected
    )
```

**Planned test code (representative):**

```python
# tests/unit/domain/test_docx_structure.py
from docs.domain.docx_structure import (
    margins_match,
    non_cover_margin_emu,
    resolve_part_text,
    structure_parts,
)


def test_structure_parts_uses_explicit_structure_when_present():
    config = {"structure": [{"type": "cover_from_template"}]}
    assert structure_parts(config) == [{"type": "cover_from_template"}]


def test_structure_parts_synthesizes_from_preliminaries_when_absent():
    config = {"preliminaries": {"roman_pagination": {"enabled": True}}}
    parts = structure_parts(config)
    assert parts[0] == {"type": "cover_from_template"}
    sections_part = next(p for p in parts if p["type"] == "sections")
    assert sections_part["preliminary_pagination"] == {"format": "lowerRoman", "start": 2}


def test_structure_parts_includes_blank_page_when_enabled():
    config = {"preliminaries": {"blank_page": {"enabled": True}}}
    parts = structure_parts(config)
    assert {"type": "blank_page"} in parts


def test_resolve_part_text_returns_literal_text_first():
    assert resolve_part_text({}, {"text": "literal"}) == "literal"


def test_resolve_part_text_resolves_text_field_from_project():
    config = {"project": {"institution": "UTN"}}
    assert resolve_part_text(config, {"text_field": "institution"}) == "UTN"


def test_resolve_part_text_returns_empty_when_neither_present():
    assert resolve_part_text({}, {}) == ""


def test_non_cover_margin_emu_converts_cm_to_emu():
    config = {"format": {"page_margins_cm": {"non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5}}}}
    expected = non_cover_margin_emu(config)
    assert expected == {"top": 900000, "right": 900000, "bottom": 900000, "left": 900000}


def test_non_cover_margin_emu_matches_python_docx_cm_conversion():
    from docx.shared import Cm

    config = {"format": {"page_margins_cm": {"non_cover": {"top": 2.5}}}}
    assert non_cover_margin_emu(config)["top"] == int(Cm(2.5))


def test_non_cover_margin_emu_skips_non_numeric_values():
    config = {"format": {"page_margins_cm": {"non_cover": {"top": "invalid"}}}}
    assert non_cover_margin_emu(config) == {}


def test_margins_match_true_within_tolerance():
    assert margins_match({"top": 900005}, {"top": 900000}) is True


def test_margins_match_false_outside_tolerance():
    assert margins_match({"top": 950000}, {"top": 900000}) is False
```

**Expected test count:** ~10 unit tests. Self-reviewable: pure functions,
no I/O, no `python-docx` object construction (only `Cm` imported in one
parity-check test). Implementer + reviewer per standard discipline since
Design Decision 4's EMU-math claim needs independent verification (see
the `test_non_cover_margin_emu_matches_python_docx_cm_conversion` parity
test above, which is the actual proof, not just an assertion).

---

### Task 2 — Port: `DocxAuditPort` Protocol

**Files to create/modify:**
- Create `src/docs/domain/ports/docx_audit_port.py`.

**Rationale:** Confirmed by direct inspection, no existing port
(`EvidenceRepository`, `SectionRepository`, `AssetRepository`,
`SourceRepository`, `DocumentRepository`, `ContextRepository`) exposes
any `python-docx`-shaped or DOCX-zip-shaped capability. A new port is
required (Design Decision 2).

**Planned implementation:**

```python
# src/docs/domain/ports/docx_audit_port.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from docs.domain.review import Issue


class DocxAuditPort(Protocol):
    def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]: ...
    def list_parts(self, docx_path: Path, prefix: str) -> list[str]: ...
    def read_xml(self, docx_path: Path, part_name: str) -> str: ...
```

**Expected test count:** 0 (bare Protocol addition, self-reviewed, per
Slice 4–9 precedent for port-growth tasks — behavior tested at the
adapter layer in Task 3).

---

### Task 3 — Infrastructure: `PythonDocxAuditAdapter`

**Files to create/modify:**
- Create `src/docs/infrastructure/docx/python_docx_audit_adapter.py`
  (new `infrastructure/docx/` subpackage — confirmed no existing
  `infrastructure/` subpackage groups DOCX-specific adapters; this is
  the first one, justified since `persistence/` is for
  filesystem/JSON-shaped storage adapters, not library-object
  traversal adapters, which is a distinct concern).
- Create `src/docs/infrastructure/docx/__init__.py`.
- Create `tests/integration/test_python_docx_audit_adapter.py`.

**Verbatim legacy reference:** `format_audit_docx` (2016–2137, full
orchestration per Design Decision 3), `section_margin_emu` (2152–2158),
`list_docx_parts` (2165–2167), `read_docx_xml` (2170–2175),
`_table_has_vertical_borders_or_shading` (2178–2182),
`paragraph_has_numbering` (2563–2565, forward-pulled).

**Planned implementation (representative skeleton — full traversal
mirrors legacy line-for-line, omitted here for length; implementer
copies the legacy body verbatim into `audit`, substituting only the
forward-pulled helper imports and `non_cover_margin_emu`'s new pure
import path):**

```python
# src/docs/infrastructure/docx/python_docx_audit_adapter.py
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from docs.domain.docx_structure import margins_match, non_cover_margin_emu, resolve_part_text, structure_parts
from docs.domain.markdown_text import normalize_heading
from docs.domain.review import Issue


def _section_margin_emu(section: Any) -> dict[str, int]:
    return {
        "top": int(section.top_margin or 0),
        "right": int(section.right_margin or 0),
        "bottom": int(section.bottom_margin or 0),
        "left": int(section.left_margin or 0),
    }


def _table_has_vertical_borders_or_shading(table: Any) -> bool:
    xml = table._tbl.xml
    if re.search(r"<w:(left|right|insideV)\b", xml):
        return True
    return "<w:shd" in xml


def paragraph_has_numbering(paragraph: Any) -> bool:
    p_pr = paragraph._p.pPr
    return bool(p_pr is not None and p_pr.numPr is not None)


class PythonDocxAuditAdapter:
    def list_parts(self, docx_path: Path, prefix: str) -> list[str]:
        with zipfile.ZipFile(docx_path) as archive:
            return sorted(name for name in archive.namelist() if name.startswith(prefix) and name.endswith(".xml"))

    def read_xml(self, docx_path: Path, part_name: str) -> str:
        with zipfile.ZipFile(docx_path) as archive:
            try:
                return archive.read(part_name).decode("utf-8")
            except KeyError:
                return ""

    def audit(self, docx_path: Path, config: dict[str, Any], strict: bool) -> list[Issue]:
        from docx import Document
        from docx.shared import Cm, Pt

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

        # ... full traversal continues exactly as legacy 2045-2137,
        # substituting `_table_has_vertical_borders_or_shading`,
        # `paragraph_has_numbering`, `_section_margin_emu` for their
        # legacy-private counterparts, `non_cover_margin_emu`/
        # `margins_match`/`structure_parts`/`resolve_part_text` for the
        # domain-module imports, and `normalize_heading` from
        # `docs.domain.markdown_text` instead of a local definition.

        return issues
```

> **Parity note on `restart_title` resolution**: legacy's
> `section_by_id(config, restart_id)["title"]` raises `ValueError` for an
> unknown id, caught and falling back to `restart_id` itself. Since
> `section_by_id` is not re-ported (Design Decision/Out-of-scope,
> consistent with Slice 5/8/9 precedent) and this adapter receives a
> plain `config: dict[str, Any]` (not a typed `Template`), the
> replacement above does a direct dict-list lookup against
> `config.get("sections", [])` mirroring the dict-shaped config legacy
> itself operates on at this call site — **not** a `Template.sections`
> lookup, because this adapter's `config` parameter is the raw dict
> (Design Decision 0), not a `Template` instance. Flagged for
> implementer: confirm `config["sections"]` is the correct key by
> checking a real config fixture/sample before finalizing — this plan's
> research did not re-derive the full config dict schema beyond what
> `format_audit_docx`/`_structure_parts`/`non_cover_margin_emu` read.

**Planned test code (representative; full suite covers each issue
category — margins, pagination XML, footer fields, heading casing,
table borders, figure captions, paragraph spacing/indent — both
triggering and not triggering):**

```python
# tests/integration/test_python_docx_audit_adapter.py
from pathlib import Path

import pytest
from docx import Document
from docx.shared import Cm

from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter


def _save_minimal_docx(tmp_path: Path, build: "Callable[[Document], None]") -> Path:
    document = Document()
    build(document)
    path = tmp_path / "fixture.docx"
    document.save(path)
    return path


def test_audit_raises_filenotfound_when_docx_missing(tmp_path):
    adapter = PythonDocxAuditAdapter()
    with pytest.raises(FileNotFoundError):
        adapter.audit(tmp_path / "missing.docx", {}, strict=False)
    # Implementer note: FileNotFoundError raised by FormatAuditService
    # (Task 4), not the adapter itself — see Design Decision 3's split.
    # This test belongs in test_format_audit_service.py, not here; moved
    # accordingly in the actual implementation. Listed here only to show
    # the guard is covered somewhere in the suite.


def test_audit_warns_on_lowercase_heading_1(tmp_path):
    def build(document):
        document.add_heading("Capítulo Uno", level=1)

    path = _save_minimal_docx(tmp_path, build)
    issues = PythonDocxAuditAdapter().audit(path, {}, strict=False)
    assert any("mayúsculas sostenidas" in issue.message for issue in issues)


def test_audit_no_warning_for_uppercase_heading_1(tmp_path):
    def build(document):
        document.add_heading("CAPÍTULO UNO", level=1)

    path = _save_minimal_docx(tmp_path, build)
    issues = PythonDocxAuditAdapter().audit(path, {}, strict=False)
    assert not any("mayúsculas sostenidas" in issue.message for issue in issues)


def test_audit_flags_table_with_vertical_borders(tmp_path):
    def build(document):
        table = document.add_table(rows=1, cols=2)
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement

        tbl_pr = table._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        left = OxmlElement("w:left")
        left.set(qn("w:val"), "single")
        borders.append(left)
        tbl_pr.append(borders)

    path = _save_minimal_docx(tmp_path, build)
    issues = PythonDocxAuditAdapter().audit(path, {}, strict=False)
    assert any("bordes verticales" in issue.message for issue in issues)


def test_audit_strict_flags_section_margin_mismatch(tmp_path):
    def build(document):
        document.add_heading("Introducción", level=1)
        document.add_section()
        document.sections[1].top_margin = Cm(1.0)
        document.sections[1].right_margin = Cm(1.0)
        document.sections[1].bottom_margin = Cm(1.0)
        document.sections[1].left_margin = Cm(1.0)

    path = _save_minimal_docx(tmp_path, build)
    config = {"format": {"page_margins_cm": {"non_cover": {"top": 2.5, "right": 2.5, "bottom": 2.5, "left": 2.5}}}}
    issues = PythonDocxAuditAdapter().audit(path, config, strict=True)
    assert any("márgenes de 2.5 cm" in issue.message for issue in issues)


def test_audit_flags_image_without_figura_caption(tmp_path):
    def build(document):
        document.add_heading("Introducción", level=1)
        paragraph = document.add_paragraph()
        run = paragraph.add_run()
        # Implementer note: inserting a real <w:drawing> run requires
        # python-docx's add_picture with a real image file, or direct
        # OXML injection of a <w:drawing> element — confirmed feasible
        # via `paragraph.add_run()._r.append(...)` with a minimal
        # OxmlElement("w:drawing"), avoiding the need for a real image
        # asset on disk.
        document.add_paragraph("Texto sin caption.")

    path = _save_minimal_docx(tmp_path, build)
    issues = PythonDocxAuditAdapter().audit(path, {}, strict=False)
    assert any("Figura" in issue.message for issue in issues)


def test_list_parts_returns_xml_parts_with_prefix(tmp_path):
    path = _save_minimal_docx(tmp_path, lambda d: d.add_paragraph("x"))
    parts = PythonDocxAuditAdapter().list_parts(path, "word/")
    assert "word/document.xml" in parts


def test_read_xml_returns_decoded_content_for_known_part(tmp_path):
    path = _save_minimal_docx(tmp_path, lambda d: d.add_paragraph("contenido único"))
    xml = PythonDocxAuditAdapter().read_xml(path, "word/document.xml")
    assert "contenido" in xml


def test_read_xml_returns_empty_string_for_unknown_part(tmp_path):
    path = _save_minimal_docx(tmp_path, lambda d: d.add_paragraph("x"))
    assert PythonDocxAuditAdapter().read_xml(path, "word/missing.xml") == ""
```

**Expected test count:** ~14–16 integration tests (one per issue
category × triggering/non-triggering, plus `list_parts`/`read_xml`
coverage). Needs implementer + reviewer: this is the highest-risk task
in the slice (Design Decision 3's flagged exception lives here), and the
`.docx` fixture-construction code itself (Design Decision 5) is new
infrastructure for this codebase's test suite that a fresh reviewer
should independently verify produces files `python-docx` actually
re-opens correctly (round-trip save/load), not just files that look
right when inspected at construction time.

---

### Task 4 — Application layer: `FormatAuditService`

**Files to create/modify:**
- Create `src/docs/application/format_audit.py`.
- Create `tests/integration/test_format_audit_service.py`.

**Verbatim legacy reference:** `format_audit_docx`'s existence-check
guard only (lines 2023–2024); the rest of the function's logic is
already ported in Task 3 per Design Decision 3.

**Planned implementation:**

```python
# src/docs/application/format_audit.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.ports.docx_audit_port import DocxAuditPort
from docs.domain.review import ReviewResult


class FormatAuditService:
    def __init__(self, port: DocxAuditPort) -> None:
        self.port = port

    def audit_format(self, docx_path: Path, config: dict[str, Any], strict: bool = False) -> ReviewResult:
        if not docx_path.exists():
            raise FileNotFoundError(f"No existe DOCX para auditar: {docx_path}")
        return ReviewResult(self.port.audit(docx_path, config, strict))
```

**Planned test code (representative):**

```python
# tests/integration/test_format_audit_service.py
from pathlib import Path

import pytest
from docx import Document

from docs.application.format_audit import FormatAuditService
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter


@pytest.fixture
def service() -> FormatAuditService:
    return FormatAuditService(PythonDocxAuditAdapter())


def test_audit_format_raises_when_docx_missing(tmp_path, service):
    with pytest.raises(FileNotFoundError):
        service.audit_format(tmp_path / "missing.docx", {})


def test_audit_format_returns_clean_result_for_compliant_docx(tmp_path, service):
    document = Document()
    document.add_heading("INTRODUCCIÓN", level=1)
    document.add_paragraph("Texto de cuerpo sin hallazgos esperables.")
    path = tmp_path / "ok.docx"
    document.save(path)
    result = service.audit_format(path, {}, strict=False)
    assert result.passed is True


def test_audit_format_returns_failed_result_when_errors_present(tmp_path, service):
    document = Document()
    document.add_heading("introducción", level=1)
    path = tmp_path / "bad.docx"
    document.save(path)
    result = service.audit_format(path, {}, strict=False)
    assert result.issues  # at least the lowercase-heading warning
```

**Expected test count:** ~3 integration tests.

---

## Out-of-scope confirmation

- **`section_by_id`** (legacy line 598) — not re-ported as a free
  function; this slice's adapter resolves `restart_title` via a direct
  `config["sections"]` dict-list lookup instead (see Task 3's parity
  note), since the adapter operates on `config: dict[str, Any]`, not a
  typed `Template` (Design Decision 0).
- **`normalize_heading`** (2753–2755) — already ported verbatim in
  Slice 5/9 (`docs.domain.markdown_text.normalize_heading`); reused, not
  re-ported, confirmed identical by direct comparison.
- **`paragraph_has_numbering`, `_structure_parts`, `_resolve_part_text`**
  — forward-pulled into this slice from Slice 11's range; Slice 11 must
  not re-port these when it is planned (see "Cross-slice dependency"
  above).
- **`build_docx`, `assemble_structure`, `insert_toc_field`,
  `_cover_base_document`, `set_bullet_numbering`, `clear_story_part`,
  and the remainder of Slice 11's 2297–2862 range** — entirely
  untouched; this slice does not construct or assemble any DOCX, only
  audits an already-produced one.
- **`run_doctor`/`DoctorResult`/`Check`** (legacy 2185+) — outside this
  slice's 2016–2184 line range; not touched.
- **Any typed `Config` model** — confirmed absent from the whole
  codebase through Slice 9; not introduced here. `config: dict[str,
  Any]` remains the parameter shape throughout, including for the new
  `docx_structure.py` functions and `FormatAuditService.audit_format`
  (Design Decision 0).
- **CLI commands invoking `audit-format`/`format-audit`** — no `cli/`
  directory exists yet (confirmed absent through Slice 9); out of scope
  until a CLI slice.

## Global constraints

- **Config-as-dict convention.** No typed `Config` Pydantic model exists
  anywhere in this codebase. `docx_structure.py`'s functions and
  `FormatAuditService.audit_format` all take `config: dict[str, Any]`
  for path/structure/format-shaped values, exactly like every prior
  slice's services (Design Decision 0).
- **Parity discipline.** Every ported function must be byte-for-byte
  behaviorally identical to the legacy block quoted above for it,
  including Spanish strings, severity levels (`"error"`/`"warning"`),
  and exact regex patterns. The one explicitly flagged *behavior*
  question is `non_cover_margin_emu`'s EMU-math replacement (Design
  Decision 4) — closed by a direct parity test against `python-docx`'s
  own `Cm` conversion (Task 1), not left as an assumption.
- **`python-docx` stays out of `domain/`.** Every domain-layer function
  in this slice (`docx_structure.py`'s three functions, plus the
  existing `margins_match`/`normalize_heading`) is verified to have zero
  `python-docx` import and zero dependency on any `python-docx` object
  shape. The one deliberate exception to "ports expose dumb I/O
  primitives, logic stays above the port" is `DocxAuditPort.audit`
  itself (Design Decision 3), flagged explicitly, not silently accepted.
- **Single-port-dependency discipline per service — preserved, not
  relaxed again.** `FormatAuditService` depends only on `DocxAuditPort`
  — a brand-new, separate service rather than growing `ReviewService`'s
  constructor with a second port, specifically to avoid repeating Slice
  9's `ContextPackService` exception a second time without an equivalent
  justification (Design Decision 3).
- **Grow-only ports, justified each time.** `DocxAuditPort` is a
  brand-new Protocol, justified against every existing port's actual
  current shape (re-confirmed in this slice's research): none of
  `EvidenceRepository`/`SectionRepository`/`AssetRepository`/
  `SourceRepository`/`DocumentRepository`/`ContextRepository` exposes any
  `python-docx`- or DOCX-zip-shaped capability.
- **New test fixture pattern, isolated to this slice's tests.** This is
  the first slice whose integration tests construct real `.docx` files
  via `python-docx`'s `Document()` API rather than writing
  JSON/Markdown text fixtures directly (Design Decision 5). No existing
  test helper is modified; the `.docx`-building helpers are local to
  `test_python_docx_audit_adapter.py`/`test_format_audit_service.py`.
- **Strict TDD per task.** Each task above is independently testable and
  committable: failing test → minimal implementation → passing test →
  commit, then independent fresh-context review, exactly as Slices 1–9.
- **No CLI, no orchestration glue in this slice.** This slice stops at
  `FormatAuditService.audit_format`. Wiring a real per-document `config`
  dict end-to-end from a config file, and exposing this through a CLI,
  is explicitly future work.
</content>
