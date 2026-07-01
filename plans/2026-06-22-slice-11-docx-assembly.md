# Slice 11 — DOCX Assembly (Core) · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 2297–2862 (`resolve_executable`
through `safe_style_name`), **excluding** three helpers already ported in
Slice 10 (`_structure_parts` 2342–2363, `_resolve_part_text` 2366–2372,
`paragraph_has_numbering` 2563–2565) and **excluding** `qa_docx`
(2862 onward, belongs to Slice 12).

## Overview / Scope — and the split decision (read this first)

This slice ports the harness's DOCX **assembly** pipeline: the capability
that takes already-rendered Markdown sections (post `build-section`) and a
pandoc-produced body `.docx`, and assembles them into the final structured
document — cover page, preliminaries (blank page, responsibility/fixed-text
pages, roman-numbered front matter), the numbered body with re-applied
paragraph/run formatting and pagination restarts, optional embedded
front/back `.docx` assets via `docxcompose`, a working table-of-contents
field, and the raw-OXML page-numbering/footer/numbering-part/TOC machinery
that makes the result open correctly in Word.

The roadmap (`plans/roadmap.md`, Slice 11 row) speculated this might split
into "core" vs. "layout/TOC/numbering". **Decision: split into two slices.**
This document plans only the first half — **Slice 11a, "DOCX Assembly
(Core)"**. The second half — TOC field insertion, the bullet-numbering
zip-surgery, the page-number-footer/section-pagination OXML helpers, and
`safe_style_name`'s style-fallback logic — is deferred to a follow-up
**Slice 11b, "DOCX Layout & TOC"**, named explicitly in "Deferred to
Slice 11b" below.

**Why split, not one slice (the actual judgment call, not a rubber stamp):**

Re-reading the full 2297–2862 range function-by-function, two genuinely
separable concerns emerge, with a clean dependency seam between them:

1. **Assembly orchestration** — "given rendered content, produce a
   structured `Document` and save it": `resolve_executable`, `build_docx`,
   `_cover_base_document`, `_build_main_document`, `_embed_assets`,
   `assemble_structure`, `add_fixed_text_page`,
   `apply_normative_paragraph_format`. These functions call *into* the
   layout/OXML helpers (`configure_*_section`, `set_bullet_numbering`,
   `ensure_bullet_numbering_part`, `insert_toc_field`) but the reverse is
   never true — nothing in group 2 calls back into group 1. That is a real
   one-directional dependency seam, not an arbitrary line drawn for size
   reasons.
2. **Raw-OXML layout utilities** — `configure_unnumbered_section`/
   `configure_numbered_body_section`/`configure_roman_preliminary_section`,
   `apply_non_cover_section_layout`, `add_page_number_footer`,
   `set_section_page_number_start`, `clear_story_part`, `set_bullet_numbering`,
   `ensure_bullet_numbering_part`, `insert_toc_field`,
   `set_update_fields_on_open`, `safe_style_name`. Every one of these is a
   **leaf-level, no-business-judgment OOXML primitive**: "set this attribute
   on this `sectPr`/`pPr`/`rPr` element", "find-and-replace a placeholder
   paragraph with a field code", "open the zip and patch this XML part".
   None of them read `config` for anything beyond raw geometry numbers
   (margins, page size) already resolved by the caller. This is a
   materially different shape from group 1, where `_build_main_document`
   and `_structure_parts`-driven branching genuinely encode the harness's
   document-structure *policy* (what counts as a preliminary page, when to
   restart numbering, which part types exist).

Splitting lets Slice 11a's task breakdown stay focused on the
"`DocxAssemblyPort`-composing service" shape (mirroring `FormatAuditService`)
without also carrying ~10 more adapter methods of pure OXML plumbing in the
same review pass, and lets a reviewer evaluate the harder layering judgment
call (Design Decision 2 below) without the noise of also checking 300 lines
of XML-attribute-setting code for typos. The two slices share one port and
one adapter class (Design Decision 2), so there is no artificial seam
imposed on the *runtime* shape — only on the *planning/review* shape, which
is exactly what "slice" is supposed to mean in this migration.

### What is ported in Slice 11a (this plan)

From legacy lines 2297–2862, **excluding** the three Slice-10-forward-pulled
helpers:

- `resolve_executable` (2297–2307)
- `build_docx` (2310–2339)
- `_cover_base_document` (2375–2391)
- `_build_main_document` (2394–2476)
- `_embed_assets` (2479–2491)
- `assemble_structure` (2494–2526)
- `add_fixed_text_page` (2529–2541)
- `apply_normative_paragraph_format` (2543–2561)

### Deferred to Slice 11b ("DOCX Layout & TOC")

- `set_bullet_numbering` (2568–2586)
- `ensure_bullet_numbering_part` (2589–2659)
- `configure_unnumbered_section` / `configure_numbered_body_section` /
  `configure_roman_preliminary_section` (2661–2687)
- `apply_non_cover_section_layout` (2689–2706)
- `add_page_number_footer` (2708–2736)
- `set_section_page_number_start` (2739–2750)
- `clear_story_part` (2758–2762)
- `insert_toc_field` (2765–2809)
- `set_update_fields_on_open` (2812–2839)
- `safe_style_name` (2842–2859)

**This is a hard dependency problem for Slice 11a's own implementation**,
flagged explicitly, not glossed over: `_build_main_document` *calls*
`configure_roman_preliminary_section`, `configure_unnumbered_section`,
`configure_numbered_body_section`, `set_section_page_number_start`,
`safe_style_name`, and `apply_normative_paragraph_format` calls
`set_bullet_numbering`; `assemble_structure` calls
`ensure_bullet_numbering_part`; `build_docx` calls `insert_toc_field`. Since
Slice 11b's functions are *callees* of Slice 11a's functions, Slice 11a
cannot be fully implemented and tested end-to-end (i.e. `build_docx`
producing a final, Word-correct `.docx`) until Slice 11b lands. See
Design Decision 1 for how this plan resolves that without blocking Slice
11a's own task breakdown.

### Already satisfied — not re-ported here

- `_structure_parts` → `docs.domain.docx_structure.structure_parts`
  (Slice 10).
- `_resolve_part_text` → `docs.domain.docx_structure.resolve_part_text`
  (Slice 10).
- `paragraph_has_numbering` → reused from
  `docs.infrastructure.docx.python_docx_audit_adapter.paragraph_has_numbering`
  (Slice 10's infrastructure copy — see "Verified context" below for why
  this slice imports that copy rather than the domain one or re-porting a
  third copy).
- `normalize_heading` → `docs.domain.markdown_text.normalize_heading`
  (Slice 5/9).

### Out of scope (confirmed, not re-derived)

- `qa_docx` and everything from legacy line 2862 onward — Slice 12.
- `run_doctor`/`Check`/`DoctorResult` — legacy 2185–2296, Slice 13.
- Any CLI surface — Slice 15.

## Legacy code blocks (verbatim, Slice 11a's portion only)

### `resolve_executable` (lines 2297–2307)

```python
def resolve_executable(name: str, fallbacks: list[Path]) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    bundled = CODEX_RUNTIME_BIN / (f"{name}.exe" if os.name == "nt" and not name.endswith(".exe") else name)
    if bundled.exists() and bundled.is_file():
        return str(bundled)
    for candidate in fallbacks:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return None
```

### `build_docx` (lines 2310–2339)

```python
def build_docx(config: dict[str, Any], output: Path | None = None) -> Path:
    pandoc = resolve_executable("pandoc", PANDOC_FALLBACKS)
    if not pandoc:
        raise RuntimeError("Pandoc no está disponible en PATH. Instálalo y vuelve a ejecutar `build-docx`.")

    sections = sorted(config["sections"], key=lambda item: item["order"])
    existing_sections = [
        Path(config["paths"]["sections_dir"]) / f"{section['order']:03d}-{section['id']}.md"
        for section in sections
        if (Path(config["paths"]["sections_dir"]) / f"{section['order']:03d}-{section['id']}.md").exists()
    ]
    if not existing_sections:
        raise RuntimeError("No hay secciones Markdown para ensamblar. Ejecuta `build-section resumen` primero.")

    output_dir = Path(config["paths"]["output_draft_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output or output_dir / "tesina-draft.docx"
    body_docx = output_dir / "tesina-body.docx"

    with tempfile.TemporaryDirectory() as tmp:
        stripped_sections: list[Path] = []
        for index, section_path in enumerate(existing_sections):
            _metadata, body = split_frontmatter(section_path.read_text(encoding="utf-8"))
            stripped = Path(tmp) / f"{index:03d}-{section_path.name}"
            stripped.write_text(body, encoding="utf-8")
            stripped_sections.append(stripped)
        subprocess.run([pandoc, *map(str, stripped_sections), "-o", str(body_docx)], check=True)
    assemble_structure(config, body_docx, output)
    insert_toc_field(output)
    return output
```

### `_cover_base_document` (lines 2375–2391)

```python
def _cover_base_document(config: dict[str, Any], leading: list[dict[str, Any]]):
    """Devuelve el Document base: portada desde asset, desde plantilla, o uno en blanco."""
    from docx import Document

    for part in leading:
        kind = part.get("type")
        if kind == "cover_from_asset":
            path = asset_path(config, part.get("asset", "cover"))
            if path.exists():
                return Document(str(path))
            return Document()
        if kind == "cover_from_template":
            template_docx = config["paths"].get("template_docx")
            if template_docx and Path(template_docx).exists():
                return Document(str(template_docx))
            return Document()
    return Document()
```

### `_build_main_document` (lines 2394–2476)

```python
def _build_main_document(config: dict[str, Any], body_docx: Path):
    """Construye el bloque principal (portada base + preliminares + cuerpo con paginación). No incluye embed_docx."""
    from docx import Document
    from docx.enum.section import WD_SECTION_START
    from docx.enum.text import WD_BREAK
    from docx.shared import Pt, RGBColor

    parts = _structure_parts(config)
    sections_part = next((p for p in parts if p.get("type") == "sections"), {"type": "sections"})
    sections_index = parts.index(sections_part) if sections_part in parts else len(parts)
    leading = parts[:sections_index]

    cover = _cover_base_document(config, leading)
    body = Document(str(body_docx))

    prelim_pag = sections_part.get("preliminary_pagination", {})
    prelim_section = cover.add_section(WD_SECTION_START.NEW_PAGE)
    if prelim_pag:
        configure_roman_preliminary_section(prelim_section, config, int(prelim_pag.get("start", 2)))
        if prelim_pag.get("format"):
            set_section_page_number_start(prelim_section, int(prelim_pag.get("start", 2)), prelim_pag["format"])
    else:
        configure_unnumbered_section(prelim_section, config)

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
                add_fixed_text_page(cover, _resolve_part_text(config, part))
            cover.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    restart_id = sections_part.get("body_restart_section", "")
    restart_heading = ""
    if restart_id:
        try:
            restart_heading = normalize_heading(section_by_id(config, restart_id)["title"])
        except ValueError:
            restart_heading = normalize_heading(restart_id)
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
            set_section_page_number_start(numbered_section, int(body_pag.get("start", 1)), body_pag.get("format", "decimal"))
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

    for table in body.tables:
        new_table = cover.add_table(rows=len(table.rows), cols=len(table.columns))
        for row_idx, row in enumerate(table.rows):
            for col_idx, cell in enumerate(row.cells):
                new_table.cell(row_idx, col_idx).text = cell.text

    return cover
```

### `_embed_assets` (lines 2479–2491)

```python
def _embed_assets(config: dict[str, Any], parts: list[dict[str, Any]], region: str) -> list[Path]:
    """Devuelve las rutas de assets embed_docx antes ('front') o después ('back') del bloque de secciones."""
    sections_index = next((i for i, p in enumerate(parts) if p.get("type") == "sections"), len(parts))
    chosen = parts[:sections_index] if region == "front" else parts[sections_index + 1:]
    paths: list[Path] = []
    for part in chosen:
        if part.get("type") != "embed_docx":
            continue
        path = asset_path(config, part.get("asset", ""))
        if not path.exists():
            raise FileNotFoundError(f"embed_docx referencia un asset inexistente: {part.get('asset')} ({path}).")
        paths.append(path)
    return paths
```

### `assemble_structure` (lines 2494–2526)

```python
def assemble_structure(config: dict[str, Any], body_docx: Path, output_docx: Path) -> None:
    """Ensambla el DOCX: bloque principal (portada+preliminares+cuerpo) + assets .docx embebidos (docxcompose)."""
    from docx import Document

    parts = _structure_parts(config)
    front = _embed_assets(config, parts, "front")
    back = _embed_assets(config, parts, "back")

    output_docx.parent.mkdir(parents=True, exist_ok=True)
    main = _build_main_document(config, body_docx)

    if not front and not back:
        main.save(str(output_docx))
        ensure_bullet_numbering_part(output_docx)
        return

    with tempfile.TemporaryDirectory(prefix="tesina_assemble_") as tmp:
        main_path = Path(tmp) / "main.docx"
        main.save(str(main_path))
        ensure_bullet_numbering_part(main_path)
        try:
            from docxcompose.composer import Composer
        except Exception as exc:
            raise RuntimeError(
                f"docxcompose no está disponible (requerido para embeber .docx): {exc}. "
                "Instala con `pip install docxcompose`."
            ) from exc
        ordered = [*front, main_path, *back]
        master = Document(str(ordered[0]))
        composer = Composer(master)
        for piece in ordered[1:]:
            composer.append(Document(str(piece)))
        composer.save(str(output_docx))
```

### `add_fixed_text_page` (lines 2529–2541)

```python
def add_fixed_text_page(document: Any, text: str) -> None:
    from docx.shared import Cm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(18)
    run = paragraph.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
```

### `apply_normative_paragraph_format` (lines 2543–2561)

```python
def apply_normative_paragraph_format(paragraph: Any, style_name: str | None, text: str, is_list: bool = False) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.space_after = Pt(18)
    if style_name == "Heading 1":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = None
    elif is_list:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.left_indent = Cm(0.63)
        set_bullet_numbering(paragraph)
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if text:
            paragraph.paragraph_format.first_line_indent = Cm(1.25)
```

## `CODEX_RUNTIME_BIN` / `PANDOC_FALLBACKS` — what they actually are

Confirmed by direct read of `tesina_harness.py` lines 1–60 (module-level
constants, defined long before the 2297–2862 range):

```python
PANDOC_FALLBACKS = [
    Path.home() / "AppData" / "Local" / "Pandoc" / "pandoc.exe",
    Path("C:/Program Files/Pandoc/pandoc.exe"),
]
...
CODEX_RUNTIME_ROOT = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
CODEX_RUNTIME_BIN = CODEX_RUNTIME_ROOT / "bin"
```

`PANDOC_FALLBACKS` is a hardcoded list of two Windows-only install paths
for a manually-downloaded Pandoc binary. `CODEX_RUNTIME_BIN` is a bundled
binaries directory under a Codex-runtime cache path — i.e. "if a sandboxed
runtime ships its own pandoc, prefer that over a bare `shutil.which`
miss, before falling back to the hardcoded list." Both are legacy's
single-machine, single-environment assumptions: no config knob exists to
override either list, and both are Windows-flavored (`AppData`,
`C:/Program Files`) with zero portability story.

**How this maps to the new architecture.** `config["paths"]` already
exists as the established namespace for filesystem locations this
codebase's services read (`paths.sections_dir`, `paths.output_draft_dir`,
`paths.prompts_dir`, `paths.fact_ledger`, `paths.template_docx` — all
confirmed by direct reads above). Decision: model executable resolution as
**caller-supplied configuration, not hardcoded module constants** —
`config["paths"]` grows two new optional keys:

- `config["paths"]["pandoc_bin"]` — an explicit override path to a pandoc
  executable, checked first.
- `config["paths"]["pandoc_fallbacks"]` — an optional `list[str]` of
  fallback paths, replacing the hardcoded `PANDOC_FALLBACKS` list.

`resolve_executable`'s `CODEX_RUNTIME_BIN`-bundled-runtime check is
**dropped, not ported** — it is a Codex-sandbox-specific assumption with no
equivalent concept anywhere in this multi-document, environment-agnostic
architecture (confirmed: no `CODEX_RUNTIME_*`-shaped constant or config key
exists anywhere in `src/docs/`), and porting it would hardcode a
third-party runtime's directory layout into a general-purpose pandoc
locator. The new `resolve_pandoc_executable(paths: dict[str, Any]) ->
str | None` (or similar; exact name decided in Task 1) checks, in order:
`shutil.which("pandoc")` → `paths.get("pandoc_bin")` if set and exists →
each entry in `paths.get("pandoc_fallbacks", [])` that exists. This is a
strict behavioral *narrowing* relative to legacy (no more
bundled-runtime-directory guess), flagged here explicitly as a deliberate
scope decision, not an oversight — see Design Decision 4.

**Confirmed via `Bash`:** `pandoc --version` succeeds in this dev
environment (`pandoc 3.10`, on `PATH`). This means `shutil.which("pandoc")`
alone resolves it here — the fallback-list code path is exercised only by
unit tests that deliberately hide `PATH`/inject a fake `paths` dict, not by
any integration test that depends on a *missing* pandoc installation.

## `docxcompose` availability — confirmed missing in this dev environment

**Confirmed via `Bash`:** `python -c "import docxcompose"` fails with
`ModuleNotFoundError` in this environment. `docxcompose` is **not** in
`pyproject.toml`'s dependencies (confirmed: only `pydantic` and
`python-docx` listed). Legacy treats it as a lazy, optional import inside
`assemble_structure`, raising `RuntimeError` if missing — this slice
preserves that exact behavior (Design Decision 5) rather than adding
`docxcompose` as a hard dependency, since the embed-front/back-`.docx`
feature is genuinely optional (`front`/`back` empty in the common case,
confirmed by `assemble_structure`'s own `if not front and not back:` early
return). **Practical consequence for this plan's test suite**: any test
exercising the `front`/`back` non-empty path will fail at
collection/runtime in this environment unless `docxcompose` is installed —
Task 5's tests are scoped to assert the `RuntimeError` message on missing
`docxcompose`, not the actual composed-document behavior, and that
behavior is explicitly flagged as untested-in-this-environment (see Task 5
and the Risks section).

## Verified context (read directly before writing this plan)

- `docs.domain.docx_structure.structure_parts` /
  `docs.domain.docx_structure.resolve_part_text` (confirmed,
  `src/docs/domain/docx_structure.py`): exact signatures
  `structure_parts(config: dict[str, Any]) -> list[dict[str, Any]]`,
  `resolve_part_text(config: dict[str, Any], part: dict[str, Any]) -> str`.
  Reused as-is.
- `docs.infrastructure.docx.python_docx_audit_adapter` (confirmed,
  `src/docs/infrastructure/docx/python_docx_audit_adapter.py`): exposes a
  **module-level** function `paragraph_has_numbering(paragraph: Any) ->
  bool` (not a method on `PythonDocxAuditAdapter`) plus the
  `table_has_vertical_borders_or_shading` helper and the
  `PythonDocxAuditAdapter` class implementing `DocxAuditPort`. Decision:
  Slice 11a's `_build_main_document` port imports this exact module-level
  `paragraph_has_numbering` function directly
  (`from docs.infrastructure.docx.python_docx_audit_adapter import
  paragraph_has_numbering`) rather than re-defining it a third time. This
  is an infrastructure→infrastructure import, which is the one direction
  this codebase's "domain has zero `python-docx` dependency" rule does not
  restrict — both modules already sit in `infrastructure/`.
  **Flagged**: this creates a same-layer cross-module dependency between
  `infrastructure/docx/python_docx_audit_adapter.py` and the new
  `infrastructure/docx/python_docx_assembly_adapter.py` (Design Decision
  2). This is acceptable (same layer, no inward-dependency violation) but
  worth a second look — an alternative is moving `paragraph_has_numbering`
  to a shared `infrastructure/docx/_shared.py` or similar so neither
  adapter "owns" a helper the other depends on; not done here to avoid
  reopening Slice 10's already-shipped module, but noted for the reviewer
  to weigh in on.
- `docs.domain.markdown_text.normalize_heading` (confirmed): unchanged,
  reused directly.
- `docs.domain.ports.docx_audit_port.DocxAuditPort` (confirmed, full file
  read): `audit`, `list_parts`, `read_xml` — three methods, all
  `python-docx`/zip-shaped read operations for *auditing* an existing
  file. **None of these cover assembly** (constructing/saving a new
  `Document`, running `subprocess`, composing via `docxcompose`) — this
  confirms `DocxAuditPort` cannot be reused or extended for this slice's
  needs without conflating two unrelated capabilities (read-only audit vs.
  write/construct), which is why Design Decision 2 below proposes a
  distinct new port.
- `docs.infrastructure.docx.python_docx_audit_adapter.PythonDocxAuditAdapter`
  (confirmed, full file read): demonstrates this codebase's established
  "fat infrastructure adapter, thin application service" exception
  (Slice 10's Design Decision 3) — `audit()` contains the *entire*
  legacy traversal/judgment logic, not just I/O primitives. This slice
  follows the same precedent for the analogous reason (see Design
  Decision 1 below) but the analogy is **not** total — flagged explicitly.
- `docs.application.format_audit.FormatAuditService` (confirmed, full file
  read): two-line service — existence-check guard, then delegate to
  `self.port.audit(...)`, wrap in `ReviewResult`. This slice's
  `DocxAssemblyService` follows the identical shape: precondition checks
  the legacy function itself performs as guards (not `python-docx`
  traversal), then delegate to the port.
- `docs.application.asset.AssetService` (confirmed, full file read):
  **`asset_path(self, doc_id: str, name: str) -> Path`** — takes `doc_id`
  explicitly, not a `config` dict. This is the single most consequential
  signature fact for this slice — see Design Decision 3 (the `doc_id`
  threading point) below; every legacy call site that did
  `asset_path(config, ...)` (`_cover_base_document`'s
  `cover_from_asset` branch, `_embed_assets`'s `embed_docx` branch) must
  be reworked to take `doc_id` as an explicit parameter and call
  `AssetService.asset_path(doc_id, name)` instead.
- `docs.domain.review.Issue` / `ReviewResult` (confirmed): not used by this
  slice's services — `build_docx`/`assemble_structure` return a `Path`,
  not a `ReviewResult`. Read only for context per the task brief; no
  reuse needed here.
- `docs.application.context_pack.ContextPackService` (confirmed, full file
  read): precedent for a service with **multiple constructor
  dependencies** (`section_repository`, `evidence_repository`,
  `evidence_service`, `review_service` — four, not one), justified in
  Slice 9 as "first service-composes-service" exception. This slice's
  `DocxAssemblyService` similarly needs more than one collaborator
  (`DocxAssemblyPort` plus `AssetService` for the `doc_id`-threading
  requirement) — see Design Decision 3 — making `ContextPackService` the
  right precedent to cite, not `FormatAuditService`'s single-port shape.
- `docs.domain.workspace.Workspace` (confirmed, full file read): only
  `documents_dir`, `templates_dir`, `registry_path`, `doc_root(doc_id)`,
  `assets_dir(doc_id)`. No DOCX-output-path or sections-dir concept exists
  yet. This slice's `build_docx`-equivalent keeps taking `output: Path |
  None = None` and reading `config["paths"]["sections_dir"]`/
  `config["paths"]["output_draft_dir"]` directly, mirroring legacy and
  consistent with this codebase's "config carries paths, `Workspace`
  carries only the doc-registry/asset-dir shape" split confirmed through
  all 10 prior slices.
- `pyproject.toml` (confirmed): `python-docx>=1.2.0` present; `docxcompose`
  **absent** (Design Decision 5 above); no `typer` yet (Slice 15).
- Pandoc availability (confirmed via `Bash`, this session): `pandoc 3.10`
  on `PATH` in this dev environment — `subprocess.run([pandoc, ...])` is
  exercisable in integration tests here, but Design Decision 6 below still
  recommends not depending on that for CI portability.

## Design decisions

1. **Most of `_build_main_document`'s body lives in the infrastructure
   adapter, not split into application-layer judgment — following Slice
   10's precedent, but the analogy is partial, flagged explicitly.**
   Re-reading `_build_main_document` line-for-line: it is dominated by
   direct `python-docx` object construction and mutation (`cover.add_section`,
   `cover.add_paragraph`, `new_run.font.name = ...`, `body.paragraphs`
   traversal) interleaved with structural decisions (is this a restart
   heading? is this the first `Heading 1`? what style maps to what).
   Exactly like Slice 10's `format_audit_docx`, this is not cleanly
   separable into "port returns facts, application judges them" without
   inventing new DTOs for "paragraph style classification" and "pagination
   restart decision" that don't exist in legacy. Decision: port
   `_build_main_document`, `_cover_base_document`, `_embed_assets`, and the
   `_structure_parts`-driven branching inside `assemble_structure` as
   adapter-internal logic on a new `PythonDocxAssemblyAdapter`, mirroring
   `PythonDocxAuditAdapter.audit`'s shape.

   **Where the analogy is partial — flagged for the reviewer, not
   smoothed over**: unlike Slice 10's `format_audit_docx`, which is a pure
   read-only traversal with no side effects beyond building a `list[Issue]`,
   this slice's functions perform `subprocess.run` (external process),
   write temp files, and (optionally) import a third-party composition
   library. Slice 10's "the traversal IS the capability" argument rests on
   the *read* traversal having no separable fact/judgment boundary; that
   argument does **not** automatically extend to "therefore subprocess
   invocation and temp-file orchestration also belong inside the same fat
   adapter method." This plan still places `build_docx`'s pandoc-invocation
   logic inside the adapter (rather than the application service) because
   `resolve_executable`'s fallback-chain logic and the `subprocess.run(...)`
   call are themselves infrastructure-shaped (external process + filesystem
   I/O, zero document-structure judgment) — but the *reason* is different
   from Slice 10's reason, and conflating the two would be sloppy. See Task
   1 for where `resolve_pandoc_executable` specifically lands (adapter, not
   domain, despite having zero `python-docx` dependency — it is still pure
   filesystem/`shutil.which` I/O, which is infrastructure by this
   codebase's own existing rule, not "anything `python-docx`-shaped").

2. **One new port, `DocxAssemblyPort` — not an extension of
   `DocxAuditPort`, and not two separate ports for "build" vs. "embed".**
   Confirmed by direct re-read of `DocxAuditPort`: its three methods
   (`audit`, `list_parts`, `read_xml`) are all *read-only* operations on an
   **already-existing** `.docx` file. This slice's capability is the
   opposite: *construct and write* a new `.docx` from Markdown sections and
   optional embedded assets. Extending `DocxAuditPort` with `build`/
   `assemble` methods would conflate "I audit files" with "I build files"
   under one Protocol name, which is a meaningful capability distinction
   worth keeping separate (the same reasoning Slice 10 itself used to
   justify a *new* port instead of extending `EvidenceRepository`).
   Decision:

   ```python
   class DocxAssemblyPort(Protocol):
       def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None: ...
       def assemble(
           self,
           config: dict[str, Any],
           body_docx: Path,
           output_docx: Path,
           *,
           cover_asset_path: Path | None,
           embed_front_paths: list[Path],
           embed_back_paths: list[Path],
       ) -> None: ...
   ```

   `render_pandoc` is kept as a **separate** narrow method (not folded into
   a single `build` mega-method) because `build_docx`'s own structure
   already separates "run pandoc to produce the body" from "assemble the
   structured document" as two sequential, independently-meaningful steps
   — and keeping them separate at the port boundary lets
   `DocxAssemblyService.build` (Task 4) own the orchestration (call pandoc,
   then call assemble, then — in Slice 11b — call TOC insertion) rather
   than burying that three-step sequence inside the adapter where a future
   reader can't see it without opening the adapter file. This mirrors how
   `ContextPackService` (precedent) composes calls to multiple narrow
   collaborator methods rather than one opaque "do everything" call.

   `assemble`'s signature takes `cover_asset_path: Path | None` and
   `embed_front_paths`/`embed_back_paths` as **pre-resolved `Path` values**,
   not raw `config`-dict asset names — this is the direct consequence of
   Design Decision 3 (the `doc_id`-threading requirement): resolving an
   asset name to a path requires `AssetService.asset_path(doc_id, name)`,
   which is an **application-layer** concern (it depends on `Workspace`),
   so the port cannot resolve these paths itself — they must be resolved
   by the calling service and passed in already-resolved. This is why
   `DocxAssemblyPort.assemble`'s signature is *not* a direct 1:1 mirror of
   legacy's `assemble_structure(config, body_docx, output_docx)` — legacy
   resolves `asset_path(config, ...)` internally; this port cannot, by
   construction, do the same.

3. **The `doc_id`-threading point — every ported function that resolved an
   asset path via legacy's `asset_path(config, ...)` now takes `doc_id`
   explicitly and goes through `AssetService.asset_path(doc_id, name)`,
   not a config-only lookup.** Confirmed by direct re-read of
   `AssetService` (`src/docs/application/asset.py`): `asset_path(self,
   doc_id: str, name: str) -> Path` — `doc_id` is a required positional
   parameter, not derived from `config`. This is a deliberate
   architectural fact specific to this codebase (multi-document, unlike
   legacy's single-document model) called out explicitly in the task
   brief, and it has two concrete consequences in this slice:

   - `_cover_base_document`'s `cover_from_asset` branch
     (`path = asset_path(config, part.get("asset", "cover"))`) — the
     ported equivalent (inside `PythonDocxAssemblyAdapter` or, more likely,
     resolved one layer up — see below) needs `doc_id` to call
     `AssetService.asset_path(doc_id, part.get("asset", "cover"))`.
   - `_embed_assets`'s `embed_docx` branch
     (`path = asset_path(config, part.get("asset", ""))`) — same
     requirement, for both `front` and `back` regions.

   **Where the resolution actually happens**: `DocxAssemblyService.build`
   (Task 4) is the layer that has both `doc_id` (passed in by its caller)
   and an `AssetService` instance (constructor-injected, per Design
   Decision 2's port signature already anticipating this). `build` is
   responsible for: calling `structure_parts(config)` (domain, already
   ported), walking the parts to find `cover_from_asset`/`embed_docx`
   entries, calling `self.asset_service.asset_path(doc_id, asset_name)`
   for each, checking existence (mirroring legacy's `FileNotFoundError`
   guard for `embed_docx`), and passing the **resolved `Path` values** into
   `self.port.assemble(...)`. This is exactly why `DocxAssemblyService`
   needs `AssetService` as a second constructor dependency (alongside
   `DocxAssemblyPort`) — confirmed against the `ContextPackService`
   precedent (Design Decision 2) — and why `assemble`'s port signature
   above takes pre-resolved paths rather than a `config` dict.

   **Practical effect on `_build_main_document`'s and `_embed_assets`'s
   ported shape**: both are still ported into the adapter (Design Decision
   1), but with their `cover_from_asset`/`embed_docx` branches' asset-name
   lookups *replaced* by reading the already-resolved `cover_asset_path`/
   `embed_front_paths`/`embed_back_paths` parameters instead of calling
   any `asset_path`-shaped function themselves. The adapter never calls
   `AssetService` directly (it has no `Workspace`/`doc_id` access by
   construction — it is a pure `python-docx`/`subprocess` adapter) — all
   asset-path resolution happens in the service, strictly above the port
   boundary. This is the cleanest way to satisfy "ports take primitives,
   services resolve domain concepts" while still keeping the bulk of
   `_build_main_document`'s traversal logic in the adapter per Design
   Decision 1.

4. **`resolve_executable`'s `CODEX_RUNTIME_BIN` bundled-runtime check is
   dropped, not ported; `PANDOC_FALLBACKS` becomes `config["paths"]`
   keys.** Already explained in full above ("`CODEX_RUNTIME_BIN` /
   `PANDOC_FALLBACKS`" section) — repeated here only as a numbered
   decision for cross-reference. **Flagged for reviewer**: confirm no
   environment this migration needs to run in actually depends on the
   Codex-runtime-bundled-pandoc behavior before treating this narrowing as
   fully safe — this plan's own confirmation (pandoc resolves via bare
   `shutil.which` in this dev environment) only proves the *common* case
   works, not that the dropped fallback path was never load-bearing
   somewhere else.

5. **`docxcompose` stays a lazy, optional import, exactly like legacy —
   not added to `pyproject.toml` as a hard dependency.** Already explained
   in full above ("`docxcompose` availability" section). The adapter's
   `assemble` method imports `docxcompose.composer.Composer` only inside
   the `front`/`back`-non-empty branch, raising the same `RuntimeError`
   message pattern as legacy on `ImportError`. Task 5's test suite asserts
   this `RuntimeError` path; it cannot assert the actual composed-output
   behavior in this environment without first `pip install docxcompose`,
   which is **not** part of this plan's scope (adding a new optional
   dependency is a decision for whoever picks up Slice 11a's tasks, not
   pre-decided here — flagged as an open question, not silently resolved).

6. **`subprocess.run([pandoc, ...])` testing strategy: real pandoc
   integration test (since it is confirmed installed here), no
   subprocess mocking, but the call site itself is isolated to one
   adapter method so a future CI environment without pandoc can `skip`
   cleanly.** Confirmed via `Bash`: `pandoc --version` succeeds in this
   dev environment (`pandoc 3.10`). Three options were weighed:
   (a) mock `subprocess.run` entirely, (b) write a fake test "pandoc"
   shell script that just copies its input to its output path, (c) use
   the real installed pandoc binary and `pytest.mark.skipif` guard if
   missing. **Decision: option (c)**, consistent with this codebase's
   established "no mocks for python-docx itself" convention (Slice 10,
   Design Decision 5) extended to "no mocks for pandoc either" — a fake
   shell script (option b) would test that *a* subprocess gets called
   with *some* arguments, not that pandoc-the-real-tool actually converts
   the stripped Markdown into a valid `.docx` body, which is the behavior
   that actually matters here. The test
   (`tests/integration/test_python_docx_assembly_adapter.py`, Task 3) is
   decorated `@pytest.mark.skipif(shutil.which("pandoc") is None, reason=
   "pandoc not installed")`, so it degrades gracefully in a pandoc-less CI
   environment rather than failing hard. **Flagged for reviewer**: this
   means the `render_pandoc` happy path has zero coverage in any CI
   environment without pandoc installed — acceptable per this plan's
   reasoning (mocking would test the wrong thing) but worth a deliberate
   "yes, we accept this CI gap" sign-off rather than discovering it later
   when CI is set up (no CI config exists yet in this repo, confirmed
   absent through all prior slices).

7. **Test-fixture strategy reuses Slice 10's "build real `.docx` fixtures
   via `python-docx`'s `Document()` API, no mocks" convention — extended
   to building a real *body* `.docx` (the pandoc-output stand-in) and a
   real *cover/template* `.docx`, since `_build_main_document` and
   `_cover_base_document` both need real files to open via
   `Document(str(path))`.** No new fixture-building pattern is introduced;
   this is a direct application of Slice 10's Design Decision 5, just with
   two real `.docx` files per test (a "body" one simulating pandoc's
   output, and optionally a "cover"/"template" one) instead of one.

## Task breakdown

### Task 1 — Domain: nothing new; infrastructure: pandoc executable resolver

**Files to create/modify:**
- Create `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`
  (new module; same `infrastructure/docx/` package as Slice 10's audit
  adapter).
- Create `tests/unit/infrastructure/test_resolve_pandoc_executable.py`.

**Verbatim legacy reference:** `resolve_executable` (2297–2307), reshaped
per Design Decision 4 (no `CODEX_RUNTIME_BIN`, `paths` dict instead of
`PANDOC_FALLBACKS` module constant).

**Why infrastructure, not domain**: despite having zero `python-docx`
import, this function does real filesystem I/O (`shutil.which`,
`Path.exists()`) — this codebase's "domain is pure, no I/O" rule
(confirmed through every prior slice) is about I/O in general, not
specifically about `python-docx`. `shutil.which`/`Path.exists` checks are
infrastructure-shaped the same way `AssetRepository.is_file` is.

**Planned implementation:**

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py (partial — this task only)
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def resolve_pandoc_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("pandoc")
    if resolved:
        return resolved
    configured = paths.get("pandoc_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("pandoc_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None
```

**Planned test code (representative):**

```python
# tests/unit/infrastructure/test_resolve_pandoc_executable.py
from pathlib import Path

from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


def test_resolve_pandoc_executable_finds_real_pandoc_on_path():
    # Confirmed installed in this dev environment (pandoc 3.10).
    assert resolve_pandoc_executable({}) is not None


def test_resolve_pandoc_executable_uses_configured_bin_when_which_misses(monkeypatch, tmp_path):
    fake_pandoc = tmp_path / "pandoc.exe"
    fake_pandoc.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_pandoc_executable({"pandoc_bin": str(fake_pandoc)})
    assert result == str(fake_pandoc)


def test_resolve_pandoc_executable_falls_back_to_fallback_list(monkeypatch, tmp_path):
    fallback = tmp_path / "fallback_pandoc.exe"
    fallback.write_text("not a real binary")
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = resolve_pandoc_executable({"pandoc_fallbacks": [str(fallback)]})
    assert result == str(fallback)


def test_resolve_pandoc_executable_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert resolve_pandoc_executable({}) is None
```

**Expected test count:** ~5 unit tests. Self-reviewable, but note the
first test depends on this dev environment's real pandoc install — flagged
as an environment-dependent test, consistent with Design Decision 6.

---

### Task 2 — Port: `DocxAssemblyPort` Protocol

**Files to create/modify:**
- Create `src/docs/domain/ports/docx_assembly_port.py`.

**Rationale:** Confirmed by direct inspection (Design Decision 2), no
existing port covers write/construct operations on `.docx` files.

**Planned implementation:**

```python
# src/docs/domain/ports/docx_assembly_port.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DocxAssemblyPort(Protocol):
    def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None: ...

    def assemble(
        self,
        config: dict[str, Any],
        body_docx: Path,
        output_docx: Path,
        *,
        cover_asset_path: Path | None,
        embed_front_paths: list[Path],
        embed_back_paths: list[Path],
    ) -> None: ...
```

**Expected test count:** 0 (bare Protocol addition, self-reviewed, per
Slice 4–10 precedent — behavior tested at the adapter layer in Task 3).

---

### Task 3 — Infrastructure: `PythonDocxAssemblyAdapter`

**Files to create/modify:**
- Extend `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`
  (adds to Task 1's `resolve_pandoc_executable`).
- Create `tests/integration/test_python_docx_assembly_adapter.py`.

**Verbatim legacy reference:** `build_docx`'s pandoc-invocation portion
only (2310–2339, the `subprocess.run` call and temp-stripped-sections
loop — the `assemble_structure`/`insert_toc_field` calls at the end of
`build_docx` move to Task 4's service orchestration, not this adapter
method), `_cover_base_document` (2375–2391), `_build_main_document`
(2394–2476, **excluding** calls into Slice-11b functions — see the
"Slice 11b stub seam" note below), `_embed_assets` (2479–2491, **with**
asset paths pre-resolved per Design Decision 3 — this adapter method does
**not** call `asset_path` itself), `assemble_structure` (2494–2526,
**excluding** the `ensure_bullet_numbering_part` call — Slice 11b),
`add_fixed_text_page` (2529–2541), `apply_normative_paragraph_format`
(2543–2561, **excluding** the `set_bullet_numbering` call — Slice 11b).

**The Slice 11b stub seam — explicit, not hidden.** Because
`configure_roman_preliminary_section`, `configure_unnumbered_section`,
`configure_numbered_body_section`, `set_section_page_number_start`,
`safe_style_name`, `set_bullet_numbering`, and `ensure_bullet_numbering_part`
do not exist yet (Slice 11b), this adapter needs **local placeholder
functions** with the same call signatures, documented inline as
"replace with Slice 11b's real implementation," so Slice 11a's own code is
syntactically complete and testable in isolation:

- `_configure_roman_preliminary_section_stub(section, config, start)`,
  `_configure_unnumbered_section_stub(section, config)`,
  `_configure_numbered_body_section_stub(section, config)`,
  `_set_section_page_number_start_stub(section, start, fmt)` — minimal
  stubs that do nothing (or, at most, the page-size/margin part already
  duplicated from `apply_non_cover_section_layout` if the implementer
  judges that sliver worth pulling forward — **not recommended**, flagged
  below).
- `_safe_style_name_stub(document, preferred_style)` — returns
  `preferred_style` unchanged (i.e. no style-fallback mapping yet).
- `_set_bullet_numbering_stub(paragraph, num_id=42)` — no-op.
- `_ensure_bullet_numbering_part_stub(docx_path, num_id=42)` — no-op.

**This means Slice 11a's own integration tests cannot assert
Word-correct page numbering, TOC, or bullet-list rendering** — those
properties only become real once Slice 11b lands and these stubs are
swapped for the real implementations. Task 3/4's tests assert only the
*structural* properties Slice 11a actually owns: correct paragraph count,
correct heading detection, correct table copying, correct section *count*
(not section *numbering format*), correct asset-embedding-path wiring.
This is flagged explicitly as the single most important scope boundary in
this plan — getting it wrong (e.g. accidentally writing a Slice 11a test
that asserts a real page-number field exists) would silently smuggle
Slice 11b's scope into this slice.

**Should the stubs be real call-throughs to Slice 11b instead of inline
stubs?** Recommendation: **no, keep them as local stubs in Slice 11a**,
removed/replaced wholesale when Slice 11b lands (the diff that adds Slice
11b's real functions should also delete this file's stub functions and
repoint the four call sites). The alternative — leaving Slice 11a's
adapter with literal `raise NotImplementedError` calls — would make
`build_docx`'s end-to-end happy path fail until Slice 11b ships, which
blocks even Slice 11a's own integration tests from running green. No-op
stubs let Slice 11a's tests assert what Slice 11a actually controls without
faking properties it doesn't.

**Planned implementation (representative skeleton — full
`_build_main_document` mirrors legacy line-for-line per Design Decision 1,
omitted here for length; implementer copies the legacy body verbatim,
substituting the stub calls, the `paragraph_has_numbering` cross-module
import, and the pre-resolved-path parameters per Design Decision 3):**

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py (continued)
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docs.domain.docx_structure import structure_parts, resolve_part_text
from docs.domain.markdown_text import normalize_heading
from docs.infrastructure.docx.python_docx_audit_adapter import paragraph_has_numbering


def _safe_style_name_stub(document: Any, preferred_style: str | None) -> str | None:
    # Placeholder for Slice 11b's safe_style_name. No style-fallback
    # mapping applied yet; returns the preferred style name unchanged.
    return preferred_style


def _set_bullet_numbering_stub(paragraph: Any, num_id: int = 42) -> None:
    # Placeholder for Slice 11b's set_bullet_numbering. No-op.
    pass


def _configure_roman_preliminary_section_stub(section: Any, config: dict[str, Any], start: int = 2) -> None:
    pass


def _configure_unnumbered_section_stub(section: Any, config: dict[str, Any]) -> None:
    pass


def _configure_numbered_body_section_stub(section: Any, config: dict[str, Any]) -> None:
    pass


def _set_section_page_number_start_stub(section: Any, start: int, fmt: str | None = None) -> None:
    pass


def _ensure_bullet_numbering_part_stub(docx_path: Path, num_id: int = 42) -> None:
    pass


def add_fixed_text_page(document: Any, text: str) -> None:
    from docx.shared import Cm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.first_line_indent = Cm(1.25)
    paragraph.paragraph_format.space_after = Pt(18)
    run = paragraph.add_run(text)
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)


def apply_normative_paragraph_format(paragraph: Any, style_name: str | None, text: str, is_list: bool = False) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    paragraph.paragraph_format.line_spacing = 1.5
    paragraph.paragraph_format.space_after = Pt(18)
    if style_name == "Heading 1":
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = None
    elif is_list:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.first_line_indent = None
        paragraph.paragraph_format.left_indent = Cm(0.63)
        _set_bullet_numbering_stub(paragraph)
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        if text:
            paragraph.paragraph_format.first_line_indent = Cm(1.25)


class PythonDocxAssemblyAdapter:
    def render_pandoc(self, pandoc_path: str, inputs: list[Path], output: Path) -> None:
        subprocess.run([pandoc_path, *map(str, inputs), "-o", str(output)], check=True)

    def _cover_base_document(self, config: dict[str, Any], cover_asset_path: Path | None, has_cover_from_asset_part: bool):
        from docx import Document

        if has_cover_from_asset_part:
            if cover_asset_path and cover_asset_path.exists():
                return Document(str(cover_asset_path))
            return Document()
        template_docx = config.get("paths", {}).get("template_docx")
        if template_docx and Path(template_docx).exists():
            return Document(str(template_docx))
        return Document()

    def _build_main_document(self, config: dict[str, Any], body_docx: Path, cover_asset_path: Path | None):
        # ... full traversal mirrors legacy 2394-2476 line-for-line,
        # substituting: structure_parts/resolve_part_text (domain imports),
        # paragraph_has_numbering (cross-module infra import),
        # normalize_heading (domain import), the four _*_stub calls above
        # in place of Slice 11b's real configure_*/set_section_page_number_start/
        # safe_style_name, and resolving the restart_heading lookup against
        # config.get("sections", []) directly (section_by_id not re-ported,
        # mirroring Slice 10's identical parity note) instead of calling
        # asset_path for the cover (already resolved by the caller per
        # Design Decision 3 — passed in as cover_asset_path).
        ...

    def assemble(
        self,
        config: dict[str, Any],
        body_docx: Path,
        output_docx: Path,
        *,
        cover_asset_path: Path | None,
        embed_front_paths: list[Path],
        embed_back_paths: list[Path],
    ) -> None:
        from docx import Document

        output_docx.parent.mkdir(parents=True, exist_ok=True)
        parts = structure_parts(config)
        has_cover_from_asset = any(p.get("type") == "cover_from_asset" for p in parts[: self._sections_index(parts)])
        main = self._build_main_document(config, body_docx, cover_asset_path if has_cover_from_asset else None)

        if not embed_front_paths and not embed_back_paths:
            main.save(str(output_docx))
            _ensure_bullet_numbering_part_stub(output_docx)
            return

        with tempfile.TemporaryDirectory(prefix="docs_assemble_") as tmp:
            main_path = Path(tmp) / "main.docx"
            main.save(str(main_path))
            _ensure_bullet_numbering_part_stub(main_path)
            try:
                from docxcompose.composer import Composer
            except Exception as exc:
                raise RuntimeError(
                    f"docxcompose no está disponible (requerido para embeber .docx): {exc}. "
                    "Instala con `pip install docxcompose`."
                ) from exc
            ordered = [*embed_front_paths, main_path, *embed_back_paths]
            master = Document(str(ordered[0]))
            composer = Composer(master)
            for piece in ordered[1:]:
                composer.append(Document(str(piece)))
            composer.save(str(output_docx))

    @staticmethod
    def _sections_index(parts: list[dict[str, Any]]) -> int:
        return next((i for i, p in enumerate(parts) if p.get("type") == "sections"), len(parts))
```

**Planned test code (representative; full suite covers: pandoc rendering
of real Markdown, blank-cover fallback, template-cover loading,
heading/paragraph/run copying with formatting, table copying, section
count when a restart heading is present, embed-front/back path wiring,
`docxcompose`-missing `RuntimeError`):**

```python
# tests/integration/test_python_docx_assembly_adapter.py
import shutil
from pathlib import Path

import pytest
from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_render_pandoc_converts_markdown_to_docx(tmp_path):
    markdown = tmp_path / "section.md"
    markdown.write_text("# Título\n\nCuerpo del texto.\n", encoding="utf-8")
    output = tmp_path / "body.docx"
    PythonDocxAssemblyAdapter().render_pandoc(shutil.which("pandoc"), [markdown], output)
    assert output.exists()
    document = Document(str(output))
    assert any("Cuerpo del texto" in p.text for p in document.paragraphs)


def _save_body_docx(tmp_path: Path) -> Path:
    document = Document()
    document.add_heading("Introducción", level=1)
    document.add_paragraph("Texto de cuerpo.")
    path = tmp_path / "body.docx"
    document.save(path)
    return path


def test_assemble_produces_output_with_blank_cover_when_no_template(tmp_path):
    body = _save_body_docx(tmp_path)
    output = tmp_path / "out.docx"
    config: dict = {}
    PythonDocxAssemblyAdapter().assemble(
        config, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[]
    )
    assert output.exists()
    document = Document(str(output))
    assert any("Introducción" in p.text for p in document.paragraphs)


def test_assemble_copies_tables_from_body(tmp_path):
    document = Document()
    document.add_heading("Capítulo", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "celda-a"
    table.cell(0, 1).text = "celda-b"
    body = tmp_path / "body.docx"
    document.save(body)

    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble({}, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[])
    result = Document(str(output))
    assert len(result.tables) == 1
    assert result.tables[0].cell(0, 0).text == "celda-a"


def test_assemble_raises_runtime_error_when_docxcompose_missing(tmp_path, monkeypatch):
    body = _save_body_docx(tmp_path)
    front_asset = tmp_path / "front.docx"
    Document().save(front_asset)
    output = tmp_path / "out.docx"
    monkeypatch.setitem(__import__("sys").modules, "docxcompose", None)
    with pytest.raises(RuntimeError, match="docxcompose"):
        PythonDocxAssemblyAdapter().assemble(
            {}, body, output, cover_asset_path=None, embed_front_paths=[front_asset], embed_back_paths=[]
        )


def test_assemble_applies_normative_paragraph_format_line_spacing(tmp_path):
    body = _save_body_docx(tmp_path)
    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble({}, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[])
    document = Document(str(output))
    body_paragraphs = [p for p in document.paragraphs if p.text.strip() == "Texto de cuerpo."]
    assert body_paragraphs[0].paragraph_format.line_spacing == 1.5
```

**Expected test count:** ~12–15 integration tests. Needs implementer +
fresh-context reviewer — this is the highest-risk task in the slice
(Design Decision 1's adapter-fat exception, the Slice-11b stub seam, and
the `doc_id`/asset-path threading all converge here). The reviewer should
specifically verify: (a) the stub functions are clearly marked and do not
silently claim Slice 11b behavior, (b) no test asserts a property only
Slice 11b's real implementations would provide (page numbers, TOC, bullet
glyphs), (c) round-trip save/reopen via `python-docx` actually works for
every fixture (per Slice 10's established round-trip-verification
discipline).

---

### Task 4 — Application: `DocxAssemblyService`

**Files to create/modify:**
- Create `src/docs/application/docx_assembly.py`.
- Create `tests/integration/test_docx_assembly_service.py`.

**Verbatim legacy reference:** `build_docx`'s orchestration shell
(2310–2339, minus the `insert_toc_field` call — Slice 11b; the pandoc
`subprocess` call itself moves to Task 3's adapter), `_embed_assets`'
asset-name-to-path resolution (2479–2491, reworked per Design Decision 3
to use `AssetService.asset_path(doc_id, name)`), `_cover_base_document`'s
`cover_from_asset` asset-name resolution (2375–2391, same rework).

**Planned implementation:**

```python
# src/docs/application/docx_assembly.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.domain.docx_structure import structure_parts
from docs.domain.ports.docx_assembly_port import DocxAssemblyPort
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


class DocxAssemblyService:
    def __init__(self, port: DocxAssemblyPort, asset_service: AssetService) -> None:
        self.port = port
        self.asset_service = asset_service

    def _sections_index(self, parts: list[dict[str, Any]]) -> int:
        return next((i for i, p in enumerate(parts) if p.get("type") == "sections"), len(parts))

    def _resolve_cover_asset_path(self, doc_id: str, parts: list[dict[str, Any]]) -> Path | None:
        leading = parts[: self._sections_index(parts)]
        for part in leading:
            if part.get("type") == "cover_from_asset":
                return self.asset_service.asset_path(doc_id, part.get("asset", "cover"))
        return None

    def _resolve_embed_paths(self, doc_id: str, parts: list[dict[str, Any]], region: str) -> list[Path]:
        sections_index = self._sections_index(parts)
        chosen = parts[:sections_index] if region == "front" else parts[sections_index + 1 :]
        paths: list[Path] = []
        for part in chosen:
            if part.get("type") != "embed_docx":
                continue
            path = self.asset_service.asset_path(doc_id, part.get("asset", ""))
            if not path.exists():
                raise FileNotFoundError(
                    f"embed_docx referencia un asset inexistente: {part.get('asset')} ({path})."
                )
            paths.append(path)
        return paths

    def assemble(self, doc_id: str, config: dict[str, Any], body_docx: Path, output_docx: Path) -> None:
        parts = structure_parts(config)
        cover_asset_path = self._resolve_cover_asset_path(doc_id, parts)
        front = self._resolve_embed_paths(doc_id, parts, "front")
        back = self._resolve_embed_paths(doc_id, parts, "back")
        self.port.assemble(
            config,
            body_docx,
            output_docx,
            cover_asset_path=cover_asset_path,
            embed_front_paths=front,
            embed_back_paths=back,
        )

    def build(self, doc_id: str, config: dict[str, Any], output: Path | None = None) -> Path:
        pandoc = resolve_pandoc_executable(config.get("paths", {}))
        if not pandoc:
            raise RuntimeError("Pandoc no está disponible en PATH. Instálalo y vuelve a ejecutar `build-docx`.")

        sections = sorted(config["sections"], key=lambda item: item["order"])
        sections_dir = Path(config["paths"]["sections_dir"])
        existing_sections = [
            sections_dir / f"{section['order']:03d}-{section['id']}.md"
            for section in sections
            if (sections_dir / f"{section['order']:03d}-{section['id']}.md").exists()
        ]
        if not existing_sections:
            raise RuntimeError("No hay secciones Markdown para ensamblar. Ejecuta `build-section resumen` primero.")

        output_dir = Path(config["paths"]["output_draft_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output or output_dir / "tesina-draft.docx"
        body_docx = output_dir / "tesina-body.docx"

        # NOTE: legacy strips YAML frontmatter from each section before
        # invoking pandoc (split_frontmatter, a function defined elsewhere
        # in tesina_harness.py, outside this slice's 2297-2862 range).
        # Confirm during implementation whether an equivalent already
        # exists in this codebase (candidate: docs.domain.markdown_text)
        # before re-deriving it here — flagged, not resolved by this plan.
        stripped_sections = self._strip_frontmatter_to_temp(existing_sections)
        self.port.render_pandoc(pandoc, stripped_sections, body_docx)
        self.assemble(doc_id, config, body_docx, output)
        # insert_toc_field(output) — deferred to Slice 11b; build() does
        # not call it yet, so the returned .docx has a literal "[[TOC]]"
        # placeholder paragraph instead of a working TOC field until
        # Slice 11b lands.
        return output
```

**Flagged gap, explicit**: `split_frontmatter` is referenced by legacy's
`build_docx` (`_metadata, body = split_frontmatter(section_path.read_text(...))`)
but its definition lives **outside** the 2297–2862 range this slice covers,
and this plan's research did not re-derive it. The implementer must
locate it (grep `tesina_harness.py` for `def split_frontmatter`) and check
whether an equivalent already exists in `docs.domain.markdown_text` (this
plan's research did not confirm either way) before writing
`_strip_frontmatter_to_temp`. This is the same category of gap as Slice
10's `RESPONSIBILITY_TEXT` placeholder flag — called out explicitly here
rather than silently assumed.

**Planned test code (representative):**

```python
# tests/integration/test_docx_assembly_service.py
from pathlib import Path

import pytest
from docx import Document

from docs.application.asset import AssetService
from docs.application.docx_assembly import DocxAssemblyService
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter


def test_assemble_resolves_cover_asset_path_via_asset_service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(repository=..., workspace=workspace)  # real FilesystemAssetRepository, per Slice 9 convention
    doc_id = "tesina-demo"
    cover_dir = workspace.assets_dir(doc_id)
    cover_dir.mkdir(parents=True)
    Document().save(cover_dir / "cover.docx")

    config = {"structure": [{"type": "cover_from_asset", "asset": "cover"}, {"type": "sections"}]}
    service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    body = tmp_path / "body.docx"
    Document().save(body)
    output = tmp_path / "out.docx"

    service.assemble(doc_id, config, body, output)
    assert output.exists()


def test_resolve_embed_paths_raises_when_asset_missing(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(repository=..., workspace=workspace)
    service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    config = {"structure": [{"type": "embed_docx", "asset": "missing"}, {"type": "sections"}]}
    parts = config["structure"]
    with pytest.raises(FileNotFoundError):
        service._resolve_embed_paths("tesina-demo", parts, "front")


def test_build_raises_when_no_markdown_sections_exist(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(repository=..., workspace=workspace)
    service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(tmp_path / "sections"), "output_draft_dir": str(tmp_path / "draft")},
    }
    (tmp_path / "sections").mkdir()
    with pytest.raises(RuntimeError, match="No hay secciones"):
        service.build("tesina-demo", config)


def test_build_raises_when_pandoc_unavailable(tmp_path, monkeypatch):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(repository=..., workspace=workspace)
    service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
    monkeypatch.setattr("shutil.which", lambda name: None)
    config = {"sections": [], "paths": {"sections_dir": str(tmp_path), "output_draft_dir": str(tmp_path)}}
    with pytest.raises(RuntimeError, match="Pandoc"):
        service.build("tesina-demo", config)
```

**Expected test count:** ~8–10 integration tests. Needs implementer +
fresh-context reviewer for the same reasons as Task 3, plus specific
verification of the `doc_id`-threading correctness (Design Decision 3) —
the reviewer should confirm `AssetService.asset_path(doc_id, name)` is
called with the right `doc_id` in every resolution path, not a
leftover `config`-only lookup.

---

## Out-of-scope confirmation

- **`_structure_parts`, `_resolve_part_text`, `paragraph_has_numbering`,
  `normalize_heading`** — all already satisfied (Slice 5/9/10); reused,
  not re-ported.
- **`set_bullet_numbering`, `ensure_bullet_numbering_part`,
  `configure_unnumbered_section`, `configure_numbered_body_section`,
  `configure_roman_preliminary_section`, `apply_non_cover_section_layout`,
  `add_page_number_footer`, `set_section_page_number_start`,
  `clear_story_part`, `insert_toc_field`, `set_update_fields_on_open`,
  `safe_style_name`** — explicitly deferred to Slice 11b, stubbed locally
  in this slice's adapter per Task 3.
- **`qa_docx`** and everything from legacy line 2862 onward — Slice 12.
- **`run_doctor`** — Slice 13.
- **Any CLI surface** (`build-docx` command wiring) — Slice 15.
- **`docxcompose` as a hard dependency** — not added; stays optional/lazy
  per Design Decision 5.
- **`split_frontmatter`** — referenced but not re-derived in this plan;
  flagged as an implementer task in Task 4, not pre-resolved.

## Global constraints

- **Config-as-dict convention preserved.** No typed `Config` model
  introduced; `config: dict[str, Any]` throughout, consistent with Slices
  1–10.
- **`python-docx`/`subprocess`/`zipfile`/`docxcompose` stay out of
  `domain/`.** Confirmed: `docs/domain/docx_structure.py` and
  `docs/domain/markdown_text.py` remain untouched by this slice; all new
  code with any of those imports lives in `infrastructure/docx/`.
- **`doc_id` threading is mandatory, not optional, for every asset-path
  resolution.** No function in this slice calls a config-only
  `asset_path`-shaped lookup; every resolution goes through
  `AssetService.asset_path(doc_id, name)` at the application layer
  (Design Decision 3).
- **Single extra collaborator, justified against the `ContextPackService`
  precedent, not invented freely.** `DocxAssemblyService` depends on
  `DocxAssemblyPort` + `AssetService` — two collaborators, justified the
  same way Slice 9 justified `ContextPackService`'s four.
- **Slice 11b seam is explicit in code, not silent.** Every stub function
  in `PythonDocxAssemblyAdapter` is named with a `_stub` suffix and a
  docstring/comment naming the Slice 11b function it stands in for, so a
  future reader (including Slice 11b's own implementer) can `grep _stub`
  and find every call site needing replacement.
- **No CLI, no `qa_docx`, no `run_doctor` glue in this slice.**
- **Strict TDD per task.** Each task above is independently testable and
  committable: failing test → minimal implementation → passing test →
  commit, then independent fresh-context review, exactly as Slices 1–10.

## Risks and open judgment calls (summary)

1. **The Slice 11a/11b split itself** (Overview section) — the dependency
   seam is real (one-directional), but it means Slice 11a's own
   integration tests cannot fully exercise `build_docx`'s real-world
   happy path (Word-correct page numbers/TOC/bullets) until Slice 11b
   lands. Mitigated by explicit `_stub`-suffixed placeholder functions
   (Task 3), but this is still a slice that ships intentionally
   incomplete behavior, which is unusual for this migration's prior 10
   slices (all of which shipped complete, independently-correct
   capabilities). **This is the single biggest deviation from this
   migration's established slicing pattern and the one most worth a
   second look before approving.**
2. **`CODEX_RUNTIME_BIN` removal** (Design Decision 4) — a behavioral
   narrowing relative to legacy, confirmed safe only for *this* dev
   environment's pandoc install, not proven safe for every environment
   this migration might run in.
3. **`docxcompose` absence** (Design Decision 5) — the embed-front/back
   feature's actual behavior is untested in this environment; only the
   `RuntimeError`-on-missing-import path is verifiable here.
4. **`split_frontmatter` gap** (Task 4) — referenced by legacy's
   `build_docx` but not re-derived by this plan; flagged for the
   implementer to resolve via direct lookup, not pre-answered.
5. **The cross-module `paragraph_has_numbering` import** (Verified
   context) — Slice 11a's assembly adapter depends on Slice 10's audit
   adapter module. Low risk (same layer, same package) but worth the
   reviewer's explicit sign-off rather than assumption.
</content>
