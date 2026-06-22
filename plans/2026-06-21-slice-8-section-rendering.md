# Slice 8 — Section Rendering · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 1157–1445 (`build_section` through `resolve_section_path`)

## Overview / Scope

This slice ports the harness's section-drafting pipeline: given a section
definition and whatever context/evidence is available, render a Markdown
draft body (table-of-contents page, or a normative scaffold with PENDIENTE
placeholders), apply keyword bolding, build/refresh the project-wide
"Fact Ledger" (`00-fact-ledger.md`), and decide where a freshly generated
section should land on disk (overwrite in place vs. proposal file), mirroring
legacy `build_section`'s conflict-detection logic.

Ported in this slice (all from legacy lines 1157–1442):

- `dedupe_strings` (pure) — generic whitespace-normalizing string dedupe.
- `apply_keyword_bold` (pure) — protects existing `**bold**` spans, then
  bolds keyword terms (longest-first, case-insensitive, word-boundary-safe).
- `_extract_table_value` / `_extract_heading_block` (pure) — Markdown table
  cell / heading-block extraction helpers.
- `render_toc_section` (pure) — trivial TOC page renderer.
- `_summarize_context` (pure) — turns a `dict[str, str]` of already-loaded
  context text into bullet-point summary lines.
- `render_contract_scaffold` (pure, with context pre-supplied) — builds the
  PENDIENTE-laden scaffold body from a section contract + context summary.
- `render_section_draft` (pure, with context pre-supplied) — dispatches to
  TOC vs. scaffold rendering, then applies keyword bolding.
- `generated_metadata_changed` (pure) — frontmatter-diff helper.
- `dedupe_facts` — **already ported** in Slice 7 (`domain/collection.py`).
  Reused, not reimplemented.
- `load_manifest_facts` (impure: reads 3 JSON manifests off disk) — ported
  as `EvidenceService.load_manifest_facts`, composing `EvidenceRepository`.
- `render_fact_ledger` (impure: reads manifests via the above) — ported as
  `EvidenceService.render_fact_ledger`, taking already-resolved
  `ledger_seed`/context-confirmed-facts as input per the "pass values in"
  convention (see Design Decision 3).
- `build_section` (impure: directory creation, frontmatter read/write,
  proposal-file fallback) — ported as `ReviewService.build_section` (see
  Design Decision 1 for why it lands on `ReviewService`, not a new service).
- `resolve_section_path` (impure: existence check + section lookup) — ported
  as `ReviewService.resolve_section_path`.

Explicitly **not** ported in this slice (see "Out of scope" below):

- `review_section` (legacy line 1445) — **already ported**, see Design
  Decision 0. Not part of this slice's work.
- `section_by_id` / `section_path_for` (legacy lines 594–595, 598–603) — not
  re-ported as free functions; their behavior is already covered by
  `Template.sections` lookups (`Section.id`/`Section.order`) plus
  `SectionRepository.section_path`, which this codebase uses everywhere else
  instead of a config-dict section list. See Design Decision 2.
- `load_context` / `load_context_for` / `context_schema` / `read_topic` — not
  re-ported as config-dict functions; this codebase's equivalent shape is
  `ContextRepository`/`ContextService` (doc_id + `Topic` objects, from
  Slice 2). See Design Decision 3.
- `source_hash` / `prompt_hash` — still deferred (same reasoning as Slice 6:
  `context_dir`/`prompts_dir`-as-flat-glob and a `prompts_dir` config concept
  this codebase has never modeled). `build_section`'s metadata still computes
  them, so `ReviewService.build_section`'s metadata dict accepts them as
  injected values rather than computing them. See Design Decision 4.

## Legacy code blocks

### `build_section` (lines 1157–1207)

```python
def build_section(config: dict[str, Any], section_id: str) -> Path:
    section = section_by_id(config, section_id)
    sections_dir = Path(config["paths"]["sections_dir"])
    sections_dir.mkdir(parents=True, exist_ok=True)
    fact_ledger_path = Path(config["paths"]["fact_ledger"])
    fact_ledger_path.parent.mkdir(parents=True, exist_ok=True)

    context = load_context(config)
    if not fact_ledger_path.exists():
        fact_ledger_path.write_text(render_fact_ledger(config, context), encoding="utf-8")

    body = render_section_draft(config, section, load_context_for(config, section_id))
    metadata = {
        "managed_by": "tesina-harness",
        "authored_by": "harness-scaffold",
        "schema": 3,
        "section_id": section_id,
        "title": section["title"],
        "source_hash": source_hash(config),
        "source_manifest_hash": manifest_hash(config["paths"].get("source_manifest")),
        "code_evidence_manifest_hash": manifest_hash(config["paths"].get("code_evidence_manifest")),
        "rules_hash": rules_hash(config),
        "contract_hash": contract_hash(config, section_id),
        "prompt_hash": prompt_hash(config),
        "body_hash": sha256_text(body),
        "last_review_hash": "",
    }
    generated = with_frontmatter(body, metadata)
    section_path = section_path_for(config, section)

    if section_path.exists():
        current_text = section_path.read_text(encoding="utf-8")
        current_meta, current_body = split_frontmatter(current_text)
        if not current_meta and current_text == body:
            section_path.write_text(generated, encoding="utf-8")
            return section_path
        is_managed = current_meta.get("managed_by") == "tesina-harness"
        is_unchanged = current_meta.get("body_hash") == sha256_text(current_body)
        if is_managed and is_unchanged:
            if generated_metadata_changed(current_meta, metadata):
                section_path.write_text(generated, encoding="utf-8")
            return section_path

        proposals_dir = sections_dir / "_proposals"
        proposals_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = proposals_dir / f"{section['order']:03d}-{section_id}.candidate.md"
        proposal_path.write_text(generated, encoding="utf-8")
        return proposal_path

    section_path.write_text(generated, encoding="utf-8")
    return section_path
```

### `generated_metadata_changed` (lines 1210–1222)

```python
def generated_metadata_changed(current: dict[str, Any], new: dict[str, Any]) -> bool:
    keys = [
        "schema",
        "title",
        "source_hash",
        "source_manifest_hash",
        "code_evidence_manifest_hash",
        "rules_hash",
        "contract_hash",
        "prompt_hash",
        "body_hash",
    ]
    return any(current.get(key) != new.get(key) for key in keys)
```

### `render_fact_ledger` (lines 1225–1282)

```python
def render_fact_ledger(config: dict[str, Any], context: dict[str, str] | None = None) -> str:
    """Ledger genérico: hechos sembrados por la plantilla + datos de contexto llenados + facts de manifests."""
    grouped: dict[str, list[str]] = {
        "confirmado": [],
        "contradiccion": [],
        "pendiente": [],
        "prototipo": [],
        "fuera_de_alcance": [],
        "dato_sensible": [],
    }

    # 1. Hechos sembrados por la plantilla/documento (sin hardcode en el motor).
    for fact in config.get("ledger_seed", []):
        classification = fact.get("classification", "confirmado")
        claim = fact.get("claim", "")
        if claim:
            grouped.setdefault(classification, []).append(claim)

    # 2. Datos confirmados desde los temas de contexto ya llenados.
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

    # 3. Facts/issues de los manifests recolectados.
    for fact in load_manifest_facts(config):
        classification = fact.get("classification", "pendiente")
        claim = fact.get("claim") or fact.get("title", "")
        if claim:
            grouped.setdefault(classification, []).append(claim)

    headings = {
        "confirmado": "Datos confirmados",
        "contradiccion": "Contradicciones conocidas",
        "pendiente": "Pendientes obligatorios",
        "prototipo": "Prototipos o dependencias externas",
        "fuera_de_alcance": "Fuera de alcance del cuerpo",
        "dato_sensible": "Datos sensibles excluidos del cuerpo",
    }
    lines = ["# Fact Ledger", ""]
    for key, title in headings.items():
        values = dedupe_strings(grouped.get(key, []))
        if not values:
            continue
        lines.extend([f"## {title}", ""])
        lines.extend(f"- {value}" for value in values)
        lines.append("")
    return "\n".join(lines)
```

### `load_manifest_facts` (lines 1285–1297)

```python
def load_manifest_facts(config: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for key in ["source_manifest", "issues_manifest", "code_evidence_manifest"]:
        path = Path(config["paths"].get(key, ""))
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        facts.extend(item for item in data.get("facts", []) if isinstance(item, dict))
        facts.extend(item for item in data.get("issues", []) if isinstance(item, dict))
    return dedupe_facts(facts)
```

### `dedupe_strings` (lines 1300–1308)

```python
def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            out.append(normalized)
            seen.add(normalized)
    return out
```

### `render_section_draft` (lines 1311–1318)

```python
def render_section_draft(config: dict[str, Any], section: dict[str, Any], context: dict[str, str]) -> str:
    contract = config.get("section_contracts", {}).get(section["id"], {})
    if contract.get("toc"):
        body = render_toc_section(section)
    else:
        body = render_contract_scaffold(config, section, context)
    terms = config.get("format", {}).get("keyword_bold_terms", {}).get(section["id"], [])
    return apply_keyword_bold(body, terms)
```

### `render_toc_section` (lines 1321–1322)

```python
def render_toc_section(section: dict[str, Any]) -> str:
    return f"# {section['title']}\n\n[[TOC]]\n"
```

### `_summarize_context` (lines 1325–1339)

```python
def _summarize_context(context: dict[str, str]) -> list[str]:
    """Resume el contexto a demanda en viñetas `etiqueta: valor` (de tablas) y notas de prosa."""
    lines: list[str] = []
    for _name, text in sorted(context.items()):
        for match in re.finditer(r"\|\s*\*\*(.+?)\*\*\s*\|\s*(.*?)\s*\|", text):
            label = _clean_markdown_text(match.group(1))
            value = _clean_markdown_text(match.group(2))
            if value and label.lower() != "campo":
                lines.append(f"- {label}: {value}")
        prose = re.sub(r"^#\s+.*\n", "", text, count=1).strip()
        if "|" not in text and prose:
            heading = text.splitlines()[0].lstrip("# ").strip() if text.startswith("#") else _name
            snippet = prose[:200] + ("…" if len(prose) > 200 else "")
            lines.append(f"- {heading}: {snippet}")
    return lines
```

> Note: `_clean_markdown_text` (legacy lines 1425–1431) is identical to
> already-ported `docs.domain.markdown_text.clean_markdown_text` — reused,
> not reimplemented.

### `render_contract_scaffold` (lines 1342–1377)

```python
def render_contract_scaffold(config: dict[str, Any], section: dict[str, Any], context: dict[str, str] | None = None) -> str:
    contract = config.get("section_contracts", {}).get(section["id"], {})
    lines = [
        f"# {section['title']}",
        "",
        "_Borrador inicial generado por el arnés. Esta sección no debe considerarse lista hasta resolver todos los PENDIENTE con evidencia._",
        "",
    ]
    if context is None:
        context = load_context_for(config, section["id"])
    context_lines = _summarize_context(context)
    if context_lines:
        lines.extend(["## Contexto disponible", "", *context_lines, ""])
    required = contract.get("required_content", [])
    if required:
        lines.extend(["## Pendientes normativos", ""])
        for item in required:
            lines.append(f"- PENDIENTE: documentar {item} con evidencia del ledger, contexto o fuentes.")
        lines.append("")
    if contract.get("apa_required"):
        lines.extend(
            [
                "## Fuentes APA 7",
                "",
                "- PENDIENTE: agregar citas autor-fecha y referencias APA 7 realmente consultadas.",
                "",
            ]
        )
    if contract.get("references_list"):
        lines.extend(
            [
                "PENDIENTE: ordenar alfabéticamente todas las fuentes citadas en el cuerpo conforme a APA 7.",
                "",
            ]
        )
    return "\n".join(lines)
```

### `apply_keyword_bold` (lines 1380–1396)

```python
def apply_keyword_bold(markdown: str, terms: list[str]) -> str:
    if not terms:
        return markdown
    placeholders: dict[str, str] = {}

    def protect(match: re.Match[str]) -> str:
        key = f"@@TESINA_BOLD_{len(placeholders)}@@"
        placeholders[key] = match.group(0)
        return key

    protected = re.sub(r"\*\*.+?\*\*", protect, markdown)
    for term in sorted((term for term in terms if term), key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w@])({re.escape(term)})(?![\w@])", re.IGNORECASE)
        protected = pattern.sub(r"**\1**", protected)
    for key, value in placeholders.items():
        protected = protected.replace(key, value)
    return protected
```

### `_extract_table_value` (lines 1399–1404)

```python
def _extract_table_value(markdown: str, field: str) -> str:
    pattern = re.compile(rf"\|\s*\*\*{re.escape(field)}\*\*\s*\|\s*(.*?)\s*\|", re.IGNORECASE)
    match = pattern.search(markdown)
    if not match:
        return ""
    return _clean_markdown_text(match.group(1))
```

### `_extract_heading_block` (lines 1407–1422)

```python
def _extract_heading_block(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    capture = False
    block: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.fullmatch(rf"#+\s*\*\*{re.escape(heading)}\*\*", stripped, re.IGNORECASE) or re.fullmatch(
            rf"#+\s*{re.escape(heading)}", stripped, re.IGNORECASE
        ):
            capture = True
            continue
        if capture and stripped.startswith("#"):
            break
        if capture:
            block.append(line)
    return "\n".join(block).strip()
```

### `resolve_section_path` (lines 1434–1442)

```python
def resolve_section_path(config: dict[str, Any], section_or_path: str) -> Path:
    candidate = Path(section_or_path)
    if candidate.exists():
        return candidate
    try:
        section = section_by_id(config, section_or_path)
    except ValueError:
        raise FileNotFoundError(f"No existe la ruta ni sección: {section_or_path}") from None
    return Path(config["paths"]["sections_dir"]) / f"{section['order']:03d}-{section['id']}.md"
```

## Design decisions

1. **`review_section` (legacy line 1445) is OUT OF SCOPE — already ported,
   not part of this slice.** I read it in full (lines 1445–1499) and traced
   it against this codebase. It is byte-for-byte the same function already
   ported in Slice 3 Task 7 as `domain.rules.review_section_text` (orchestrator:
   excluded-section / first-person / subjective-term / secret-pattern /
   scope-delimiting / missing-title checks, composing
   `review_section_contract` + `review_apa7_text`, plus the
   `pendiente`-not-allowed and results-without-evidence checks). Its
   `is_policy_file`/`section_id` derivation already lives in
   `ReviewService.review_document` (Slice 5 Task 4), which calls
   `infer_section_id_from_path` (`domain/sections.py`, Slice 5 Task 1) exactly
   as legacy's `review_section` does. The doc-level orchestration role legacy
   gives `review_section` (single-file entry point) is filled by
   `ReviewService.review_document`'s per-section loop. There is no missing
   behavior here — porting it "again" under this slice's name would either
   duplicate `review_section_text` outright or require inventing a new
   single-file wrapper with no current caller. Decision: confirm it stays out
   of scope, document why, and do not create a redundant wrapper.

2. **`section_by_id` / `section_path_for` are NOT re-ported as free
   functions.** Both are config-dict-list lookups over a "flat list of
   section dicts" shape that legacy used everywhere. This codebase replaced
   that shape back in Slice 1 with `Template.sections: list[Section]`
   (Pydantic) plus `SectionRepository.section_path(doc_id, order, section_id)`
   (Slice 5), which every other service (`ReviewService`) already uses for
   section lookups and path resolution. Re-introducing a config-dict
   `section_by_id`/`section_path_for` pair would create two parallel,
   inconsistent ways to do the same lookup. Decision: `build_section`'s use
   of `section_by_id`/`section_path_for` is satisfied by looking up the
   `Section` in `template.sections` and calling
   `SectionRepository.section_path`, exactly like `ReviewService` already
   does — no new code needed for these two legacy helpers.

3. **`load_context` / `load_context_for` / `context_schema` / `read_topic`
   are NOT re-ported as config-dict functions.** `load_context` (flat
   `context_dir.glob("*.md")` → `dict[str, str]`) is *already* covered by
   `SourceRepository.read_context_texts` (Slice 7) — same shape, already
   used by `CollectionService.collect_sources`. But `load_context_for`
   (section-scoped subset via the legacy JSON context index) and
   `context_schema`/`read_topic` (topic-schema-driven field/prose reads) are
   built on a doc-id-less, flat-directory shape that this codebase replaced
   in Slice 2 with `ContextRepository`/`ContextService`
   (doc_id + `Topic` Pydantic objects, `context_repo.read_topic(doc_id, topic)`).
   Re-deriving `load_context_for`'s legacy JSON-index-driven subset logic
   would mean either (a) reviving the legacy flat-index file format this
   codebase no longer writes that way, or (b) redesigning around
   `ContextRepository`'s `regenerate_index`/`Topic.consumed_by` shape — a
   non-trivial design decision squarely out of bounds for a "pass values in"
   slice. Decision: `render_section_draft`/`render_contract_scaffold` accept
   an **already-resolved** `context: dict[str, str]` parameter (exactly as
   legacy's own functions do when called with a pre-loaded `context` arg —
   see `build_section` passing `load_context_for(...)` in, and
   `render_fact_ledger`'s `context` parameter). The caller (a future
   document-assembly slice, or the CLI) is responsible for resolving context
   via `ContextService`/`ContextRepository` before calling into this slice's
   pure rendering functions. This slice does NOT introduce a new
   "load context for section" capability; it consumes whatever `dict[str, str]`
   it's given, which is exactly what `_summarize_context` and
   `render_contract_scaffold`'s `context` parameter already do at the call
   site that matters (the one this slice ports). The `context_schema(config)`
   / `read_topic(config, topic)` loop inside `render_fact_ledger` (step 2,
   "Datos confirmados desde los temas de contexto ya llenados") is therefore
   ported as accepting a **pre-computed `list[str]` of confirmed-fact lines**
   (the caller runs `ContextService.status`-style logic and feeds in already-
   rendered `"{label}: {value}"` strings) rather than this function reaching
   into `ContextRepository` itself. This keeps `EvidenceService` (which is
   where `render_fact_ledger` naturally lands, see Decision 5) dependent on
   only `EvidenceRepository`, not also on `ContextRepository` — avoiding a
   two-port service for a slice that doesn't need it. This is the same kind
   of "pass values in" decision Slice 6/7 made for `repo_root: Path`.

4. **`source_hash` / `prompt_hash` remain deferred (same as Slice 6).**
   `build_section`'s metadata dict calls both. Slice 6 already established
   (and this plan reconfirms by re-reading lines 417–439) that `source_hash`
   needs `context_dir`+`manual_dir` globbing combined with `config["sections"]`
   (the legacy flat list, see Decision 2) and `prompt_hash` needs a
   `prompts_dir` config concept this codebase has never modeled anywhere.
   Porting either now would be speculative modeling, exactly as Slice 6's
   pre-execution review concluded. Decision: `ReviewService.build_section`'s
   metadata-building step accepts `source_hash: str` and `prompt_hash: str`
   as **injected parameters** rather than computing them — consistent with
   how `manifest_hash`/`rules_hash`/`contract_hash` are already
   `EvidenceService` methods the caller invokes and passes in. This is not a
   new pattern; `build_section`'s own metadata dict already calls
   `manifest_hash(...)`/`rules_hash(...)`/`contract_hash(...)` as separate
   function calls feeding a dict literal — the only two NOT yet portable are
   carved out as caller-supplied strings, with their (still TODO) values
   simply passed straight through to the frontmatter metadata, matching
   legacy's literal behavior when a caller doesn't yet have a real value.

4.5. **`SectionContract` must grow two fields: `toc: bool = False` and
   `references_list: bool = False`.** Verified directly: real fixture
   templates (`tests/fixtures/templates/documento-generico.json`, section
   `indice`/`referencias`) already put `"toc": true` / `"references_list": true`
   inside `section_contracts` JSON entries, which `Template.from_json` parses
   into `dict[str, SectionContract]` via `model_validate_json`. Today these
   two keys are silently absorbed by `SectionContract`'s `extra="allow"` as
   untyped extra attributes — accessible only via `getattr`, not `.get()`,
   and not visible in the model's declared shape. Also corrects a plan error:
   the original draft of this plan recommended `render_contract_scaffold`
   take `contract: dict[str, Any]` "to stay consistent with
   `review_section_contract`'s contract parameter shape in `domain/rules.py`"
   — but `review_section_contract` (and every caller in `domain/rules.py`)
   actually takes the **typed** `contract: SectionContract` and uses
   attribute access (`contract.length.min_words`, `contract.required_content`,
   `contract.evidence_required`, `contract.apa_required`,
   `contract.pending_allowed_in_draft`) — never `.get()`. That recommendation
   was backwards and is overridden here. Decision: add the two fields to
   `SectionContract` (`domain/models/template.py`) as ordinary typed fields
   (same pattern as `apa_required`/`evidence_required`), and
   `render_section_draft`/`render_contract_scaffold` take
   `contract: SectionContract`, reading `contract.toc`,
   `contract.required_content`, `contract.apa_required`,
   `contract.references_list` by attribute — matching the rest of the
   codebase's typed-contract convention exactly, not a dict-shaped one.

5. **`render_fact_ledger`/`load_manifest_facts` land on `EvidenceService`,
   not a new service.** `load_manifest_facts` reads the same three manifest
   JSON files (`source_manifest`, `issues_manifest`, `code_evidence_manifest`)
   that `EvidenceRepository.read_manifest` already knows how to read (Slice 4),
   and reuses `dedupe_facts` (Slice 7, `domain/collection.py`). No new port
   is needed — `EvidenceRepository.read_manifest`/`file_exists` cover exactly
   this I/O shape. Decision: add `EvidenceService.load_manifest_facts` and
   `EvidenceService.render_fact_ledger` to the existing `EvidenceService`
   (`application/evidence.py`), which already depends on
   `EvidenceRepository` only — consistent with the "grow the existing
   service/port when the I/O shape fits" precedent from Slices 4–7.

6. **`build_section`/`resolve_section_path` land on `ReviewService`, not a
   new service.** Both operate purely on section-file I/O (existence checks,
   read/write, frontmatter) — exactly `SectionRepository`'s existing shape
   (read-only methods from Slice 5 + `write_section` from Slice 6). No new
   port is justified; the I/O shape is identical to what `ReviewService`
   already does in `stamp_section` (Slice 6 Task 5): read current section,
   compute new metadata, `with_frontmatter`, `write_section`. Decision: add
   `ReviewService.build_section` and `ReviewService.resolve_section_path` to
   the existing `ReviewService` (`application/review.py`), depending only on
   `SectionRepository`, mirroring `stamp_section`'s shape closely (including
   reusing its already-established pattern of computing `body_hash` inline
   via `hashlib.sha256` rather than injecting `EvidenceRepository` — same
   single-port-dependency discipline Slice 6 established and Slice 7's
   pre-execution review explicitly endorsed as a precedent).

7. **`generated_metadata_changed` is a pure domain function**, added to
   `domain/sections.py` alongside `with_frontmatter`/`apply_stamp` (its
   sibling frontmatter helpers from Slice 6).

8. **`dedupe_strings` is a pure domain function**, added to
   `domain/markdown_text.py` — it's a generic string-list dedupe utility in
   the same spirit as `clean_markdown_text`, and `render_fact_ledger` is its
   only call site, mirroring legacy's adjacency (lines 1300–1308 sit right
   after `render_fact_ledger`, lines 1225–1282).

9. **`apply_keyword_bold`, `render_toc_section`, `_summarize_context`,
   `render_contract_scaffold`, `render_section_draft`, `_extract_table_value`,
   `_extract_heading_block` are pure domain functions**, added to a new file
   `domain/section_rendering.py`. A new file (not an existing one) because
   none of `markdown_text.py`/`sections.py`/`rules.py`/`evidence.py`/
   `collection.py` is a good home: this is a distinct concern (rendering
   section bodies from context+contract) that doesn't belong inside
   "markdown text utilities," "section frontmatter/stamping," "review rule
   evaluation," "evidence manifests," or "source collection." This mirrors
   the precedent of creating `domain/collection.py` in Slice 7 when an
   existing file's shape didn't fit.

10. **`_extract_table_value`/`_extract_heading_block` are ported even though
    they have no caller within this slice's line range.** I checked: neither
    is called by any function in lines 1157–1445 (legacy's `read_topic`,
    which calls `_extract_table_value`, is itself out of scope per Decision 3).
    They are private (`_`-prefixed) Markdown helpers physically adjacent to
    `apply_keyword_bold`/`_clean_markdown_text` in the legacy file (lines
    1399–1422), clearly part of the same "section rendering toolbox" the
    legacy author grouped together. Since the task explicitly lists them as
    in-scope ("table+heading extraction helpers") and they are pure with zero
    risk of behavioral drift, they are ported now as pure utilities, with no
    production caller yet — same posture as `EvidenceRepository.read_manifest`
    being ported in Slice 4 ahead of a caller, flagged as a documented minor
    if it persists uncalled past this slice's final review.

11. **No typed Config model introduced.** Per the established convention,
    `EvidenceService.render_fact_ledger`/`load_manifest_facts` and
    `ReviewService.build_section`/`resolve_section_path` all take
    `config: dict[str, Any]` and read `config["paths"][...]`/`config.get(...)`
    directly, exactly like every prior service.

## Task breakdown

### Task 1 — Pure domain functions (3 files)

**Files to create/modify:**
- Modify `src/docs/domain/models/template.py` — add `toc: bool = False` and
  `references_list: bool = False` fields to `SectionContract` (see Design
  Decision 4.5). Add/extend `tests/unit/domain/test_template.py` (or wherever
  `SectionContract` is currently tested) to cover parsing `"toc": true` /
  `"references_list": true` from JSON, matching the real fixture shape.
- Modify `src/docs/domain/markdown_text.py` — add `dedupe_strings`.
- Modify `src/docs/domain/sections.py` — add `generated_metadata_changed`.
- Create `src/docs/domain/section_rendering.py` — add `apply_keyword_bold`,
  `render_toc_section`, `_summarize_context`, `render_contract_scaffold`,
  `render_section_draft`, `_extract_table_value`, `_extract_heading_block`.
- Create `tests/unit/domain/test_section_rendering.py`.
- Modify `tests/unit/domain/test_markdown_text.py` (add `dedupe_strings` cases).
- Modify `tests/unit/domain/test_sections.py` (add `generated_metadata_changed` cases).

**Verbatim legacy reference:** see "Legacy code blocks" above —
`dedupe_strings` (1300–1308), `generated_metadata_changed` (1210–1222),
`apply_keyword_bold` (1380–1396), `render_toc_section` (1321–1322),
`_summarize_context` (1325–1339, using `clean_markdown_text` for
`_clean_markdown_text`), `render_contract_scaffold` (1342–1377, with the
`context is None` branch's `load_context_for` call REMOVED per Design
Decision 3 — `context` becomes a required parameter, not optional),
`render_section_draft` (1311–1318), `_extract_table_value` (1399–1404),
`_extract_heading_block` (1407–1422).

**Planned implementation notes:**
- `render_contract_scaffold(section_title: str, contract: SectionContract, context: dict[str, str])`
  — signature changes from legacy's `(config, section, context=None)` to take
  `section_title: str` and the **typed** `contract: SectionContract` (see
  Design Decision 4.5 — NOT a plain dict; read fields via attribute access:
  `contract.required_content`, `contract.apa_required`,
  `contract.references_list`) directly, and a **required**
  `context: dict[str, str]` (no `None` default, no internal
  `load_context_for` call — see Design Decision 3). This is a deliberate,
  documented signature deviation from legacy, not a silent behavior change:
  the *output* for any given `context` dict is byte-for-byte identical to
  legacy; only the responsibility for resolving "what context" moves to the
  caller, which the legacy code already supported via its optional `context`
  parameter — this slice just makes that the only path.
- `render_section_draft(section_id: str, section_title: str, contract: SectionContract, context: dict[str, str], keyword_bold_terms: list[str])`
  — flatten legacy's `config`/`section` dict-reach-throughs into explicit
  parameters (the contract and keyword terms are looked up by the *caller*
  from `template.section_contracts`/`config["format"]["keyword_bold_terms"]`,
  consistent with "pass values in, don't compute internally"). Internally:
  if `contract.toc`, call `render_toc_section`, else
  `render_contract_scaffold`; then `apply_keyword_bold(body, keyword_bold_terms)`.
- `render_toc_section(section_title: str) -> str` — takes the title directly
  instead of a `section` dict (no other field of `section` is used).
- All regexes, the bold-protect-placeholder scheme, the `dedupe`-by-`set`
  pattern, and Spanish strings are transcribed byte-for-byte from the legacy
  blocks above — no rewording, no regex "cleanup."

**Planned test code (representative; implementer fills in full coverage):**

```python
# tests/unit/domain/test_section_rendering.py
import pytest

from docs.domain.models.template import SectionContract
from docs.domain.section_rendering import (
    _extract_heading_block,
    _extract_table_value,
    _summarize_context,
    apply_keyword_bold,
    render_contract_scaffold,
    render_section_draft,
    render_toc_section,
)


class TestApplyKeywordBold:
    def test_no_terms_returns_markdown_unchanged(self):
        assert apply_keyword_bold("hello world", []) == "hello world"

    def test_bolds_matching_term_case_insensitively(self):
        assert apply_keyword_bold("the API is great", ["api"]) == "the **API** is great"

    def test_does_not_double_bold_inside_existing_bold_span(self):
        assert apply_keyword_bold("**API** docs", ["api"]) == "**API** docs"

    def test_longest_term_wins_when_terms_overlap(self):
        result = apply_keyword_bold("REST API client", ["api", "REST API"])
        assert result == "**REST API** client"

    def test_word_boundary_respected(self):
        assert apply_keyword_bold("apiary", ["api"]) == "apiary"


class TestRenderTocSection:
    def test_renders_title_and_toc_marker(self):
        assert render_toc_section("Índice") == "# Índice\n\n[[TOC]]\n"


class TestSummarizeContext:
    def test_extracts_table_rows_as_bullets(self):
        context = {"topic": "| **Campo** | Información |\n| **Nombre** | Juan |\n"}
        assert "- Nombre: Juan" in _summarize_context(context)

    def test_skips_campo_header_row(self):
        context = {"topic": "| **Campo** | Información |\n"}
        assert _summarize_context(context) == []

    def test_prose_topic_without_pipe_yields_snippet_bullet(self):
        context = {"intro": "# Intro\n\nUna nota de prosa relevante."}
        lines = _summarize_context(context)
        assert any("Intro" in line and "prosa relevante" in line for line in lines)


class TestRenderContractScaffold:
    def test_includes_required_content_pendientes(self):
        contract = SectionContract(required_content=["alcance"])
        body = render_contract_scaffold("Resultados", contract, {})
        assert "PENDIENTE: documentar alcance" in body

    def test_includes_apa_pendiente_when_apa_required(self):
        body = render_contract_scaffold("Discusión", SectionContract(apa_required=True), {})
        assert "Fuentes APA 7" in body

    def test_includes_context_section_when_context_present(self):
        context = {"topic": "| **Campo** | Información |\n| **Nombre** | Ana |\n"}
        body = render_contract_scaffold("Intro", SectionContract(), context)
        assert "## Contexto disponible" in body
        assert "- Nombre: Ana" in body

    def test_includes_references_list_pendiente_when_references_list_true(self):
        body = render_contract_scaffold("Referencias", SectionContract(references_list=True), {})
        assert "PENDIENTE: ordenar alfabéticamente" in body


class TestRenderSectionDraft:
    def test_toc_contract_renders_toc_body(self):
        body = render_section_draft("toc", "Índice", SectionContract(toc=True), {}, [])
        assert "[[TOC]]" in body

    def test_non_toc_contract_renders_scaffold_and_applies_bold(self):
        body = render_section_draft("intro", "Introducción", SectionContract(), {}, ["alcance"])
        assert "# Introducción" in body


class TestExtractTableValue:
    def test_extracts_value_for_field(self):
        markdown = "| **Nombre** | Juan |"
        assert _extract_table_value(markdown, "Nombre") == "Juan"

    def test_returns_empty_when_field_absent(self):
        assert _extract_table_value("| **Otro** | x |", "Nombre") == ""


class TestExtractHeadingBlock:
    def test_extracts_block_until_next_heading(self):
        markdown = "# Título\nlinea 1\nlinea 2\n# Otro\nignorada"
        assert _extract_heading_block(markdown, "Título") == "linea 1\nlinea 2"

    def test_returns_empty_when_heading_absent(self):
        assert _extract_heading_block("# Otro\ntexto", "Título") == ""
```

```python
# additions to tests/unit/domain/test_markdown_text.py
from docs.domain.markdown_text import dedupe_strings


def test_dedupe_strings_normalizes_whitespace_and_dedupes():
    assert dedupe_strings(["a  b", "a b", "c"]) == ["a b", "c"]


def test_dedupe_strings_skips_blank_after_normalization():
    assert dedupe_strings(["   ", "x"]) == ["x"]
```

```python
# additions to tests/unit/domain/test_sections.py
from docs.domain.sections import generated_metadata_changed


def test_generated_metadata_changed_true_when_body_hash_differs():
    current = {"schema": 3, "body_hash": "a"}
    new = {"schema": 3, "body_hash": "b"}
    assert generated_metadata_changed(current, new) is True


def test_generated_metadata_changed_false_when_tracked_keys_match():
    payload = {"schema": 3, "title": "t", "body_hash": "a", "untracked": "x"}
    other = dict(payload, untracked="y")
    assert generated_metadata_changed(payload, other) is False
```

**Expected test count:** ~24 new tests (15 in `test_section_rendering.py`,
2 in `test_markdown_text.py`, 2 in `test_sections.py`, 2-3 for
`SectionContract`'s new `toc`/`references_list` fields, plus a handful more
the implementer adds for full branch coverage of `apply_keyword_bold`'s
placeholder-protection loop — target 365 → ~389).

---

### Task 2 — Port growth: `EvidenceRepository` (self-reviewed, bare Protocol)

**Files to create/modify:**
- Modify `src/docs/domain/ports/evidence_repository.py`.

**Rationale:** `load_manifest_facts` needs to read three manifest paths
(already covered by `read_manifest`/`file_exists`, both already on the
Protocol — **no new method needed here**). On inspection, the existing
`EvidenceRepository` Protocol already has every method `EvidenceService`
needs for both `load_manifest_facts` and `render_fact_ledger`. **This task
is a no-op** — confirmed during planning, not skipped silently. Recorded as
its own task entry only so the per-task dependency-ordering convention
(domain → port growth → adapter → application) is visible in the ledger;
the actual diff for this task is empty. If the implementer finds a genuine
gap (e.g., a need to distinguish manifest-absent from manifest-malformed
that `read_manifest -> dict | None` can't express), surface it before writing
any code rather than improvising a signature change.

**Expected test count:** 0 (no Protocol change; full suite stays at the
Task 1 exit count).

---

### Task 3 — Application layer: `EvidenceService.load_manifest_facts` / `render_fact_ledger`

**Files to create/modify:**
- Modify `src/docs/application/evidence.py`.
- Create `tests/integration/test_evidence_service_ledger.py` (or extend
  `tests/integration/test_evidence_service.py` — implementer's call, follow
  whichever existing file groups `EvidenceService` integration tests; if a
  single file, keep it one file).

**Verbatim legacy reference:** `load_manifest_facts` (1285–1297, using
`dedupe_facts` from `domain/collection.py`), `render_fact_ledger` (1225–1282).

**Planned implementation:**

```python
# additions to src/docs/application/evidence.py
from docs.domain.collection import dedupe_facts
from docs.domain.markdown_text import dedupe_strings

_LEDGER_HEADINGS = {
    "confirmado": "Datos confirmados",
    "contradiccion": "Contradicciones conocidas",
    "pendiente": "Pendientes obligatorios",
    "prototipo": "Prototipos o dependencias externas",
    "fuera_de_alcance": "Fuera de alcance del cuerpo",
    "dato_sensible": "Datos sensibles excluidos del cuerpo",
}


class EvidenceService:
    ...

    def load_manifest_facts(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        for key in ["source_manifest", "issues_manifest", "code_evidence_manifest"]:
            path_str = config["paths"].get(key, "")
            path = Path(path_str)
            if not self.repository.file_exists(path):
                continue
            data = self.repository.read_manifest(path)
            if not data:
                continue
            facts.extend(item for item in data.get("facts", []) if isinstance(item, dict))
            facts.extend(item for item in data.get("issues", []) if isinstance(item, dict))
        return dedupe_facts(facts)

    def render_fact_ledger(
        self,
        config: dict[str, Any],
        context_confirmed_lines: list[str] | None = None,
    ) -> str:
        grouped: dict[str, list[str]] = {key: [] for key in _LEDGER_HEADINGS}

        for fact in config.get("ledger_seed", []):
            classification = fact.get("classification", "confirmado")
            claim = fact.get("claim", "")
            if claim:
                grouped.setdefault(classification, []).append(claim)

        for line in context_confirmed_lines or []:
            grouped["confirmado"].append(line)

        for fact in self.load_manifest_facts(config):
            classification = fact.get("classification", "pendiente")
            claim = fact.get("claim") or fact.get("title", "")
            if claim:
                grouped.setdefault(classification, []).append(claim)

        lines = ["# Fact Ledger", ""]
        for key, title in _LEDGER_HEADINGS.items():
            values = dedupe_strings(grouped.get(key, []))
            if not values:
                continue
            lines.extend([f"## {title}", ""])
            lines.extend(f"- {value}" for value in values)
            lines.append("")
        return "\n".join(lines)
```

> Note on `render_fact_ledger`'s step 2 ("Datos confirmados desde los temas
> de contexto"): per Design Decision 3, this is NOT computed inside
> `render_fact_ledger`. The caller (a future slice, or the CLI/orchestrator
> layer) is responsible for running `ContextService.status`-equivalent logic
> and rendering each non-empty, non-sensitive field as a `"{label}: {value}"`
> string and each sensitive field as a `"{label} (dato sensible; excluido
> del cuerpo)."` string into the `dato_sensible` group BEFORE calling
> `render_fact_ledger`. This plan's `render_fact_ledger` accepts only the
> `confirmado`-classified lines via `context_confirmed_lines` because the
> `dato_sensible` classification requires per-field `sensitive` flags that
> `Topic.fields[].sensitive` already models — pushing that branch back into
> the caller is the same "don't reach into another port" choice as Decision 3
> consistently, not a new ad-hoc shortcut. **Open question for implementer/
> reviewer:** if this asymmetry (confirmed lines accepted, but not sensitive
> lines) turns out to need its own parameter for completeness, add
> `sensitive_lines: list[str] | None = None` analogously rather than reaching
> into `ContextRepository` — flag this as a documented decision either way
> in the task's completion log.

**Planned test code (representative):**

```python
# tests/integration/test_evidence_service.py (additions)
def test_load_manifest_facts_dedupes_across_manifests(tmp_path):
    repo = JsonEvidenceRepository()
    service = EvidenceService(repo)
    source_manifest = tmp_path / "source.json"
    repo.write_manifest(source_manifest, {"facts": [{"classification": "confirmado", "claim": "x", "source": "a"}]})
    config = {"paths": {"source_manifest": str(source_manifest), "issues_manifest": "", "code_evidence_manifest": ""}}

    facts = service.load_manifest_facts(config)

    assert facts == [{"classification": "confirmado", "claim": "x", "source": "a"}]


def test_render_fact_ledger_includes_ledger_seed_and_manifest_facts(tmp_path):
    repo = JsonEvidenceRepository()
    service = EvidenceService(repo)
    config = {
        "paths": {"source_manifest": "", "issues_manifest": "", "code_evidence_manifest": ""},
        "ledger_seed": [{"classification": "confirmado", "claim": "Hecho sembrado"}],
    }

    ledger = service.render_fact_ledger(config)

    assert "# Fact Ledger" in ledger
    assert "## Datos confirmados" in ledger
    assert "- Hecho sembrado" in ledger


def test_render_fact_ledger_omits_empty_groups(tmp_path):
    config = {"paths": {"source_manifest": "", "issues_manifest": "", "code_evidence_manifest": ""}}
    ledger = EvidenceService(JsonEvidenceRepository()).render_fact_ledger(config)
    assert "## Contradicciones conocidas" not in ledger


def test_render_fact_ledger_includes_caller_supplied_context_lines():
    config = {"paths": {"source_manifest": "", "issues_manifest": "", "code_evidence_manifest": ""}}
    ledger = EvidenceService(JsonEvidenceRepository()).render_fact_ledger(
        config, context_confirmed_lines=["Nombre: Ana"]
    )
    assert "- Nombre: Ana" in ledger
```

**Expected test count:** ~8 new integration tests.

---

### Task 4 — Port growth: `SectionRepository` (likely self-reviewed)

**Files to create/modify:**
- Modify `src/docs/domain/ports/section_repository.py`.

**Rationale:** `build_section` needs: section existence check (already
`section_exists`), read current section (already `read_section`), write
generated/proposal text (already `write_section`), and resolve the section
path (already `section_path`). On inspection, the existing 5-method
`SectionRepository` Protocol (post-Slice-6) already covers every I/O
operation `ReviewService.build_section`/`resolve_section_path` need —
**no new method required.** Like Task 2, this task's diff is empty; recorded
to preserve the dependency-ordering convention. The one operation
`build_section` performs that the Protocol does NOT cover —
`proposals_dir.mkdir(parents=True, exist_ok=True)` plus writing to
`{order:03d}-{section_id}.candidate.md` under a `_proposals/` subdirectory —
is handled by extending `write_section`'s existing contract: see Task 5
($JsonSectionRepository.write_section$ already does `mkdir`-then-write
generically for ANY path under the document's `sections/` tree, so writing
to a `_proposals/` subpath works without a new method, AS LONG AS the
proposal path is constructed by the application layer and passed through
the existing write path). **Confirmed by direct inspection (not left as an
open question): `write_section` is NOT a generic path-accepting write — it
calls its own `section_path(doc_id, order, section_id)` internally to
compute the write target and has no path parameter at all** (see
`json_section_repository.py:32-35`). It cannot express a `_proposals/`
subpath. Task 4 is therefore confirmed NOT a no-op: add
`write_proposal_section(doc_id: str, order: int, section_id: str, raw_text: str) -> Path`
to `SectionRepository` (mirroring `write_section`'s shape, parity-justified
by `build_section`'s own proposal-path construction at line 1202).

**Expected test count:** 0 (bare Protocol addition, self-reviewed per
Slice 4/5/6/7 Task 2 precedent — behavior tested at the adapter layer in
Task 5, not the Protocol itself).

---

### Task 5 — Infrastructure: `JsonSectionRepository.write_proposal_section`

**Files to create/modify:**
- Modify `src/docs/infrastructure/persistence/json_section_repository.py`.
- Modify `tests/unit/infrastructure/test_json_section_repository.py`.

**Planned implementation** (verified against the real file —
`_sections_dir(doc_id)` is the existing private helper name,
`json_section_repository.py:13-14`):

```python
def write_proposal_section(self, doc_id: str, order: int, section_id: str, raw_text: str) -> Path:
    proposals_dir = self._sections_dir(doc_id) / "_proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    path = proposals_dir / f"{order:03d}-{section_id}.candidate.md"
    path.write_text(raw_text, encoding="utf-8")
    return path
```

**Planned test code:**

```python
def test_write_proposal_section_creates_proposals_dir_and_writes_file(tmp_path):
    repo = JsonSectionRepository(tmp_path)
    repo.write_proposal_section("doc1", 3, "intro", "---\n{}\n---\nbody")
    path = tmp_path / "doc1" / "sections" / "_proposals" / "003-intro.candidate.md"
    assert path.read_text(encoding="utf-8") == "---\n{}\n---\nbody"


def test_write_proposal_section_returns_the_written_path(tmp_path):
    repo = JsonSectionRepository(tmp_path)
    path = repo.write_proposal_section("doc1", 3, "intro", "text")
    assert path.name == "003-intro.candidate.md"
```

**Expected test count:** ~2.

---

### Task 6 — Application layer: `ReviewService.build_section` / `resolve_section_path`

**Files to create/modify:**
- Modify `src/docs/application/review.py`.
- Modify `tests/integration/test_review_service.py`.

**Verbatim legacy reference:** `build_section` (1157–1207),
`resolve_section_path` (1434–1442).

**Planned implementation:**

```python
# additions to src/docs/application/review.py
from docs.domain.sections import generated_metadata_changed  # alongside existing apply_stamp/with_frontmatter import


class ReviewService:
    ...

    def build_section(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        body: str,
        *,
        source_hash: str,
        source_manifest_hash: str,
        code_evidence_manifest_hash: str,
        rules_hash: str,
        contract_hash: str,
        prompt_hash: str,
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        metadata = {
            "managed_by": "tesina-harness",
            "authored_by": "harness-scaffold",
            "schema": 3,
            "section_id": section_id,
            "title": section.title,
            "source_hash": source_hash,
            "source_manifest_hash": source_manifest_hash,
            "code_evidence_manifest_hash": code_evidence_manifest_hash,
            "rules_hash": rules_hash,
            "contract_hash": contract_hash,
            "prompt_hash": prompt_hash,
            "body_hash": body_hash,
            "last_review_hash": "",
        }
        generated = with_frontmatter(body, metadata)
        section_path = self.repository.section_path(doc_id, section.order, section.id)

        if self.repository.section_exists(doc_id, section.order, section.id):
            current_metadata, current_body = self.repository.read_section(doc_id, section.order, section.id)
            if not current_metadata and current_body == body:
                self.repository.write_section(doc_id, section.order, section.id, generated)
                return section_path
            is_managed = current_metadata.get("managed_by") == "tesina-harness"
            current_body_hash = hashlib.sha256(current_body.encode("utf-8")).hexdigest()
            is_unchanged = current_metadata.get("body_hash") == current_body_hash
            if is_managed and is_unchanged:
                if generated_metadata_changed(current_metadata, metadata):
                    self.repository.write_section(doc_id, section.order, section.id, generated)
                return section_path

            return self.repository.write_proposal_section(doc_id, section.order, section.id, generated)

        self.repository.write_section(doc_id, section.order, section.id, generated)
        return section_path

    def resolve_section_path(self, doc_id: str, template: Template, section_or_id: str) -> Path:
        for section in template.sections:
            if section.id == section_or_id:
                return self.repository.section_path(doc_id, section.order, section.id)
        raise FileNotFoundError(f"No existe sección: {section_or_id}")
```

> Parity note (must be re-verified by implementer/reviewer against the
> legacy block above): legacy's first branch checks
> `current_text == body` (the FULL raw current text, including any leading
> frontmatter block) against `body` (just the rendered body, no frontmatter)
> — meaning this branch is only true when the existing file has NO
> frontmatter at all (`current_meta` is falsy from `split_frontmatter`) AND
> its entire raw content equals the new body exactly. Since
> `SectionRepository.read_section` already returns `(metadata, body)` via
> `split_frontmatter` (Slice 5 Task 3), `current_metadata` empty +
> `current_body == body` is the behaviorally-equivalent translation — `read_section`
> already did the frontmatter split that legacy's inline `split_frontmatter`
> call does, so comparing against `current_body` (the split body) rather
> than `current_text` (the raw text) is correct PROVIDED `read_section`
> returns `body` unchanged when there's no frontmatter to split (verify this
> against `split_frontmatter`'s actual no-frontmatter behavior — it returns
> `({}, raw_text)` unchanged, so `current_body` IS `current_text` in that
> branch, confirming equivalence). Implementer must verify this reasoning
> against the real `read_section`/`split_frontmatter` code before treating it
> as settled, and the reviewer must independently re-derive it — flag any
> discrepancy rather than silently trusting this plan's note.
>
> Also note: legacy's `resolve_section_path` has a FIRST branch
> (`candidate = Path(section_or_path); if candidate.exists(): return candidate`)
> that this plan's port DROPS. This is a deliberate, documented exception:
> that branch lets the legacy CLI accept either a section id OR a literal
> filesystem path typed by a human at the command line — a CLI-ergonomics
> concern with no equivalent in this codebase yet (no CLI exists per Slice 1's
> deferred scope). Porting it now would require a bare `Path.exists()` call
> with no `doc_id`/`SectionRepository` context, which doesn't fit
> `ReviewService`'s shape at all. Decision: port only the section-id-lookup
> branch; the bare-path-passthrough branch is deferred to whichever future
> CLI slice actually needs it, where it can be implemented as a CLI-layer
> concern (try the literal path first, fall back to `ReviewService.resolve_section_path`)
> rather than inside the service.

**Planned test code (representative):**

```python
# tests/integration/test_review_service.py (additions)
def test_build_section_writes_new_section_when_absent(tmp_path):
    repo = JsonSectionRepository(tmp_path)
    service = ReviewService(repo)
    template = _template_with_section("intro", order=1, title="Introducción")

    path = service.build_section(
        "doc1", template, "intro", "# Introducción\n\nbody",
        source_hash="sh", source_manifest_hash="smh", code_evidence_manifest_hash="cemh",
        rules_hash="rh", contract_hash="ch", prompt_hash="ph",
    )

    metadata, body = repo.read_section("doc1", 1, "intro")
    assert metadata["managed_by"] == "tesina-harness"
    assert body == "# Introducción\n\nbody"


def test_build_section_overwrites_when_managed_and_unchanged_with_metadata_drift(tmp_path):
    # Seed a managed section whose body matches its stored body_hash but whose
    # title (a generated_metadata_changed-tracked key) differs from the new render.
    ...


def test_build_section_writes_proposal_when_unmanaged_and_modified(tmp_path):
    ...


def test_build_section_no_op_when_managed_unchanged_and_metadata_identical(tmp_path):
    ...


def test_resolve_section_path_returns_path_for_known_section_id(tmp_path):
    repo = JsonSectionRepository(tmp_path)
    service = ReviewService(repo)
    template = _template_with_section("intro", order=1, title="Introducción")

    path = service.resolve_section_path("doc1", template, "intro")

    assert path == repo.section_path("doc1", 1, "intro")


def test_resolve_section_path_raises_for_unknown_section(tmp_path):
    repo = JsonSectionRepository(tmp_path)
    service = ReviewService(repo)
    template = _template_with_section("intro", order=1, title="Introducción")

    with pytest.raises(FileNotFoundError):
        service.resolve_section_path("doc1", template, "missing")
```

**Expected test count:** ~7 new integration tests (covering all 4
`build_section` branches: new file / no-frontmatter-body-match /
managed-unchanged-with-and-without-metadata-drift / unmanaged-modified-proposal;
plus 2 for `resolve_section_path`).

---

## Out-of-scope confirmation

- **`review_section`** (legacy 1445–1499) — confirmed already ported as
  `domain.rules.review_section_text` (Slice 3) + `ReviewService.review_document`
  (Slice 5). Not re-touched in this slice. See Design Decision 0/1.
- **`section_by_id` / `section_path_for`** (legacy 594–605) — not re-ported
  as free functions; satisfied by `Template.sections` + `SectionRepository.section_path`.
  See Design Decision 2.
- **`load_context` / `load_context_for` / `context_schema` / `read_topic` /
  `topic_file_path` / `write_topic` / `topic_missing_fields` /
  `context_completion` / `regenerate_context_index` / `load_context_index`**
  (legacy 606–747) — `load_context`'s shape is already covered by
  `SourceRepository.read_context_texts` (Slice 7); the rest are superseded by
  `ContextRepository`/`ContextService` (Slice 2) and not re-derived. See
  Design Decision 3.
- **`source_hash` / `prompt_hash`** (legacy 417–439) — still deferred, same
  reasoning as Slice 6 (`context_dir`+`manual_dir`+flat-`config["sections"]`
  globbing for the former; unmodeled `prompts_dir` for the latter). See
  Design Decision 4.
- **`format_audit_docx` / `build_docx` / everything from Slice 9+** — not
  touched; out of this line range entirely.
- **The full `resolve_executable` fallback machinery** — deferred to Slices
  10–12 per Slice 7's decision; this slice doesn't call it at all (legacy
  `build_section`'s line range has no executable-resolution calls).
- **Any typed `Config` model** — confirmed absent from the whole codebase
  (Slice 7); not introduced here. All new service methods take
  `config: dict[str, Any]`.
- **CLI commands invoking `build_section`/`resolve_section_path`** — no
  `cli/` directory exists yet (confirmed via the Slice 7 final review's
  grep); out of scope until a CLI slice.

## Global constraints

- **Config-as-dict convention.** No typed `Config` Pydantic model exists
  anywhere in this codebase (confirmed in Slice 7's pre-execution review and
  reconfirmed here by reading `application/evidence.py`/`application/review.py`
  directly). Every new/extended service method in this slice reads
  `config["paths"][...]` / `config.get(...)` directly, exactly like
  `EvidenceService.build_rules`/`rules_hash` and `CollectionService.collect_sources`
  already do. Do not introduce a typed config model in this slice.
- **Parity discipline.** Every ported function must be byte-for-byte
  behaviorally identical to the legacy block quoted above for it, including
  Spanish strings, regexes, truncation lengths (160, 200), and the exact
  placeholder scheme (`@@TESINA_BOLD_{n}@@`). Any signature change from the
  legacy `(config, section_dict, ...)` shape to this codebase's
  `(doc_id, template, explicit params, ...)` shape must be documented as a
  signature-only deviation with an explicit argument that the *output*
  is unchanged for equivalent inputs (see Design Decisions 2, 3, 6 and
  Task 6's `resolve_section_path` note for the one genuine behavior
  reduction — the dropped bare-path branch — which is flagged, not silently
  dropped).
- **"Pass values in, don't compute internally."** `source_hash`,
  `prompt_hash`, and context-confirmed-fact lines are all caller-supplied
  parameters to the new service methods rather than computed by reaching
  into ports those services don't otherwise need (`ContextRepository`,
  the not-yet-modeled `prompts_dir` concept). This mirrors Slice 6/7's
  `repo_root: Path`/hash-injection precedent exactly.
  
- **Single-port-dependency discipline per service.** `EvidenceService`
  continues to depend only on `EvidenceRepository`; `ReviewService` continues
  to depend only on `SectionRepository`. Neither grows a second port in this
  slice. `body_hash` computation inside `ReviewService.build_section` uses
  inline `hashlib.sha256`, mirroring `stamp_section`'s already-established
  exception (Slice 6 Task 5) rather than reaching into `EvidenceRepository.hash_text`.
- **Grow-only ports, justified each time.** Tasks 2 and 4 are explicitly
  expected to be no-ops (or near-no-ops) on the Protocol level — confirmed by
  re-reading the current `EvidenceRepository`/`SectionRepository` definitions
  before planning, not assumed. If an implementer discovers mid-task that a
  genuine gap exists, they must document the specific I/O shape that doesn't
  fit before adding a method, per the same bar Slice 7 used to justify the
  new `SourceRepository` port over extending `EvidenceRepository`.
- **Strict TDD per task.** Each task above is independently testable and
  committable: failing test → minimal implementation → passing test → commit,
  then independent fresh-context review, exactly as Slices 1–7.
- **No CLI, no orchestration glue in this slice.** This slice stops at
  `ReviewService`/`EvidenceService` methods. Whatever future component
  resolves "which context does this section consume" (replacing legacy's
  `load_context_for`) and wires `build_section`'s six injected hash
  parameters together end-to-end is explicitly future work, not this slice's
  responsibility.
