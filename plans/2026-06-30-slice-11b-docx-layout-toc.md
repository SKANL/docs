# Slice 11b — DOCX Layout & TOC · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 2568–2859 (`set_bullet_numbering`
through `safe_style_name`), **excluding** `normalize_heading` (2753–2755,
already ported in Slice 5/9 and reused as
`docs.domain.markdown_text.normalize_heading` — out of scope here, not
re-derived).

## Overview / Scope

Slice 11a ("DOCX Assembly (Core)", `plans/2026-06-22-slice-11-docx-assembly.md`)
ported the assembly *orchestration* — cover resolution, preliminaries,
body-paragraph/table copying, asset embedding — but explicitly deferred
seven raw-OOXML layout primitives to this slice, replacing each with a local
no-op `_stub`-suffixed placeholder inside
`src/docs/infrastructure/docx/python_docx_assembly_adapter.py`. Those stubs
let Slice 11a ship a syntactically complete, independently testable
adapter, at the declared cost that Slice 11a's own integration tests could
not assert Word-correct page numbering, bullet glyphs, or a working TOC
field (Slice 11a plan, "Deferred to Slice 11b" and Task 3's "Slice 11b stub
seam" note).

This slice, 11b, does three things:

1. **Replaces all 7 stubs with their real implementations**, repointing
   every call site inside `_build_main_document`,
   `apply_normative_paragraph_format`, and `assemble` (all in
   `python_docx_assembly_adapter.py`).
2. **Adds 5 net-new functions** that had no stub equivalent because Slice
   11a's adapter never called them directly: `apply_non_cover_section_layout`,
   `clear_story_part`, `add_page_number_footer` (all three are internal
   helpers the real `configure_*_section` functions call),
   `insert_toc_field`, and `set_update_fields_on_open` (TOC field insertion
   — previously commented out, not called at all, in
   `DocxAssemblyService.build()`).
3. **Fixes a live crash bug** in the passthrough `_safe_style_name_stub`:
   real pandoc output stamps its first body paragraph after a heading with
   style `"First Paragraph"`, which a blank `python-docx Document()` does
   not define — confirmed empirically this session (see "Verified context"
   below) to raise `KeyError` via `document.add_paragraph(style="First
   Paragraph")`. The real `safe_style_name`'s fallback-mapping logic is the
   fix.

### What is ported in Slice 11b (verbatim, legacy 2568–2859)

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

### Already satisfied — not re-ported here

- `normalize_heading` (2753–2755) → `docs.domain.markdown_text.normalize_heading`
  (Slice 5/9). Already imported and reused by
  `python_docx_assembly_adapter.py`'s current `_build_main_document`;
  nothing to do.

### Out of scope (confirmed, not re-derived)

- `qa_docx` and everything from legacy line 2862 onward — Slice 12.
- `run_doctor`/`Check`/`DoctorResult` — Slice 13.
- Any CLI surface (`build-docx` command wiring) — Slice 15.

## Legacy code blocks (verbatim — as supplied, reused without modification)

### `set_bullet_numbering` (lines 2568–2586)

```python
def set_bullet_numbering(paragraph: Any, num_id: int = 42) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        num_pr = OxmlElement("w:numPr")
        p_pr.append(num_pr)
    ilvl = num_pr.find(qn("w:ilvl"))
    if ilvl is None:
        ilvl = OxmlElement("w:ilvl")
        num_pr.append(ilvl)
    ilvl.set(qn("w:val"), "0")
    num_id_el = num_pr.find(qn("w:numId"))
    if num_id_el is None:
        num_id_el = OxmlElement("w:numId")
        num_pr.append(num_id_el)
    num_id_el.set(qn("w:val"), str(num_id))
```

### `ensure_bullet_numbering_part` (lines 2589–2659)

```python
def ensure_bullet_numbering_part(docx_path: Path, num_id: int = 42) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("w", namespace)
    ET.register_namespace("rel", rel_namespace)
    ET.register_namespace("ct", content_namespace)
    with tempfile.TemporaryDirectory(prefix="tesina_docx_numbering_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        document_xml = (tmp_path / "word" / "document.xml").read_text(encoding="utf-8")
        if f'w:numId w:val="{num_id}"' not in document_xml:
            return

        numbering_path = tmp_path / "word" / "numbering.xml"
        if numbering_path.exists():
            numbering_tree = ET.parse(numbering_path)
            numbering_root = numbering_tree.getroot()
        else:
            numbering_path.parent.mkdir(parents=True, exist_ok=True)
            numbering_root = ET.Element(f"{{{namespace}}}numbering")
            numbering_tree = ET.ElementTree(numbering_root)

        if not numbering_root.find(f".//{{{namespace}}}num[@{{{namespace}}}numId='{num_id}']"):
            abstract = ET.SubElement(numbering_root, f"{{{namespace}}}abstractNum", {f"{{{namespace}}}abstractNumId": str(num_id)})
            ET.SubElement(abstract, f"{{{namespace}}}multiLevelType", {f"{{{namespace}}}val": "hybridMultilevel"})
            lvl = ET.SubElement(abstract, f"{{{namespace}}}lvl", {f"{{{namespace}}}ilvl": "0"})
            ET.SubElement(lvl, f"{{{namespace}}}start", {f"{{{namespace}}}val": "1"})
            ET.SubElement(lvl, f"{{{namespace}}}numFmt", {f"{{{namespace}}}val": "bullet"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlText", {f"{{{namespace}}}val": "•"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlJc", {f"{{{namespace}}}val": "left"})
            p_pr = ET.SubElement(lvl, f"{{{namespace}}}pPr")
            tabs = ET.SubElement(p_pr, f"{{{namespace}}}tabs")
            ET.SubElement(tabs, f"{{{namespace}}}tab", {f"{{{namespace}}}val": "num", f"{{{namespace}}}pos": "720"})
            ET.SubElement(p_pr, f"{{{namespace}}}ind", {f"{{{namespace}}}left": "720", f"{{{namespace}}}hanging": "360"})
            r_pr = ET.SubElement(lvl, f"{{{namespace}}}rPr")
            ET.SubElement(r_pr, f"{{{namespace}}}rFonts", {f"{{{namespace}}}ascii": "Symbol", f"{{{namespace}}}hAnsi": "Symbol"})
            ET.SubElement(r_pr, f"{{{namespace}}}sz", {f"{{{namespace}}}val": "24"})
            num = ET.SubElement(numbering_root, f"{{{namespace}}}num", {f"{{{namespace}}}numId": str(num_id)})
            ET.SubElement(num, f"{{{namespace}}}abstractNumId", {f"{{{namespace}}}val": str(num_id)})
        numbering_tree.write(numbering_path, xml_declaration=True, encoding="UTF-8")

        rels_path = tmp_path / "word" / "_rels" / "document.xml.rels"
        rels_tree = ET.parse(rels_path)
        rels_root = rels_tree.getroot()
        numbering_rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        if not any(rel.get("Type") == numbering_rel_type for rel in rels_root):
            existing_ids = [int(match.group(1)) for rel in rels_root for match in [re.match(r"rId(\d+)$", rel.get("Id", ""))] if match]
            next_id = max(existing_ids or [0]) + 1
            ET.SubElement(rels_root, f"{{{rel_namespace}}}Relationship", {"Id": f"rId{next_id}", "Type": numbering_rel_type, "Target": "numbering.xml"})
            rels_tree.write(rels_path, xml_declaration=True, encoding="UTF-8")

        content_types_path = tmp_path / "[Content_Types].xml"
        content_tree = ET.parse(content_types_path)
        content_root = content_tree.getroot()
        numbering_content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
        if not any(override.get("PartName") == "/word/numbering.xml" for override in content_root):
            ET.SubElement(
                content_root,
                f"{{{content_namespace}}}Override",
                {"PartName": "/word/numbering.xml", "ContentType": numbering_content_type},
            )
            content_tree.write(content_types_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())
```

### `configure_unnumbered_section` / `configure_numbered_body_section` / `configure_roman_preliminary_section` (lines 2661–2687)

```python
def configure_unnumbered_section(section: Any, config: dict[str, Any]) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)


def configure_numbered_body_section(section: Any, config: dict[str, Any]) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    add_page_number_footer(section.footer)
    set_section_page_number_start(section, 1, "decimal")


def configure_roman_preliminary_section(section: Any, config: dict[str, Any], start: int = 2) -> None:
    apply_non_cover_section_layout(section, config)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    clear_story_part(section.header)
    clear_story_part(section.footer)
    add_page_number_footer(section.footer)
    set_section_page_number_start(section, start, "lowerRoman")
```

### `apply_non_cover_section_layout` (lines 2689–2706)

```python
def apply_non_cover_section_layout(section: Any, config: dict[str, Any]) -> None:
    from docx.shared import Cm, Inches

    if config.get("format", {}).get("page_size") == "letter":
        section.page_width = Inches(8.5)
        section.page_height = Inches(11)

    margins = config.get("format", {}).get("page_margins_cm", {}).get("non_cover", {})
    for attr, key in [
        ("top_margin", "top"),
        ("right_margin", "right"),
        ("bottom_margin", "bottom"),
        ("left_margin", "left"),
    ]:
        value = margins.get(key)
        if isinstance(value, (int, float)):
            setattr(section, attr, Cm(float(value)))
```

### `add_page_number_footer` (lines 2708–2736)

```python
def add_page_number_footer(footer: Any) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt

    paragraph = footer.paragraphs[-1] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = paragraph.add_run()
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
```

### `set_section_page_number_start` (lines 2739–2750)

```python
def set_section_page_number_start(section: Any, start: int, fmt: str | None = None) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sect_pr = section._sectPr
    pg_num_type = sect_pr.find(qn("w:pgNumType"))
    if pg_num_type is None:
        pg_num_type = OxmlElement("w:pgNumType")
        sect_pr.append(pg_num_type)
    pg_num_type.set(qn("w:start"), str(start))
    if fmt:
        pg_num_type.set(qn("w:fmt"), fmt)
```

### `clear_story_part` (lines 2758–2762)

```python
def clear_story_part(part: Any) -> None:
    element = part._element
    for child in list(element):
        element.remove(child)
    part.add_paragraph()
```

### `insert_toc_field` (lines 2765–2809)

```python
def insert_toc_field(docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool:
    try:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
    except Exception as exc:
        raise RuntimeError(f"python-docx no está disponible para insertar índice: {exc}") from exc

    document = Document(str(docx_path))
    target = None
    for paragraph in document.paragraphs:
        if (paragraph.text or "").strip() == placeholder:
            target = paragraph
            break
    if target is None:
        return False

    for run in list(target.runs)[::-1]:
        target._p.remove(run._r)

    run = target.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TOC \\o "{levels}" \\h \\z \\u '

    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")

    text = OxmlElement("w:t")
    text.text = "(El índice se actualizará al abrir el documento en Word)"

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
    document.save(str(docx_path))
    set_update_fields_on_open(docx_path)
    return True
```

### `set_update_fields_on_open` (lines 2812–2839)

```python
def set_update_fields_on_open(docx_path: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", namespace)
    with tempfile.TemporaryDirectory(prefix="tesina_docx_settings_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        settings_path = tmp_path / "word" / "settings.xml"
        if settings_path.exists():
            tree = ET.parse(settings_path)
            root = tree.getroot()
        else:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            root = ET.Element(f"{{{namespace}}}settings")
            tree = ET.ElementTree(root)

        update_fields = root.find(f"{{{namespace}}}updateFields")
        if update_fields is None:
            update_fields = ET.Element(f"{{{namespace}}}updateFields")
            root.insert(0, update_fields)
        update_fields.set(f"{{{namespace}}}val", "true")
        tree.write(settings_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())
```

### `safe_style_name` (lines 2842–2859)

```python
def safe_style_name(document: Any, preferred_style: str | None) -> str | None:
    available = {style.name for style in document.styles}
    if preferred_style in available:
        return preferred_style

    pandoc_style_map = {
        "First Paragraph": "No Spacing",
        "Body Text": "No Spacing",
        "Compact": "No Spacing",
    }
    mapped = pandoc_style_map.get(preferred_style or "")
    if mapped in available:
        return mapped
    if "Normal" in available:
        return "Normal"
    if "No Spacing" in available:
        return "No Spacing"
    return None
```

## Verified context (read directly this session)

- **`src/docs/infrastructure/docx/python_docx_assembly_adapter.py`** (full
  file read, current state, 257 lines). Confirmed exact stub definitions
  and every call site that must be repointed:
  - `_safe_style_name_stub` (lines 38–41) — called at lines 175 and 178,
    both inside `_build_main_document`'s per-paragraph loop.
  - `_set_bullet_numbering_stub` (lines 44–46) — called at line 101,
    inside `apply_normative_paragraph_format`'s `is_list` branch.
  - `_configure_roman_preliminary_section_stub` (lines 49–51) — called at
    line 144, inside `_build_main_document`'s preliminary-section setup.
  - `_configure_unnumbered_section_stub` (lines 54–56) — called at line
    150, same preliminary-section setup (the `else` branch when there is
    no roman pagination).
  - `_configure_numbered_body_section_stub` (lines 59–61) — called at line
    184, inside the body-restart-heading branch.
  - `_set_section_page_number_start_stub` (lines 64–66) — called at lines
    146 and 185 (preliminary section and numbered-body section
    respectively).
  - `_ensure_bullet_numbering_part_stub` (lines 69–71) — called at lines
    233 and 239, inside `assemble` (the no-embed early-return path and the
    embed-via-`docxcompose` path).
  - The stub-seam comment block spans lines 28–35 ("Slice 11b stub seam —
    explicit, not hidden"). Once Task 5 below removes the last three
    stubs, this entire comment block is deleted (see Task 5).
  - Module-level imports today: `shutil`, `subprocess`, `tempfile`,
    `pathlib.Path`, `typing.Any`, plus the three domain/infra imports
    (`structure_parts`/`resolve_part_text`, `normalize_heading`,
    `paragraph_has_numbering`). **No `zipfile`, `re`, or
    `xml.etree.ElementTree` import exists yet** — Tasks 3 and 6 add these
    at module level (Design Decision 5).
  - Every existing `python-docx`-package import (`from docx import
    Document`, `from docx.oxml import OxmlElement`, etc.) is lazy —
    imported inside the function body that needs it, never at module top
    level. This is an established convention in this file (confirmed
    across every current function) and this slice's new functions follow
    it identically (Design Decision 5).
- **`src/docs/infrastructure/docx/python_docx_audit_adapter.py`** (Slice
  10, full file read). Confirmed the only existing zip precedent:
  `list_parts` and `read_xml`, both **read-only**
  (`zipfile.ZipFile(docx_path)` opened for reading, `archive.namelist()`/
  `archive.read(...)`). **No extract-mutate-rezip helper exists anywhere in
  this codebase yet** — `ensure_bullet_numbering_part` (Task 3) and
  `set_update_fields_on_open` (Task 6) are the first code in this migration
  that opens a `.docx` zip, mutates XML parts, and rewrites the archive.
  There is nothing to reuse beyond the general "a `.docx` is a zip" fact
  already established by Slice 10; see Design Decision 2 for why this plan
  does not invent a shared "patch this XML part" abstraction across the
  two call sites.
- **`src/docs/domain/docx_structure.py`** (full file read). Confirmed
  `non_cover_margin_emu`/`margins_match` exist but serve the *audit*
  adapter's EMU-tolerance comparison — a different shape from
  `apply_non_cover_section_layout`'s direct `Cm(...)`-set from
  `config["format"]["page_margins_cm"]["non_cover"]`. **Not reused here** —
  confirmed no signature overlap makes reuse meaningful; `Task 4` ports
  `apply_non_cover_section_layout` reading the raw cm dict directly, same
  as legacy, not routed through the domain audit helper.
- **`src/docs/domain/ports/docx_assembly_port.py`** (full file read):
  current `Protocol` has exactly two methods, `render_pandoc` and
  `assemble`. **No method exists yet for TOC insertion** — Task 6 adds a
  third Protocol method, `insert_toc_field` (Design Decision 3).
- **`src/docs/application/docx_assembly.py`** (full file read). Confirmed
  two facts that update Slice 11a's plan text:
  1. The `split_frontmatter` gap Slice 11a's plan flagged as "referenced
     but not re-derived" is **already resolved** in the shipped code —
     `DocxAssemblyService._strip_frontmatter_to_temp` imports and calls
     `docs.domain.markdown_text.split_frontmatter` directly. Nothing to do
     here; noted only so this plan doesn't re-flag an already-closed gap.
  2. `DocxAssemblyService.build()` (lines 59–88) contains the exact
     deferred-TOC comment this slice must resolve: `# insert_toc_field(output)
     — deferred to Slice 11b; build() does not call it yet, so the
     returned .docx has a literal "[[TOC]]" placeholder paragraph instead
     of a working TOC field until Slice 11b lands.` Task 6 replaces that
     comment with a real `self.port.insert_toc_field(output)` call.
- **`pyproject.toml`** (confirmed): `python-docx>=1.2.0` present;
  `docxcompose` absent (unaffected by this slice); no new third-party
  dependency is needed for this slice — `zipfile` and
  `xml.etree.ElementTree` are both standard library, already the exact
  toolset Slice 10 used for its read-only zip access.
- **Empirically confirmed this session** (`pandoc 3.10` on `PATH`, via
  direct `Bash` invocation, not assumed): converting a two-paragraph
  Markdown file (`# Título` + a body paragraph) through pandoc produces a
  `.docx` where the heading paragraph has style `"Heading 1"` and the
  **very next** paragraph has style `"First Paragraph"`. Separately
  confirmed a blank `python-docx Document()`'s style collection contains
  `"Normal"`, `"No Spacing"`, `"Heading 1"`, `"List Bullet"`, and `"Body
  Text"` — but **not** `"First Paragraph"` and **not** `"Compact"`. This
  is the exact crash scenario `_safe_style_name_stub`'s current
  passthrough hits (`document.add_paragraph(style="First Paragraph")` →
  `KeyError`, since `"First Paragraph"` doesn't exist in a blank cover's
  style sheet) and the exact case the real `safe_style_name`'s
  `pandoc_style_map` (`"First Paragraph"` → `"No Spacing"`) exists to
  cover. Task 1's regression test exercises exactly this pandoc-output-vs-
  blank-cover pairing.

## Design decisions

1. **Task granularity: six tasks, ordered independent-fix-first, then
   increasing zip/XML risk, then the cross-cutting section-layout group,
   then TOC last.** Following this migration's "vertical slice, testable
   increment" sizing (Slice 11a used four tasks for eight ported
   functions; this slice ports twelve functions across six tasks — roughly
   the same function-per-task density, split further where a reviewer
   could plausibly approve one task while rejecting a sibling):
   - Task 1 (`safe_style_name`) is fully independent of every other task
     and fixes a live crash — no reason to sequence it after anything
     else.
   - Tasks 2/3 (`set_bullet_numbering` / `ensure_bullet_numbering_part`)
     are split because they differ sharply in risk shape: Task 2 is a
     small, paragraph-scoped OXML edit with no zip I/O; Task 3 is this
     migration's **first zip-rewrite** capability (extract, multi-file XML
     mutation across three separate archive members, rezip) — bundling
     them would let a reviewer's easy approval of Task 2 paper over Task
     3's materially higher risk.
   - Task 4 (the shared section/footer/pagination primitives —
     `apply_non_cover_section_layout`, `clear_story_part`,
     `add_page_number_footer`, `set_section_page_number_start`) is kept
     separate from Task 5 (the three `configure_*_section` functions that
     call them) because Task 4's functions are independently unit-testable
     leaf primitives with no dependency on `structure_parts`-driven
     branching, while Task 5 is where the actual stub call-site repointing
     and the "does the whole `_build_main_document` preliminary/body
     section wiring produce Word-correct sections" integration assertion
     happens — folding them together would make Task 5's review surface
     both "are these four OXML primitives individually correct" and "is
     the wiring correct" at once, which is exactly the kind of task a
     reviewer might want to split approval on.
   - Task 6 (`insert_toc_field` + `set_update_fields_on_open`) is last
     because it is the only task that touches `DocxAssemblyService.build()`
     (application layer, not just the adapter) and the only task that
     changes the `DocxAssemblyPort` Protocol shape — a natural final step
     once every adapter-internal stub is gone.

2. **No shared "patch this XML part in a zip" abstraction — `ensure_bullet_numbering_part`
   and `set_update_fields_on_open` are ported verbatim as two independent
   extract-mutate-rezip functions, not refactored into one generic helper.**
   Both functions share the same *shape* (extract to a temp dir, `ET.parse`
   or construct a part, mutate, rezip), but operate on entirely different
   archive members with different XML schemas and different
   existence-branching logic (`numbering.xml` + `document.xml.rels` +
   `[Content_Types].xml`, three files, versus `settings.xml`, one file).
   Only two call sites exist in the entire ported range. Inventing a
   parameterized "generic OOXML part patcher" for two call sites this
   different would need enough parameters (namespace registration, which
   files to touch, per-file existence/mutation logic) that it would not
   meaningfully reduce duplication — it would just move the same logic
   behind an extra layer of indirection. Decision: port both verbatim
   (YAGNI), flagged here as a legitimate future refactor candidate if a
   third zip-mutation call site ever appears, but not attempted now.

3. **`insert_toc_field` becomes a third `DocxAssemblyPort` Protocol method,
   not a bare module-level import like `resolve_pandoc_executable`.**
   Slice 11a's Design Decision 4 already established a precedent for
   *not* routing every adapter-module function through the Protocol:
   `resolve_pandoc_executable` is imported directly by
   `DocxAssemblyService` because it is a pure filesystem lookup with no
   adapter-state dependency, used only to decide what to pass *into* a
   port call. `insert_toc_field` is different in kind: like `assemble` and
   `render_pandoc`, it is itself a `.docx`-file-mutating capability with
   no separable "fact vs. judgment" split — exactly the shape the existing
   two Protocol methods already have. Routing it through the Protocol
   keeps `DocxAssemblyService.build()`'s three real capabilities
   (`render_pandoc`, `assemble`, `insert_toc_field`) uniformly swappable
   and testable via a fake port, while `resolve_pandoc_executable` (a
   precondition check, not a capability) correctly stays a bare import.
   Signature added to `DocxAssemblyPort`:

   ```python
   def insert_toc_field(self, docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool: ...
   ```

   `DocxAssemblyService.build()`'s deferred-comment line becomes:

   ```python
   self.assemble(doc_id, config, body_docx, output)
   self.port.insert_toc_field(output)
   return output
   ```

   Called unconditionally, exactly matching legacy `build_docx`'s
   unconditional `insert_toc_field(output)` call — `insert_toc_field`
   itself already handles the "no `[[TOC]]` placeholder present" case by
   returning `False` without raising (confirmed in the legacy body: `if
   target is None: return False`), so no caller-side guard is needed.

4. **`num_id=42` stays a hardcoded default parameter on both
   `set_bullet_numbering` and `ensure_bullet_numbering_part` — no new
   config knob.** Confirmed: every call site in the ported range
   (`apply_normative_paragraph_format`'s `set_bullet_numbering(paragraph)`,
   `assemble`'s `ensure_bullet_numbering_part(docx_path)`) omits the
   `num_id` argument, relying on the shared default. Since both functions
   default to the same literal `42` and no caller ever overrides it,
   there is no coordination problem to solve and no reason to introduce a
   `config["format"]["bullet_num_id"]`-shaped key this slice's scope
   doesn't ask for (YAGNI) — ported as an unexplained magic-number default,
   exactly as legacy has it, flagged here rather than silently carried
   over unremarked.

5. **New module-level imports (`re`, `zipfile`, `xml.etree.ElementTree as ET`)
   go at the top of `python_docx_assembly_adapter.py`, mirroring Slice
   10's `python_docx_audit_adapter.py` exactly; `python-docx`-package
   imports (`docx`, `docx.oxml`, `docx.shared`, `docx.enum.*`) stay
   function-local, matching this file's existing convention.** Confirmed
   both facts directly: Slice 10's audit adapter imports `re` and
   `zipfile` at module top (never lazily) because they are standard
   library with no import-order hazard; this slice's Task 3 and Task 6
   need the identical stdlib imports for the same reason, plus
   `xml.etree.ElementTree` (also stdlib, not yet imported anywhere in this
   file). Meanwhile every current function in
   `python_docx_assembly_adapter.py` imports `python-docx` symbols lazily
   inside the function body — this slice's new functions
   (`add_page_number_footer`, `set_section_page_number_start`,
   `insert_toc_field`, etc.) follow that exact pattern, not a new one.

5.1. **`defusedxml` is added as a new dependency (user decision, 2026-06-30,
   superseding this plan's original Risk #6 draft) and used for every
   `ET.parse(...)` call that reads XML pulled out of a `.docx` zip in Task
   3 and Task 6 — `ET.SubElement`/`ET.Element`/`ET.ElementTree`/`.write()`/
   `register_namespace` stay on stdlib `xml.etree.ElementTree`, since
   `defusedxml` only hardens the *parsing* entry points (it has no
   construction/serialization API of its own — its `parse()`/`fromstring()`
   return ordinary `xml.etree.ElementTree` objects, fully interoperable
   with stdlib `ET.SubElement`/`.write()`).** Module-level imports become:
   `import xml.etree.ElementTree as ET` (construction/writing, as
   originally planned) **plus** `from defusedxml.ElementTree import parse
   as safe_parse` (parsing only). Every `ET.parse(existing_path)` call in
   Task 3 (`numbering_path`, `rels_path`, `content_types_path`) and Task 6
   (`settings_path`) becomes `safe_parse(existing_path)` instead — the
   returned tree is used identically afterward (`.getroot()`,
   `ET.SubElement(root, ...)`, `tree.write(...)` all unchanged). **Slice
   10's `read_xml`/`list_parts` do NOT need retrofitting** — confirmed by
   direct re-read of `src/docs/infrastructure/docx/python_docx_audit_adapter.py`
   lines 36-45 during this revision: both methods only call
   `archive.read(...).decode("utf-8")` / `archive.namelist()` — neither
   calls `ET.parse`/`ET.fromstring` at all, so there is no unsafe XML
   *parsing* in Slice 10 to harden, only raw byte/text extraction. The
   original Risk #6 draft's claim that Slice 10 "established the
   stdlib-ElementTree-for-.docx-XML precedent for reads" was imprecise —
   corrected here. `pyproject.toml` gains `defusedxml` in Task 3 (the
   first task that needs it); Task 6 reuses the same dependency, no
   second addition.

6. **Test strategy: real `.docx`/zip round-trips throughout, no mocking of
   `python-docx` or `zipfile` — extending Slice 10's Design Decision 5 and
   Slice 11a's Design Decision 7 to zip-*writing* verification.** Every
   task's tests build a real fixture via `python-docx`'s `Document()` API
   (or, for zip-level assertions, `zipfile.ZipFile` read-back), call the
   real function under test, then **re-open the saved file** — via
   `python-docx` for paragraph/run/section-level assertions, or via
   `zipfile.ZipFile`/`ET.parse` for archive-member-level assertions
   (`word/numbering.xml` exists with the right `abstractNum`/`num`
   elements; `word/_rels/document.xml.rels` has the numbering
   relationship; `[Content_Types].xml` has the `Override`; `word/settings.xml`
   has `w:updateFields w:val="true"`; a section's `_sectPr` has the right
   `w:pgNumType` attributes). This is the same discipline Slice 10 and
   Slice 11a already established — the difference is these tests are the
   first in this migration to assert the zip was *rewritten* correctly,
   not just read.

7. **Task 1's regression test uses real pandoc when available, `skipif`-
   guarded exactly like Slice 11a's `render_pandoc` tests — not a
   synthetic fixture that merely sets `paragraph.style` to a fake "First
   Paragraph"-named style object.** A synthetic fixture (e.g.
   monkeypatching a paragraph's `.style.name` to `"First Paragraph"`
   without that style actually existing in *any* document) would test the
   fallback-mapping logic in isolation but would not reproduce the actual
   crash mechanism (`add_paragraph(style=...)` raising `KeyError` against
   a blank cover's real style sheet). Both are included: Task 1 has
   fast synthetic unit tests for the pure mapping logic
   (`tests/unit/infrastructure/test_safe_style_name.py`), **and** one
   `@pytest.mark.skipif(shutil.which("pandoc") is None, ...)`-guarded
   integration regression test that runs real pandoc, feeds the real
   output through `PythonDocxAssemblyAdapter().assemble(...)` against a
   blank cover, and asserts no `KeyError` — the actual gap flagged by both
   Slice 11a's per-task reviewer and its whole-slice reviewer.

## Task breakdown

### Task 1 — `safe_style_name` (fixes the live pandoc-style crash gap)

**Files to create/modify:**
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  delete `_safe_style_name_stub` (lines 38–41), add real `safe_style_name`
  in its place, repoint both call sites inside `_build_main_document`
  (currently lines 175 and 178) from `_safe_style_name_stub(...)` to
  `safe_style_name(...)`. Remove the `_safe_style_name_stub` bullet from
  the stub-seam comment block (lines 28–35) — do not delete the whole
  block yet (Tasks 2–4 still reference it; the block itself is only fully
  removed in Task 5, once no stub remains).
- Create `tests/unit/infrastructure/test_safe_style_name.py`.
- Modify `tests/integration/test_python_docx_assembly_adapter.py`: add the
  regression test described below.

**Verbatim legacy reference:** `safe_style_name` (2842–2859), verbatim, no
reshaping — signature and body match legacy exactly.

**Planned implementation:**

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py
# (replaces the _safe_style_name_stub block; call sites at what are
# currently lines 175/178 in _build_main_document change from
# `_safe_style_name_stub(...)` to `safe_style_name(...)`.)


def safe_style_name(document: Any, preferred_style: str | None) -> str | None:
    available = {style.name for style in document.styles}
    if preferred_style in available:
        return preferred_style

    pandoc_style_map = {
        "First Paragraph": "No Spacing",
        "Body Text": "No Spacing",
        "Compact": "No Spacing",
    }
    mapped = pandoc_style_map.get(preferred_style or "")
    if mapped in available:
        return mapped
    if "Normal" in available:
        return "Normal"
    if "No Spacing" in available:
        return "No Spacing"
    return None
```

**Planned test code:**

```python
# tests/unit/infrastructure/test_safe_style_name.py
from __future__ import annotations

from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import safe_style_name


def test_safe_style_name_returns_preferred_when_already_available():
    document = Document()
    assert safe_style_name(document, "Heading 1") == "Heading 1"


def test_safe_style_name_maps_first_paragraph_to_no_spacing():
    document = Document()
    assert "First Paragraph" not in {s.name for s in document.styles}
    assert safe_style_name(document, "First Paragraph") == "No Spacing"


def test_safe_style_name_maps_compact_to_no_spacing():
    document = Document()
    assert safe_style_name(document, "Compact") == "No Spacing"


def test_safe_style_name_falls_back_to_normal_when_no_mapping_matches():
    document = Document()
    assert safe_style_name(document, "Some Unknown Style") == "Normal"


def test_safe_style_name_returns_none_when_neither_fallback_exists():
    class _FakeStyle:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeDocument:
        styles = [_FakeStyle("Custom Only")]

    assert safe_style_name(_FakeDocument(), "First Paragraph") is None


def test_safe_style_name_returns_none_for_none_preferred_style_without_fallback():
    class _FakeStyle:
        def __init__(self, name: str) -> None:
            self.name = name

    class _FakeDocument:
        styles = [_FakeStyle("Custom Only")]

    assert safe_style_name(_FakeDocument(), None) is None
```

```python
# tests/integration/test_python_docx_assembly_adapter.py (added test)
import shutil

import pytest


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_assemble_does_not_crash_on_real_pandoc_first_paragraph_style(tmp_path):
    # Regression test for the gap flagged during Slice 11a review: real
    # pandoc output stamps the paragraph right after a heading with style
    # "First Paragraph", which a blank cover Document() does not define.
    # Before this slice's safe_style_name, this raised KeyError via
    # document.add_paragraph(style="First Paragraph").
    markdown = tmp_path / "section.md"
    markdown.write_text("# Titulo\n\nCuerpo del texto de prueba.\n", encoding="utf-8")
    body_docx = tmp_path / "body.docx"
    PythonDocxAssemblyAdapter().render_pandoc(shutil.which("pandoc"), [markdown], body_docx)

    output = tmp_path / "out.docx"
    # Should not raise KeyError.
    PythonDocxAssemblyAdapter().assemble(
        {}, body_docx, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[]
    )
    result = Document(str(output))
    target = next(p for p in result.paragraphs if p.text.strip() == "Cuerpo del texto de prueba.")
    assert target.style.name == "No Spacing"
```

**Expected test count:** ~6 unit tests + 1 integration regression test = 7.
Self-reviewable for the unit tests; the regression test should get an
explicit reviewer sign-off since it is the test that closes out a gap two
separate reviewers flagged in Slice 11a.

---

### Task 2 — `set_bullet_numbering`

**Files to create/modify:**
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  delete `_set_bullet_numbering_stub` (lines 44–46), add real
  `set_bullet_numbering`, repoint the one call site inside
  `apply_normative_paragraph_format` (currently line 101) from
  `_set_bullet_numbering_stub(paragraph)` to `set_bullet_numbering(paragraph)`.
  Remove the `_set_bullet_numbering_stub` bullet from the stub-seam
  comment block.
- Create `tests/unit/infrastructure/test_set_bullet_numbering.py`.

**Verbatim legacy reference:** `set_bullet_numbering` (2568–2586), verbatim.

**Planned implementation:**

```python
def set_bullet_numbering(paragraph: Any, num_id: int = 42) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is None:
        num_pr = OxmlElement("w:numPr")
        p_pr.append(num_pr)
    ilvl = num_pr.find(qn("w:ilvl"))
    if ilvl is None:
        ilvl = OxmlElement("w:ilvl")
        num_pr.append(ilvl)
    ilvl.set(qn("w:val"), "0")
    num_id_el = num_pr.find(qn("w:numId"))
    if num_id_el is None:
        num_id_el = OxmlElement("w:numId")
        num_pr.append(num_id_el)
    num_id_el.set(qn("w:val"), str(num_id))
```

**Planned test code:**

```python
# tests/unit/infrastructure/test_set_bullet_numbering.py
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn

from docs.infrastructure.docx.python_docx_assembly_adapter import set_bullet_numbering


def test_set_bullet_numbering_adds_num_pr_with_default_num_id():
    document = Document()
    paragraph = document.add_paragraph("Item")
    set_bullet_numbering(paragraph)
    p_pr = paragraph._p.pPr
    num_pr = p_pr.find(qn("w:numPr"))
    assert num_pr is not None
    assert num_pr.find(qn("w:ilvl")).get(qn("w:val")) == "0"
    assert num_pr.find(qn("w:numId")).get(qn("w:val")) == "42"


def test_set_bullet_numbering_honors_custom_num_id():
    document = Document()
    paragraph = document.add_paragraph("Item")
    set_bullet_numbering(paragraph, num_id=7)
    num_pr = paragraph._p.pPr.find(qn("w:numPr"))
    assert num_pr.find(qn("w:numId")).get(qn("w:val")) == "7"


def test_set_bullet_numbering_is_idempotent_not_duplicating_elements():
    document = Document()
    paragraph = document.add_paragraph("Item")
    set_bullet_numbering(paragraph)
    set_bullet_numbering(paragraph)
    p_pr = paragraph._p.pPr
    assert len(p_pr.findall(qn("w:numPr"))) == 1
    num_pr = p_pr.find(qn("w:numPr"))
    assert len(num_pr.findall(qn("w:numId"))) == 1


def test_set_bullet_numbering_round_trips_through_save_and_reopen(tmp_path):
    document = Document()
    paragraph = document.add_paragraph("Item")
    set_bullet_numbering(paragraph)
    path = tmp_path / "fixture.docx"
    document.save(path)

    reopened = Document(str(path))
    target = next(p for p in reopened.paragraphs if p.text == "Item")
    num_pr = target._p.pPr.find(qn("w:numPr"))
    assert num_pr.find(qn("w:numId")).get(qn("w:val")) == "42"
```

**Expected test count:** ~4 unit tests. Self-reviewable — small, no zip I/O,
no external dependency on other tasks.

---

### Task 3 — `ensure_bullet_numbering_part` (first zip-rewrite in this migration)

**Files to create/modify:**
- Modify `pyproject.toml`: add `defusedxml` to `dependencies` (per Design
  Decision 5.1 — user decision 2026-06-30 to harden XML parsing now rather
  than defer).
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  add module-level imports `import re`, `import zipfile`, `import
  xml.etree.ElementTree as ET`, `from defusedxml.ElementTree import parse
  as safe_parse` (alongside the existing `shutil`, `subprocess`,
  `tempfile` imports); delete `_ensure_bullet_numbering_part_stub` (lines
  69–71), add real `ensure_bullet_numbering_part` (using `safe_parse` in
  place of `ET.parse` for the three existing-file reads — see Planned
  implementation below), repoint both call sites inside `assemble`
  (currently lines 233 and 239) from
  `_ensure_bullet_numbering_part_stub(...)` to
  `ensure_bullet_numbering_part(...)`. Remove the
  `_ensure_bullet_numbering_part_stub` bullet from the stub-seam comment
  block.
- Create `tests/integration/test_ensure_bullet_numbering_part.py`.

**Verbatim legacy reference:** `ensure_bullet_numbering_part` (2589–2659) —
identical except the three `ET.parse(...)` calls become `safe_parse(...)`
per Design Decision 5.1 (user decision to add `defusedxml`).

**Planned implementation:**

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py
# (replaces the _ensure_bullet_numbering_part_stub block; only the three
# ET.parse(...) calls differ from the verbatim legacy body — they become
# safe_parse(...). Everything else — ET.Element/ET.SubElement/ET.write,
# the zipfile extract/rezip shape — is unchanged from legacy.)


def ensure_bullet_numbering_part(docx_path: Path, num_id: int = 42) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel_namespace = "http://schemas.openxmlformats.org/package/2006/relationships"
    content_namespace = "http://schemas.openxmlformats.org/package/2006/content-types"
    ET.register_namespace("w", namespace)
    ET.register_namespace("rel", rel_namespace)
    ET.register_namespace("ct", content_namespace)
    with tempfile.TemporaryDirectory(prefix="docs_docx_numbering_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        document_xml = (tmp_path / "word" / "document.xml").read_text(encoding="utf-8")
        if f'w:numId w:val="{num_id}"' not in document_xml:
            return

        numbering_path = tmp_path / "word" / "numbering.xml"
        if numbering_path.exists():
            numbering_tree = safe_parse(numbering_path)
            numbering_root = numbering_tree.getroot()
        else:
            numbering_path.parent.mkdir(parents=True, exist_ok=True)
            numbering_root = ET.Element(f"{{{namespace}}}numbering")
            numbering_tree = ET.ElementTree(numbering_root)

        if not numbering_root.find(f".//{{{namespace}}}num[@{{{namespace}}}numId='{num_id}']"):
            abstract = ET.SubElement(numbering_root, f"{{{namespace}}}abstractNum", {f"{{{namespace}}}abstractNumId": str(num_id)})
            ET.SubElement(abstract, f"{{{namespace}}}multiLevelType", {f"{{{namespace}}}val": "hybridMultilevel"})
            lvl = ET.SubElement(abstract, f"{{{namespace}}}lvl", {f"{{{namespace}}}ilvl": "0"})
            ET.SubElement(lvl, f"{{{namespace}}}start", {f"{{{namespace}}}val": "1"})
            ET.SubElement(lvl, f"{{{namespace}}}numFmt", {f"{{{namespace}}}val": "bullet"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlText", {f"{{{namespace}}}val": "•"})
            ET.SubElement(lvl, f"{{{namespace}}}lvlJc", {f"{{{namespace}}}val": "left"})
            p_pr = ET.SubElement(lvl, f"{{{namespace}}}pPr")
            tabs = ET.SubElement(p_pr, f"{{{namespace}}}tabs")
            ET.SubElement(tabs, f"{{{namespace}}}tab", {f"{{{namespace}}}val": "num", f"{{{namespace}}}pos": "720"})
            ET.SubElement(p_pr, f"{{{namespace}}}ind", {f"{{{namespace}}}left": "720", f"{{{namespace}}}hanging": "360"})
            r_pr = ET.SubElement(lvl, f"{{{namespace}}}rPr")
            ET.SubElement(r_pr, f"{{{namespace}}}rFonts", {f"{{{namespace}}}ascii": "Symbol", f"{{{namespace}}}hAnsi": "Symbol"})
            ET.SubElement(r_pr, f"{{{namespace}}}sz", {f"{{{namespace}}}val": "24"})
            num = ET.SubElement(numbering_root, f"{{{namespace}}}num", {f"{{{namespace}}}numId": str(num_id)})
            ET.SubElement(num, f"{{{namespace}}}abstractNumId", {f"{{{namespace}}}val": str(num_id)})
        numbering_tree.write(numbering_path, xml_declaration=True, encoding="UTF-8")

        rels_path = tmp_path / "word" / "_rels" / "document.xml.rels"
        rels_tree = safe_parse(rels_path)
        rels_root = rels_tree.getroot()
        numbering_rel_type = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"
        if not any(rel.get("Type") == numbering_rel_type for rel in rels_root):
            existing_ids = [int(match.group(1)) for rel in rels_root for match in [re.match(r"rId(\d+)$", rel.get("Id", ""))] if match]
            next_id = max(existing_ids or [0]) + 1
            ET.SubElement(rels_root, f"{{{rel_namespace}}}Relationship", {"Id": f"rId{next_id}", "Type": numbering_rel_type, "Target": "numbering.xml"})
            rels_tree.write(rels_path, xml_declaration=True, encoding="UTF-8")

        content_types_path = tmp_path / "[Content_Types].xml"
        content_tree = safe_parse(content_types_path)
        content_root = content_tree.getroot()
        numbering_content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"
        if not any(override.get("PartName") == "/word/numbering.xml" for override in content_root):
            ET.SubElement(
                content_root,
                f"{{{content_namespace}}}Override",
                {"PartName": "/word/numbering.xml", "ContentType": numbering_content_type},
            )
            content_tree.write(content_types_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())
```

**Planned test code:**

```python
# tests/integration/test_ensure_bullet_numbering_part.py
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import (
    ensure_bullet_numbering_part,
    set_bullet_numbering,
)

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NUMBERING_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering"


def _docx_with_bulleted_paragraph(tmp_path: Path, num_id: int = 42) -> Path:
    document = Document()
    paragraph = document.add_paragraph("Item con vinieta")
    set_bullet_numbering(paragraph, num_id=num_id)
    path = tmp_path / "fixture.docx"
    document.save(path)
    return path


def test_ensure_bullet_numbering_part_adds_numbering_xml_with_expected_num_id(tmp_path):
    path = _docx_with_bulleted_paragraph(tmp_path)
    ensure_bullet_numbering_part(path)

    with zipfile.ZipFile(path) as archive:
        assert "word/numbering.xml" in archive.namelist()
        numbering_xml = archive.read("word/numbering.xml").decode("utf-8")
    root = ET.fromstring(numbering_xml)
    num = root.find(f".//{{{_W_NS}}}num[@{{{_W_NS}}}numId='42']")
    assert num is not None


def test_ensure_bullet_numbering_part_adds_relationship_and_content_type(tmp_path):
    path = _docx_with_bulleted_paragraph(tmp_path)
    ensure_bullet_numbering_part(path)

    with zipfile.ZipFile(path) as archive:
        rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        content_types_xml = archive.read("[Content_Types].xml").decode("utf-8")
    assert _NUMBERING_REL_TYPE in rels_xml
    assert "/word/numbering.xml" in content_types_xml


def test_ensure_bullet_numbering_part_is_a_noop_when_no_bulleted_paragraph_exists(tmp_path):
    document = Document()
    document.add_paragraph("Sin vinietas")
    path = tmp_path / "plain.docx"
    document.save(path)

    ensure_bullet_numbering_part(path)

    with zipfile.ZipFile(path) as archive:
        assert "word/numbering.xml" not in archive.namelist()


def test_ensure_bullet_numbering_part_is_idempotent_across_repeated_calls(tmp_path):
    path = _docx_with_bulleted_paragraph(tmp_path)
    ensure_bullet_numbering_part(path)
    ensure_bullet_numbering_part(path)

    with zipfile.ZipFile(path) as archive:
        numbering_xml = archive.read("word/numbering.xml").decode("utf-8")
        rels_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
        content_types_xml = archive.read("[Content_Types].xml").decode("utf-8")
    root = ET.fromstring(numbering_xml)
    assert len(root.findall(f".//{{{_W_NS}}}num[@{{{_W_NS}}}numId='42']")) == 1
    assert rels_xml.count(_NUMBERING_REL_TYPE) == 1
    assert content_types_xml.count("/word/numbering.xml") == 1


def test_ensure_bullet_numbering_part_result_still_opens_via_python_docx(tmp_path):
    path = _docx_with_bulleted_paragraph(tmp_path)
    ensure_bullet_numbering_part(path)

    # Round-trip check: the rewritten zip must still be a valid .docx.
    reopened = Document(str(path))
    assert any(p.text == "Item con vinieta" for p in reopened.paragraphs)


def test_ensure_bullet_numbering_part_rejects_malicious_entity_expansion_in_existing_numbering_xml(tmp_path):
    # Hardening regression test for Design Decision 5.1 (defusedxml):
    # a pre-existing numbering.xml carrying a billion-laughs-style DTD
    # entity must be rejected by safe_parse, not silently expanded.
    path = _docx_with_bulleted_paragraph(tmp_path)
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(
            "word/numbering.xml",
            '<?xml version="1.0"?>'
            '<!DOCTYPE numbering [<!ENTITY lol "lol">]>'
            f'<w:numbering xmlns:w="{_W_NS}">&lol;</w:numbering>',
        )
    import pytest
    from defusedxml.common import DefusedXmlException

    with pytest.raises(DefusedXmlException):
        ensure_bullet_numbering_part(path)
```

**Expected test count:** ~6 integration tests. **Highest-risk task in this
slice** — needs implementer + fresh-context reviewer. The reviewer should
specifically verify: (a) the temp-dir extract/rezip round-trip does not
corrupt any existing archive member (spot-check via
`test_ensure_bullet_numbering_part_result_still_opens_via_python_docx`),
(b) the no-op early-return path (no `w:numId` present) is actually
exercised and does not accidentally create `numbering.xml` anyway, (c) the
idempotency test genuinely calls the function twice against the same file
on disk, not two independent fixtures, (d) the new hardening test actually
exercises `safe_parse` (not stdlib `ET.parse`) and genuinely fails before
Design Decision 5.1's change is applied — confirm the implementer shows a
RED run against plain `ET.parse` before swapping to `safe_parse`.

---

### Task 4 — Section/footer/pagination primitives

**Files to create/modify:**
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  add `apply_non_cover_section_layout`, `clear_story_part`,
  `add_page_number_footer` as new module functions (no stub existed for
  these three — Slice 11a's adapter never called them directly); delete
  `_set_section_page_number_start_stub` (lines 64–66), add real
  `set_section_page_number_start`, repoint both call sites inside
  `_build_main_document` (currently lines 146 and 185) from
  `_set_section_page_number_start_stub(...)` to
  `set_section_page_number_start(...)`. Remove the
  `_set_section_page_number_start_stub` bullet from the stub-seam comment
  block.
- Create `tests/unit/infrastructure/test_section_layout_primitives.py`.

**Verbatim legacy reference:** `apply_non_cover_section_layout`
(2689–2706), `add_page_number_footer` (2708–2736),
`set_section_page_number_start` (2739–2750), `clear_story_part`
(2758–2762) — all verbatim, no reshaping.

**Planned implementation:** (verbatim, as given in the Legacy code blocks
section above.)

**Planned test code:**

```python
# tests/unit/infrastructure/test_section_layout_primitives.py
from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches

from docs.infrastructure.docx.python_docx_assembly_adapter import (
    add_page_number_footer,
    apply_non_cover_section_layout,
    clear_story_part,
    set_section_page_number_start,
)


# --- apply_non_cover_section_layout -----------------------------------------


def test_apply_non_cover_section_layout_sets_letter_page_size():
    document = Document()
    section = document.sections[0]
    config = {"format": {"page_size": "letter"}}
    apply_non_cover_section_layout(section, config)
    assert section.page_width == Inches(8.5)
    assert section.page_height == Inches(11)


def test_apply_non_cover_section_layout_sets_configured_margins():
    document = Document()
    section = document.sections[0]
    config = {
        "format": {
            "page_margins_cm": {"non_cover": {"top": 2.5, "right": 3.0, "bottom": 2.5, "left": 3.0}},
        }
    }
    apply_non_cover_section_layout(section, config)
    assert section.top_margin == Cm(2.5)
    assert section.right_margin == Cm(3.0)
    assert section.bottom_margin == Cm(2.5)
    assert section.left_margin == Cm(3.0)


def test_apply_non_cover_section_layout_ignores_missing_margin_keys():
    document = Document()
    section = document.sections[0]
    original_left = section.left_margin
    apply_non_cover_section_layout(section, {"format": {"page_margins_cm": {"non_cover": {"top": 2.5}}}})
    assert section.left_margin == original_left


# --- clear_story_part --------------------------------------------------------


def test_clear_story_part_removes_existing_paragraphs_and_adds_one_empty():
    document = Document()
    section = document.sections[0]
    section.footer.is_linked_to_previous = False
    section.footer.paragraphs[0].text = "old content"
    section.footer.add_paragraph("more old content")
    clear_story_part(section.footer)
    assert len(section.footer.paragraphs) == 1
    assert section.footer.paragraphs[0].text == ""


# --- add_page_number_footer ---------------------------------------------------


def test_add_page_number_footer_sets_right_alignment_and_page_field(tmp_path):
    document = Document()
    section = document.sections[0]
    section.footer.is_linked_to_previous = False
    add_page_number_footer(section.footer)
    paragraph = section.footer.paragraphs[-1]
    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    xml = paragraph._p.xml
    assert "PAGE" in xml
    assert 'w:fldCharType="begin"' in xml
    assert 'w:fldCharType="separate"' in xml
    assert 'w:fldCharType="end"' in xml


# --- set_section_page_number_start --------------------------------------------


def test_set_section_page_number_start_sets_start_and_format():
    document = Document()
    section = document.sections[0]
    set_section_page_number_start(section, 5, "lowerRoman")
    pg_num_type = section._sectPr.find(qn("w:pgNumType"))
    assert pg_num_type.get(qn("w:start")) == "5"
    assert pg_num_type.get(qn("w:fmt")) == "lowerRoman"


def test_set_section_page_number_start_without_format_leaves_fmt_unset():
    document = Document()
    section = document.sections[0]
    set_section_page_number_start(section, 1)
    pg_num_type = section._sectPr.find(qn("w:pgNumType"))
    assert pg_num_type.get(qn("w:start")) == "1"
    assert pg_num_type.get(qn("w:fmt")) is None


def test_set_section_page_number_start_reuses_existing_pg_num_type_element():
    document = Document()
    section = document.sections[0]
    set_section_page_number_start(section, 1, "decimal")
    set_section_page_number_start(section, 3, "lowerRoman")
    assert len(section._sectPr.findall(qn("w:pgNumType"))) == 1
    pg_num_type = section._sectPr.find(qn("w:pgNumType"))
    assert pg_num_type.get(qn("w:start")) == "3"
    assert pg_num_type.get(qn("w:fmt")) == "lowerRoman"
```

**Expected test count:** ~9 unit tests. Self-reviewable individually, but
flag for the reviewer that these are leaf primitives only — Task 5 is
where their *composition* (the three `configure_*_section` functions) gets
integration-level verification.

---

### Task 5 — `configure_unnumbered_section` / `configure_numbered_body_section` / `configure_roman_preliminary_section` (closes the stub seam)

**Files to create/modify:**
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  delete `_configure_roman_preliminary_section_stub` (lines 49–51),
  `_configure_unnumbered_section_stub` (lines 54–56), and
  `_configure_numbered_body_section_stub` (lines 59–61); add the three
  real `configure_*_section` functions; repoint the three call sites
  inside `_build_main_document` (currently lines 144, 150, and 184) to the
  real functions. **This is the task that removes the last three stub
  entries — delete the entire "Slice 11b stub seam" comment block (current
  lines 28–35) in this task**, since after this task no `_stub`-suffixed
  function remains anywhere in the file (confirm via `grep _stub` on the
  finished file returning zero matches).
- Modify `tests/integration/test_python_docx_assembly_adapter.py`: add the
  Word-correct assertions below (these were explicitly impossible under
  Slice 11a's stubs — see Slice 11a plan, Task 3, "This means Slice 11a's
  own integration tests cannot assert Word-correct page numbering...").

**Verbatim legacy reference:** `configure_unnumbered_section` /
`configure_numbered_body_section` / `configure_roman_preliminary_section`
(2661–2687), verbatim — each calls Task 4's already-ported
`apply_non_cover_section_layout`, `clear_story_part`,
`add_page_number_footer`, `set_section_page_number_start`.

**Planned implementation:** (verbatim, as given in the Legacy code blocks
section above.)

**Planned test code:**

```python
# tests/integration/test_python_docx_assembly_adapter.py (added tests)
from docx.oxml.ns import qn


def _config_with_roman_prelim_and_body_restart() -> dict:
    return {
        "structure": [
            {"type": "cover_from_template"},
            {
                "type": "sections",
                "preliminary_pagination": {"start": 2, "format": "lowerRoman"},
                "body_restart_section": "cap2",
                "body_pagination": {"format": "decimal", "start": 1},
            },
        ],
        "sections": [{"id": "cap2", "title": "CAPITULO DOS"}],
    }


def test_assemble_configures_lower_roman_preliminary_section_pagination(tmp_path):
    document = Document()
    document.add_heading("CAPITULO DOS", level=1)
    document.add_paragraph("Texto de cuerpo.")
    body = tmp_path / "body.docx"
    document.save(body)

    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble(
        _config_with_roman_prelim_and_body_restart(), body, output,
        cover_asset_path=None, embed_front_paths=[], embed_back_paths=[],
    )
    result = Document(str(output))
    prelim_section = result.sections[1]
    pg_num_type = prelim_section._sectPr.find(qn("w:pgNumType"))
    assert pg_num_type.get(qn("w:start")) == "2"
    assert pg_num_type.get(qn("w:fmt")) == "lowerRoman"


def test_assemble_configures_decimal_body_section_pagination_restart(tmp_path):
    document = Document()
    document.add_heading("CAPITULO DOS", level=1)
    document.add_paragraph("Texto de cuerpo.")
    body = tmp_path / "body.docx"
    document.save(body)

    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble(
        _config_with_roman_prelim_and_body_restart(), body, output,
        cover_asset_path=None, embed_front_paths=[], embed_back_paths=[],
    )
    result = Document(str(output))
    body_section = result.sections[2]
    pg_num_type = body_section._sectPr.find(qn("w:pgNumType"))
    assert pg_num_type.get(qn("w:start")) == "1"
    assert pg_num_type.get(qn("w:fmt")) == "decimal"
    footer_xml = body_section.footer.paragraphs[-1]._p.xml
    assert "PAGE" in footer_xml


def test_assemble_unnumbered_section_has_no_page_field_in_footer(tmp_path):
    body = _save_body_docx(tmp_path)
    output = tmp_path / "out.docx"
    config = {
        "structure": [
            {"type": "cover_from_template"},
            {"type": "sections", "preliminary_pagination": {}},
        ]
    }
    PythonDocxAssemblyAdapter().assemble(
        config, body, output, cover_asset_path=None, embed_front_paths=[], embed_back_paths=[]
    )
    result = Document(str(output))
    prelim_section = result.sections[1]
    assert "PAGE" not in prelim_section.footer.paragraphs[-1]._p.xml


def test_assemble_clears_header_and_footer_on_configured_sections(tmp_path):
    body = _save_body_docx(tmp_path)
    output = tmp_path / "out.docx"
    PythonDocxAssemblyAdapter().assemble(
        _config_with_roman_prelim_and_body_restart(), body, output,
        cover_asset_path=None, embed_front_paths=[], embed_back_paths=[],
    )
    result = Document(str(output))
    prelim_section = result.sections[1]
    assert prelim_section.header.is_linked_to_previous is False
    assert prelim_section.footer.is_linked_to_previous is False
```

**Expected test count:** ~4 new integration tests (added to the existing
Slice 11a assembly-adapter suite). Needs implementer + fresh-context
reviewer — verify (a) the three call sites are repointed correctly and not
swapped (roman-preliminary vs. numbered-body configuration is easy to
transpose), (b) the entire stub-seam comment block is actually deleted and
a `grep _stub` on the finished file is clean, (c) Slice 11a's own
previously-stubbed assertions (page numbers, section pagination) now pass
for real rather than trivially (no stub silently still short-circuiting
somewhere).

---

### Task 6 — `insert_toc_field` + `set_update_fields_on_open` (new port method, service wiring)

**Files to create/modify:**
- Modify `src/docs/domain/ports/docx_assembly_port.py`: add
  `insert_toc_field(self, docx_path: Path, placeholder: str = "[[TOC]]",
  levels: str = "1-3") -> bool: ...` to the `Protocol`.
- Modify `src/docs/infrastructure/docx/python_docx_assembly_adapter.py`:
  add module-level functions `insert_toc_field` and
  `set_update_fields_on_open` (both net-new — no stub existed for either,
  since Slice 11a's `DocxAssemblyService.build()` never called them at
  all); add `PythonDocxAssemblyAdapter.insert_toc_field` as a thin method
  delegating to the module-level function (mirroring how `assemble` and
  `render_pandoc` are already both module-adjacent logic and adapter
  methods in this file).
- Modify `src/docs/application/docx_assembly.py`: in `build()`, replace
  the comment `# insert_toc_field(output) — deferred to Slice 11b; ...`
  with a real `self.port.insert_toc_field(output)` call, right after
  `self.assemble(doc_id, config, body_docx, output)`.
- Create `tests/integration/test_insert_toc_field.py`.
- Modify `tests/integration/test_docx_assembly_service.py`: add the
  service-level end-to-end test below.

**Verbatim legacy reference:** `insert_toc_field` (2765–2809),
`set_update_fields_on_open` (2812–2839) — both verbatim.

**Planned implementation:**

```python
# src/docs/domain/ports/docx_assembly_port.py (added method)
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

    def insert_toc_field(self, docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool: ...
```

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py (added)
def insert_toc_field(docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document(str(docx_path))
    target = None
    for paragraph in document.paragraphs:
        if (paragraph.text or "").strip() == placeholder:
            target = paragraph
            break
    if target is None:
        return False

    for run in list(target.runs)[::-1]:
        target._p.remove(run._r)

    run = target.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f' TOC \\o "{levels}" \\h \\z \\u '
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "(El indice se actualizara al abrir el documento en Word)"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(text)
    run._r.append(fld_end)
    document.save(str(docx_path))
    set_update_fields_on_open(docx_path)
    return True


def set_update_fields_on_open(docx_path: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    ET.register_namespace("w", namespace)
    with tempfile.TemporaryDirectory(prefix="docs_docx_settings_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as archive:
            archive.extractall(tmp_path)

        settings_path = tmp_path / "word" / "settings.xml"
        if settings_path.exists():
            tree = safe_parse(settings_path)  # Design Decision 5.1 (defusedxml)
            root = tree.getroot()
        else:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            root = ET.Element(f"{{{namespace}}}settings")
            tree = ET.ElementTree(root)

        update_fields = root.find(f"{{{namespace}}}updateFields")
        if update_fields is None:
            update_fields = ET.Element(f"{{{namespace}}}updateFields")
            root.insert(0, update_fields)
        update_fields.set(f"{{{namespace}}}val", "true")
        tree.write(settings_path, xml_declaration=True, encoding="UTF-8")

        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in tmp_path.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(tmp_path).as_posix())
```

```python
# src/docs/infrastructure/docx/python_docx_assembly_adapter.py
# (PythonDocxAssemblyAdapter method addition)
class PythonDocxAssemblyAdapter:
    ...

    def insert_toc_field(self, docx_path: Path, placeholder: str = "[[TOC]]", levels: str = "1-3") -> bool:
        return insert_toc_field(docx_path, placeholder=placeholder, levels=levels)
```

```python
# src/docs/application/docx_assembly.py (build(), updated tail)
        self.port.render_pandoc(pandoc, stripped_sections, body_docx)
        self.assemble(doc_id, config, body_docx, output)
        self.port.insert_toc_field(output)
        return output
```

**Planned test code:**

```python
# tests/integration/test_insert_toc_field.py
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document

from docs.infrastructure.docx.python_docx_assembly_adapter import insert_toc_field

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_with_toc_placeholder(tmp_path: Path) -> Path:
    document = Document()
    document.add_paragraph("[[TOC]]")
    path = tmp_path / "fixture.docx"
    document.save(path)
    return path


def test_insert_toc_field_replaces_placeholder_with_toc_field(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    result = insert_toc_field(path)
    assert result is True

    reopened = Document(str(path))
    target = next(p for p in reopened.paragraphs if "TOC" in p._p.xml or "actualizara" in p.text)
    xml = target._p.xml
    assert 'w:fldCharType="begin"' in xml
    assert 'TOC \\o "1-3" \\h \\z \\u' in xml
    assert 'w:fldCharType="separate"' in xml
    assert 'w:fldCharType="end"' in xml


def test_insert_toc_field_sets_update_fields_on_open(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    insert_toc_field(path)

    with zipfile.ZipFile(path) as archive:
        settings_xml = archive.read("word/settings.xml").decode("utf-8")
    assert 'w:val="true"' in settings_xml
    assert "updateFields" in settings_xml


def test_insert_toc_field_returns_false_and_leaves_file_untouched_when_placeholder_missing(tmp_path):
    document = Document()
    document.add_paragraph("No placeholder here.")
    path = tmp_path / "no_toc.docx"
    document.save(path)
    before = path.read_bytes()

    result = insert_toc_field(path)
    assert result is False
    assert path.read_bytes() == before


def test_insert_toc_field_honors_custom_levels_argument(tmp_path):
    path = _docx_with_toc_placeholder(tmp_path)
    insert_toc_field(path, levels="1-2")
    reopened = Document(str(path))
    xml = "".join(p._p.xml for p in reopened.paragraphs)
    assert 'TOC \\o "1-2"' in xml
```

```python
# tests/integration/test_docx_assembly_service.py (added test)
import shutil

import pytest


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not installed")
def test_build_produces_working_toc_field_not_literal_placeholder(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(repository=..., workspace=workspace)
    service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)

    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / "001-resumen.md").write_text("# Resumen\n\nContenido.\n", encoding="utf-8")
    config = {
        "sections": [{"id": "resumen", "order": 1}],
        "paths": {"sections_dir": str(sections_dir), "output_draft_dir": str(tmp_path / "draft")},
        "structure": [{"type": "cover_from_template"}, {"type": "toc"}, {"type": "sections"}],
    }

    output = service.build("tesina-demo", config)
    result = Document(str(output))
    assert not any(p.text.strip() == "[[TOC]]" for p in result.paragraphs)
    assert any('w:fldCharType="begin"' in p._p.xml for p in result.paragraphs)
```

**Expected test count:** ~4 adapter-level tests + 1 service-level
end-to-end test = 5. Needs implementer + fresh-context reviewer — verify
(a) the `Protocol` addition doesn't break the fake/test double used
elsewhere for `DocxAssemblyPort` (grep for any existing hand-written fake
implementing the Protocol before assuming none exists), (b) the
service-level test genuinely exercises the real adapter end-to-end (not a
fake), consistent with this migration's "no mocking python-docx/pandoc"
convention, (c) the deferred-TOC comment in `DocxAssemblyService.build()`
is fully removed, not just commented differently.

---

## Global constraints

- **Config-as-dict convention preserved.** No typed `Config` model
  introduced; `config: dict[str, Any]` throughout, consistent with Slices
  1–11a.
- **`python-docx`/`zipfile`/`xml.etree.ElementTree` stay out of `domain/`.**
  All new code lives in `infrastructure/docx/python_docx_assembly_adapter.py`,
  except the one-line `DocxAssemblyPort` Protocol addition (domain layer,
  but a bare method signature with no implementation — consistent with
  every prior port addition in this migration).
- **Every stub function and every stub call site is accounted for.** By
  the end of Task 5, `grep _stub` on
  `src/docs/infrastructure/docx/python_docx_assembly_adapter.py` must
  return zero matches, and the "Slice 11b stub seam" comment block must be
  fully deleted.
- **`num_id=42` stays a hardcoded default**, not promoted to a config key
  (Design Decision 4) — this slice's scope is "port the real functions,"
  not "add new configurability legacy never had."
- **One new third-party dependency: `defusedxml`** (user decision,
  2026-06-30, Design Decision 5.1) — added in Task 3, used for every
  `ET.parse(...)` call in this slice that reads XML pulled out of a
  `.docx` zip (`numbering.xml`, `word/_rels/document.xml.rels`,
  `[Content_Types].xml` in Task 3; `settings.xml` in Task 6). `zipfile` and
  `xml.etree.ElementTree` (construction/writing only) remain standard
  library; `docxcompose` remains untouched (Slice 11a's Design Decision 5,
  unaffected by this slice).
- **No CLI, no `qa_docx`, no `run_doctor` glue in this slice.**
- **Strict TDD per task.** Each task above is independently testable and
  committable: failing test → minimal implementation → passing test →
  commit, then independent fresh-context review — Task 3 and Task 6 in
  particular warrant the review given their zip-rewrite and
  Protocol-surface-changing nature respectively.

## Risks and open judgment calls

1. **Task 3 and Task 6 are both "first of their kind" zip-rewrite code in
   this migration** — no prior slice's tests catch a zip-corruption
   regression pattern, since Slice 10's zip usage is read-only. Mitigated
   by this plan's explicit "reopen via `python-docx` after every rewrite"
   discipline (Design Decision 6), but a reviewer should specifically
   confirm every zip-rewrite test actually reopens the result rather than
   only inspecting raw XML strings.
2. **Task 5's three-way call-site repointing (roman-preliminary vs.
   unnumbered vs. numbered-body) is easy to transpose** — the three
   `configure_*_section` functions have near-identical bodies (same
   `apply_non_cover_section_layout`/`clear_story_part` calls, differing
   only in whether/how `add_page_number_footer` and
   `set_section_page_number_start` are invoked), which is exactly the kind
   of near-duplicate code where a copy-paste error silently swaps two
   call sites without any test failing if the test itself doesn't
   distinguish the two sections' actual pagination values (flagged
   explicitly in Task 5's planned tests — each asserts a *specific*
   `w:start`/`w:fmt` value per section, not just "some pagination exists").
3. **`insert_toc_field`'s `Protocol` addition may affect existing test
   doubles.** This plan did not find (nor did Slice 11a's plan mention) a
   hand-written fake `DocxAssemblyPort` implementation anywhere in the
   current test suite — all existing `DocxAssemblyService` tests use the
   real `PythonDocxAssemblyAdapter()` — but the Task 6 implementer should
   `grep` for `DocxAssemblyPort` usages before assuming the Protocol
   change is consequence-free.
4. **The `safe_style_name` regression test (Task 1) depends on this dev
   environment's real pandoc install**, consistent with every other
   pandoc-dependent test in this migration (Slice 11a Design Decision 6) —
   `skipif`-guarded, so it degrades gracefully but has zero coverage in a
   pandoc-less CI environment, same accepted gap Slice 11a already flagged.
5. **Whether `PythonDocxAssemblyAdapter.insert_toc_field` should be a thin
   delegate to a module-level function (as planned) or inline the logic
   directly onto the class**, mirroring the existing inconsistency in this
   file (`render_pandoc` is inline on the class; `add_fixed_text_page`/
   `apply_normative_paragraph_format` are module-level functions called
   from within class methods). This plan follows the "module-level
   function + thin class delegate" shape for `insert_toc_field` since it
   is also independently useful as a standalone importable function (the
   adapter-level tests in Task 6 call it directly, not through the
   class) — flagged as a minor style judgment call for the reviewer to
   confirm is worth the extra indirection versus inlining.
6. **RESOLVED (user decision, 2026-06-30): add `defusedxml` now, this
   slice, rather than deferring.** Original concern: `xml.etree.ElementTree`
   (stdlib) is XXE/billion-laughs-vulnerable by default, and this slice is
   the first to *parse* (not just read raw bytes from) XML pulled out of a
   `.docx` zip — `ET.parse(numbering_path)`/`ET.parse(rels_path)`/
   `ET.parse(content_types_path)` in `ensure_bullet_numbering_part` (Task
   3) and `ET.parse(settings_path)` in `set_update_fields_on_open` (Task
   6) all parse XML that originated inside a `.docx` file, and via Slice
   11a's `cover_from_asset`/`embed_docx` structure parts, a `.docx` file's
   contents are not guaranteed to be self-generated — they can be a
   user-supplied asset. Presented to the user as a genuine fork (accept
   as consistent with Slice 10's already-shipped precedent vs. harden now)
   — user chose to harden now. **Correction made during this decision**:
   the premise that "Slice 10 already established the
   stdlib-`ElementTree`-for-`.docx`-XML precedent for reads" was checked
   directly against `python_docx_audit_adapter.py` (lines 36-45) and found
   inaccurate — `read_xml`/`list_parts` only call
   `archive.read(...).decode("utf-8")`/`archive.namelist()`, never
   `ET.parse`/`ET.fromstring`. There is no unsafe XML *parsing* in Slice
   10 to retrofit; only this slice introduces real parsing of
   zip-extracted XML. See Design Decision 5.1 for the resulting
   implementation (`defusedxml.ElementTree.parse` aliased `safe_parse` for
   every existing-file read; stdlib `ET` retained for construction/writing,
   since `defusedxml` has no construction API of its own). Task 3 also
   gained a dedicated hardening regression test
   (`test_ensure_bullet_numbering_part_rejects_malicious_entity_expansion_in_existing_numbering_xml`)
   proving the swap actually changes behavior against a crafted payload,
   not just a documentation-only claim.
