# Slice 9 — Context Packing & Assets · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 1789–2015 (`_keyword_set` through `pack_context_document`)

## Overview / Scope

This slice ports the harness's two remaining "assemble a curated bundle for
an external agent" capabilities:

1. **Context packing** — `pack_context` (single section) and
   `pack_context_document` (whole-document closing pass) assemble a
   Markdown briefing file combining the section contract, role prompts,
   relevant Fact Ledger lines, relevant manifest evidence, the current
   draft body, and current review findings, so an external authoring agent
   has everything it needs in one file.
2. **Asset management** — `add_asset`/`list_assets`/`remove_asset` let the
   author attach pre-made `.docx` files (cover pages, appendices) to a
   document, stored under an `assets/` directory, copied in via
   `shutil.copy2`.

Ported in this slice (all from legacy lines 1789–2015):

- `_keyword_set` (pure) — builds a lowercased token set (`len >= 4`) from
  one or more input texts, via `normalize_author_key`.
- `_matches_keywords` (pure) — empty-keywords-matches-everything
  short-circuit, then substring containment check against
  `normalize_author_key(text)`.
- `read_prompt` (impure: reads a prompt file as plain text, returns `""`
  if absent) — ported as a small `ContextPackService` helper taking
  `prompts_dir: Path`, composing `EvidenceRepository.file_exists`/`read_text`
  (no new port method — see Design Decision 6).
- `context_pack_dir` (pure path arithmetic) — ported as
  `SectionRepository.context_pack_path` (see Design Decision 5), not a
  free function.
- `assets_dir` / `asset_path` (pure path arithmetic) — ported as
  `AssetRepository`-adjacent path helpers (see Design Decision 1).
- `add_asset` (impure: existence/suffix validation, `mkdir`, `shutil.copy2`)
  — ported as `AssetService.add_asset`.
- `list_assets` (impure: directory glob) — ported as
  `AssetService.list_assets`.
- `remove_asset` (impure: existence check + `unlink`) — ported as
  `AssetService.remove_asset`.
- `pack_context` (impure: composes section lookup, contract lookup,
  keyword extraction, prompt reads, ledger read, manifest facts, current
  draft + review, then writes the pack file) — ported as
  `ContextPackService.pack_context`.
- `pack_context_document` (impure: composes a per-section status table,
  role prompts, `review_document`, and the Fact Ledger file) — ported as
  `ContextPackService.pack_context_document`.

Explicitly **not** ported in this slice (see "Out of scope" below):

- `section_by_id` / `section_path_for` (legacy lines 594–605) — not
  re-ported as free functions; satisfied by `Template.sections` +
  `SectionRepository.section_path`, per Slice 8 Design Decision 2.
- `_as_posix` (legacy lines 208–209) — trivial `.resolve().as_posix()`,
  already inlined at call sites throughout this codebase since Slice 4/7;
  not a standalone port. This slice's `pack_context_document` has no
  `_as_posix` call site in its ported range (the ledger-path reference in
  legacy's `pack_context_document` prints `_as_posix(ledger_path)` — ported
  inline the same way).
- `review_section` (legacy's single-file review entry point, called from
  `pack_context`) — **does not exist as a standalone function in this
  codebase.** A new `ReviewService.review_section` method is added in this
  slice (Task 3) to fill the gap — see Design Decision 3. This is a new
  capability, not a re-port of an existing legacy free function of the
  same name (legacy's own single-file `review_section`, lines 1445–1499,
  was already ported as `domain.rules.review_section_text` in Slice 3/5 —
  see Slice 8 Design Decision 0/1). The method this slice adds is a thin
  single-section *orchestration* wrapper with the same name as legacy's
  call site expects, composing `review_section_text` for exactly one
  section, mirroring what `review_document`'s loop body already does.
- Everything from Slice 10+ (`format_audit_docx`, `build_docx`, etc.) —
  out of this line range entirely.

## Legacy code blocks

### `_keyword_set` (lines 1789–1796)

```python
def _keyword_set(*texts: str) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        normalized = normalize_author_key(text)
        for token in normalized.split():
            if len(token) >= 4:
                tokens.add(token)
    return tokens
```

### `_matches_keywords` (lines 1799–1803)

```python
def _matches_keywords(text: str, keywords: set[str]) -> bool:
    if not keywords:
        return True
    normalized = normalize_author_key(text)
    return any(keyword in normalized for keyword in keywords)
```

### `read_prompt` (lines 1806–1810)

```python
def read_prompt(config: dict[str, Any], name: str) -> str:
    path = Path(config["paths"]["prompts_dir"]) / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""
```

### `context_pack_dir` (lines 1813–1814)

```python
def context_pack_dir(config: dict[str, Any]) -> Path:
    return Path(config["paths"]["sections_dir"]) / "_context"
```

### `assets_dir` / `asset_path` (lines 1819–1825)

```python
def assets_dir(config: dict[str, Any]) -> Path:
    return Path(config["paths"]["assets_dir"])


def asset_path(config: dict[str, Any], name: str) -> Path:
    safe = name if name.lower().endswith(".docx") else f"{name}.docx"
    return assets_dir(config) / safe
```

### `add_asset` (lines 1828–1837)

```python
def add_asset(config: dict[str, Any], src: str, name: str = "") -> Path:
    source = Path(src)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"No existe el archivo a adjuntar: {source}")
    if source.suffix.lower() != ".docx":
        raise ValueError(f"Sólo se admiten archivos .docx como asset: {source.name}")
    target_name = name or source.stem
    target = asset_path(config, target_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
```

### `list_assets` (lines 1840–1844)

```python
def list_assets(config: dict[str, Any]) -> list[str]:
    directory = assets_dir(config)
    if not directory.exists():
        return []
    return [path.stem for path in sorted(directory.glob("*.docx"))]
```

### `remove_asset` (lines 1847–1850)

```python
def remove_asset(config: dict[str, Any], name: str) -> None:
    target = asset_path(config, name)
    if target.exists():
        target.unlink()
```

### `pack_context` (lines 1853–1928)

```python
def pack_context(config: dict[str, Any], section_id: str) -> Path:
    """Ensambla el contexto mínimo y exacto que un agente externo necesita para redactar una sección."""
    section = section_by_id(config, section_id)
    contract = config.get("section_contracts", {}).get(section_id, {})
    required = contract.get("required_content", [])
    apa_required = bool(contract.get("apa_required"))
    keywords = _keyword_set(section.get("title", ""), section_id, " ".join(required))

    lines: list[str] = [
        f"# Context pack — {section['title']}",
        "",
        "_Paquete generado por el arnés. Es el contexto curado para redactar esta sección. "
        "Redacta con `prompts/section-author.md`, luego corre `review-section "
        f"{section_id} --strict --json` y corrige hasta quedar en verde._",
        "",
        "## Contrato de sección",
        "",
        "```json",
        json.dumps(contract, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Checklist de contenido obligatorio",
        "",
    ]
    if required:
        lines.extend(f"- [ ] {item}" for item in required)
    else:
        lines.append("- (Sin `required_content` declarado.)")
    lines.extend(["", f"APA 7 requerido: {'sí' if apa_required else 'no'}.", ""])

    # Prompts relevantes
    prompt_names = ["section-planner.md", "section-author.md", "section-reviewer.md"]
    if apa_required:
        prompt_names.append("apa7-citation-auditor.md")
    lines.extend(["## Prompts del rol", ""])
    for name in prompt_names:
        content = read_prompt(config, name)
        if content:
            lines.extend([f"### {name}", "", content, ""])

    # Hechos relevantes del ledger
    ledger_path = Path(config["paths"]["fact_ledger"])
    if ledger_path.exists():
        ledger_lines = [
            line.strip()
            for line in ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("- ") and _matches_keywords(line, keywords)
        ]
        if ledger_lines:
            lines.extend(["## Hechos relevantes del ledger", ""])
            lines.extend(ledger_lines)
            lines.append("")

    # Evidencia relevante de los manifests
    manifest_facts = [
        fact
        for fact in load_manifest_facts(config)
        if _matches_keywords(f"{fact.get('claim', '')} {fact.get('title', '')}", keywords)
    ]
    if manifest_facts:
        lines.extend(["## Evidencia relevante (manifests)", ""])
        for fact in manifest_facts[:40]:
            claim = fact.get("claim") or fact.get("title") or ""
            classification = fact.get("classification", "")
            source = fact.get("source") or fact.get("url") or ""
            suffix = f" — {source}" if source else ""
            tag = f"[{classification}] " if classification else ""
            lines.append(f"- {tag}{claim}{suffix}")
        lines.append("")

    # Borrador actual y hallazgos
    section_path = section_path_for(config, section)
    if section_path.exists():
        _metadata, body = split_frontmatter(section_path.read_text(encoding="utf-8"))
        review = review_section(section_path, config=config, strict=False)
        lines.extend(["## Borrador actual", "", "```markdown", body.strip(), "```", ""])
        lines.extend(["## Hallazgos actuales (review-section)", ""])
        if review.issues:
            for issue in review.issues:
                code = f" ({issue.code})" if issue.code else ""
                lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
        else:
            lines.append("- Sin hallazgos.")
        lines.append("")
    else:
        lines.extend(["## Borrador actual", "", "_Aún no existe; ejecuta `build-section "
                      f"{section_id}` para generar el scaffold inicial._", ""])

    out_dir = context_pack_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{section['order']:03d}-{section_id}.context.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
```

### `pack_context_document` (lines 1931–2015)

```python
def pack_context_document(config: dict[str, Any]) -> Path:
    """Context pack a nivel documento: estado global + coherencia cruzada para la pasada final."""
    lines: list[str] = [
        "# Context pack — DOCUMENTO COMPLETO",
        "",
        "_Paquete para la revisión global y el cierre del documento. Úsalo con el rol "
        "`document-reviewer.md` y corre `review-document --strict --json` y `verify --strict` "
        "hasta quedar en verde._",
        "",
        "## Estado por sección",
        "",
        "| Sección | Existe | Palabras | PENDIENTE | Autor | Modelo |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for section in sorted(config["sections"], key=lambda item: item["order"]):
        path = section_path_for(config, section)
        if not path.exists():
            lines.append(f"| {section['id']} | no | – | – | – | – |")
            continue
        raw = path.read_text(encoding="utf-8")
        metadata, body = split_frontmatter(raw)
        words = len(re.findall(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b", _strip_frontmatter_and_markdown(raw)))
        pending = "sí" if "PENDIENTE" in body else "no"
        author = metadata.get("authored_by", "–")
        model = metadata.get("model", "–")
        lines.append(f"| {section['id']} | sí | {words} | {pending} | {author} | {model} |")
    lines.append("")

    # Prompts globales del rol
    lines.extend(["## Prompts del rol", ""])
    for name in ["document-reviewer.md", "docx-builder.md", "format-auditor.md"]:
        content = read_prompt(config, name)
        if content:
            lines.extend([f"### {name}", "", content, ""])

    # Hallazgos globales (incluye consistencia cruzada)
    review = review_document(config, strict=False)
    lines.extend(["## Hallazgos globales (review-document)", ""])
    if review.issues:
        for issue in review.issues:
            code = f" ({issue.code})" if issue.code else ""
            lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
    else:
        lines.append("- Sin hallazgos.")
    lines.append("")

    # Ledger como referencia de hechos canónicos
    ledger_path = Path(config["paths"]["fact_ledger"])
    if ledger_path.exists():
        lines.extend(
            [
                "## Hechos canónicos (ledger)",
                "",
                f"Fuente de verdad: `{_as_posix(ledger_path)}`. Toda afirmación del documento debe ser consistente con estos hechos.",
                "",
                ledger_path.read_text(encoding="utf-8").strip(),
                "",
            ]
        )

    out_dir = context_pack_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "000-document.context.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
```

## Verified context (read directly before writing this plan)

- `SectionRepository` Protocol (`src/docs/domain/ports/section_repository.py`)
  currently has 6 methods: `section_path`, `sections_dir_exists`,
  `section_exists`, `read_section`, `write_section`,
  `write_proposal_section`. No method exposes the section's *content* in a
  shape suitable for a "section pack output directory" concept yet — see
  Design Decision 5.
- `EvidenceRepository` Protocol (`src/docs/domain/ports/evidence_repository.py`)
  already has `read_text(path) -> str` and `file_exists(path) -> bool`,
  both already used by `EvidenceService`/`CollectionService` for arbitrary
  text-file reads. This fully covers `read_prompt`'s I/O shape (file
  existence check + read) and the Fact Ledger file's I/O shape — confirmed
  no new port method is needed for either. See Design Decision 6.
- `EvidenceService.load_manifest_facts` (`src/docs/application/evidence.py`,
  already implemented in Slice 8) is directly reusable for `pack_context`'s
  manifest-evidence step — no reimplementation needed.
- `EvidenceService.render_fact_ledger` (also Slice 8) is reusable if a
  caller wants to *regenerate* the ledger, but `pack_context`/
  `pack_context_document` only *read* an already-rendered ledger file off
  disk via `fact_ledger` path — they never call `render_fact_ledger`
  themselves. This is preserved: ported code reads the ledger file via
  `EvidenceRepository.file_exists`/`read_text`, not via `render_fact_ledger`.
- `ReviewService` (`src/docs/application/review.py`) currently has
  `review_document`, `stamp_section`, `build_section`,
  `resolve_section_path` — all depending only on `SectionRepository`. It
  has **no single-section review entry point**. `review_document`'s loop
  body (lines 48–85) is the exact logic `pack_context` needs for one
  section: read section, resolve `section_id`/`contract` from metadata or
  path inference, call `domain.rules.review_section_text` with the same
  kwargs bundle. See Design Decision 3 for the new `review_section` method.
- `domain.rules.review_section_text` signature (confirmed by direct read):
  `(text, metadata, section_id, contract, template, strict, *,
  excluded_terms, is_policy_file, first_person_patterns, subjective_terms,
  secret_patterns, scope_term="", scope_focus="") -> list[Issue]`. A new
  `ReviewService.review_section` method threads the identical kwargs
  bundle, exactly as `review_document` already does for each section in
  its loop.
- `Template`/`Section`/`SectionContract` (`src/docs/domain/models/template.py`,
  Pydantic, confirmed): `Section` has `id: str`, `title: str`,
  `order: int = 0`, `required: bool`, `optional: bool`. `SectionContract`
  has `required_content: list[str]`, `apa_required: bool`, plus `toc`,
  `references_list`, `evidence_required`, `length`, `detect`,
  `pending_allowed_in_draft` (all typed fields, `extra="allow"`). Confirmed:
  `template.sections` + `template.section_contracts` give everything
  `pack_context` needs to replace legacy's `section_by_id`/dict-contract
  lookups — no config-dict needed for the section/contract shape itself
  (though `config: dict[str, Any]` is still used for `paths`/`prompts_dir`-
  shaped values, per the established convention).
- `domain.markdown_text` (confirmed, exact names): `normalize_author_key`,
  `strip_frontmatter_and_markdown`, `split_frontmatter`,
  `clean_markdown_text`, `dedupe_strings`, `normalize_for_sort`,
  `extract_markdown_headings` all already exist with these exact names.
  Legacy's `_strip_frontmatter_and_markdown` matches
  `strip_frontmatter_and_markdown` byte-for-byte (already ported, Slice 5).
- `Workspace` (`src/docs/domain/workspace.py`, confirmed): only
  `documents_dir: Path`, `templates_dir: Path`, `registry_path` (property),
  `doc_root(doc_id) -> Path`. No `assets_dir`/`prompts_dir` concept exists
  anywhere in this codebase yet. See Design Decision 1 for where assets
  land; `prompts_dir` is **not** modeled as a `Workspace` property in this
  slice either — see Design Decision 6 (it stays a caller-supplied
  `Path` parameter, mirroring `manual_dir`/`extracted_dir` being plain
  `config["paths"][...]` values rather than `Workspace` properties).
- `tests/integration/test_review_service.py` / `test_evidence_service.py`
  conventions confirmed: `Workspace(documents_dir=tmp_path / "documents",
  templates_dir=tmp_path / "templates")` fixture, real adapters
  (`JsonSectionRepository(workspace)`, `JsonEvidenceRepository()`), no
  mocks; tests write fixture files directly via `_write_section`-style
  helpers or `repository.write_manifest(...)`, then assert on service
  output. This slice's integration tests follow the identical pattern.
- `FilesystemSourceRepository` (`src/docs/infrastructure/persistence/filesystem_source_repository.py`)
  is the established naming precedent for a filesystem-backed adapter
  whose Protocol is named `XRepository` without a `Json`/`Filesystem`
  prefix collision — confirms `FilesystemAssetRepository` (not
  `JsonAssetRepository`) is the right adapter name for Design Decision 1,
  since asset I/O is `shutil.copy2`/glob/`unlink`, not JSON.

## Design decisions

1. **A new `AssetRepository` Protocol + `FilesystemAssetRepository` adapter
   + new `AssetService` are required; assets are document-scoped.**
   `add_asset`/`list_assets`/`remove_asset` need `shutil.copy2`, `Path.glob`,
   and `Path.unlink` — none of which `EvidenceRepository` (manifest/text
   I/O), `SectionRepository` (frontmatter-aware section I/O), or
   `SourceRepository` (markdown globbing + subprocess) expose, and forcing
   this shape onto any of them would be a port-purpose mismatch (each
   existing port models a distinct I/O concern; assets are a fourth,
   distinct one: "manage opaque binary attachments"). Decision: add
   `AssetRepository` Protocol (`domain/ports/asset_repository.py`) with
   `copy_file(src: Path, dest: Path) -> None`, `glob_docx(directory: Path)
   -> list[Path]`, `file_exists(path: Path) -> bool`,
   `is_file(path: Path) -> bool`, `remove_file(path: Path) -> None`,
   `ensure_dir(path: Path) -> None` — thin I/O primitives mirroring
   `SourceRepository`'s shape (no business logic in the Protocol).
   Implement `FilesystemAssetRepository`
   (`infrastructure/persistence/filesystem_asset_repository.py`, naming
   parity with `FilesystemSourceRepository`, NOT `JsonAssetRepository` —
   confirmed: assets are never JSON-shaped). Add a new `AssetService`
   (`application/asset.py`) depending only on `AssetRepository`, mirroring
   `CollectionService`'s single-new-port-per-service pattern from Slice 7.
   **Assets are document-scoped** (`workspace.doc_root(doc_id) / "assets"`),
   not workspace-shared: every other per-document concept in this codebase
   (`sections/`, soon `_context/`) lives under `doc_root(doc_id)`, and
   legacy's own `assets_dir` is read from `config["paths"]["assets_dir"]` —
   a *per-document* config dict in legacy's harness (one config per
   tesina/document). Treating assets as workspace-shared (like
   `templates_dir`, which holds *template definitions* reused *across*
   documents) would conflate "thing every document might reuse" with
   "thing that belongs to one document's cover/appendix," which is
   document-specific content. Decision: `AssetService` methods take
   `doc_id: str` and resolve `workspace.doc_root(doc_id) / "assets"`
   internally (via a `Workspace.assets_dir(doc_id)` helper — see below),
   exactly like `SectionRepository` resolves `sections/` under
   `doc_root(doc_id)`.

   **`Workspace` grows one new method**: `assets_dir(doc_id: str) -> Path`
   returning `self.doc_root(doc_id) / "assets"`, mirroring no existing
   precedent exactly (today only `JsonSectionRepository._sections_dir`
   does this kind of doc-scoped subdirectory resolution, and it's private
   to that adapter) — but since `AssetService`/`FilesystemAssetRepository`
   need the same `doc_root(doc_id) / "assets"` arithmetic that
   `JsonSectionRepository._sections_dir` does for `sections/`, and
   `Workspace` already owns `doc_root`, adding `assets_dir` to `Workspace`
   (public, unlike `_sections_dir`) is the natural extension point — it's
   pure path arithmetic with zero I/O, appropriate for the pure
   `Workspace` dataclass. `FilesystemAssetRepository` methods take the
   already-resolved `Path` (asset's full path), not `doc_id` — keeping the
   adapter as dumb I/O, consistent with `JsonSectionRepository` taking
   `doc_id` and resolving paths itself vs. `JsonEvidenceRepository` taking
   already-resolved `Path` values. Since `AssetRepository`'s shape is
   closer to `EvidenceRepository`'s (arbitrary path-in, no `doc_id`-aware
   resolution baked into the Protocol), `AssetService` resolves
   `workspace.assets_dir(doc_id)` itself and passes concrete `Path` values
   into `AssetRepository` methods.

2. **`pack_context`/`pack_context_document` land on a new
   `ContextPackService`, composing `SectionRepository` +
   `EvidenceRepository` directly (not composing `EvidenceService`/
   `ReviewService`).** This service needs: section/contract lookup (via
   `Template`, no port), prompt file reads + Fact Ledger file read (via
   `EvidenceRepository.file_exists`/`read_text`), manifest facts (via
   `EvidenceService.load_manifest_facts` — see caveat below), current
   draft body (via `SectionRepository.read_section`), and a single-section
   review (via the new `ReviewService.review_section`, Design Decision 3),
   plus `ReviewService.review_document` for the whole-document pack.
   This *appears* to need four collaborators, which would violate the
   "single new port per service" discipline established in Slices 4–8.
   Resolving this: `ContextPackService` is **the first service in this
   codebase to legitimately depend on other application services, not
   just ports** — and that is the correct shape here, not a shortcut. The
   reasoning: `load_manifest_facts`/`review_document`/`review_section`
   are not raw I/O operations a Protocol could express directly — they are
   already-assembled *business results* (deduped fact lists, structured
   `ReviewResult`s) that two other services already know how to produce
   from raw ports. Re-deriving "read 3 manifests, dedupe" or "loop
   sections, call `review_section_text`" a second time inside
   `ContextPackService` would duplicate `EvidenceService`/`ReviewService`
   logic outright — the exact anti-pattern Slice 7/8's "grow the existing
   service when the shape fits" precedent was designed to prevent, just
   one layer up (service-reuse instead of port-reuse). Decision:
   `ContextPackService.__init__(self, section_repository: SectionRepository,
   evidence_repository: EvidenceRepository, evidence_service: EvidenceService,
   review_service: ReviewService)`. This is a deliberate, documented
   precedent-setter for this codebase (no prior service composes another
   service) — flagged explicitly for the reviewer: if this is rejected,
   the fallback is duplicating `load_manifest_facts`'s 3-manifest-read loop
   and `review_section_text`'s kwargs-threading loop directly inside
   `ContextPackService` against `EvidenceRepository`/`SectionRepository`
   only, which avoids the new "service depends on service" shape at the
   cost of two near-duplicate logic blocks. This plan's recommendation is
   to compose services, not duplicate logic — but this is the single
   highest-judgment call in this slice and should be confirmed, not
   silently accepted.

3. **`ReviewService` grows a new `review_section` method** for the
   single-file review legacy's `pack_context` calls (`review_section(
   section_path, config=config, strict=False)`). Confirmed by direct
   reading: this is NOT the same as `domain.rules.review_section_text`
   (which legacy's *own* `review_section`, lines 1445–1499, already wraps
   and which is already ported — see Slice 8 Design Decision 0/1). What's
   missing is the *orchestration* `review_document`'s loop body performs
   for one section: resolve `section_id` from metadata-or-path-inference,
   resolve `contract` from `template.section_contracts`, call
   `review_section_text` with the full kwargs bundle, wrap results in a
   `ReviewResult`. Decision: add
   `ReviewService.review_section(self, doc_id: str, template: Template,
   section_id: str, strict: bool = False, *, excluded_terms: dict[str, str],
   is_policy_file: bool, first_person_patterns: list[str],
   subjective_terms: list[str], secret_patterns: list[str],
   scope_term: str = "", scope_focus: str = "") -> ReviewResult`, threading
   the identical kwargs `review_document` already threads, and internally
   doing exactly what `review_document`'s loop body does for the single
   matching `section` — read section via `self.repository.read_section`,
   resolve `section_id`/`contract`, call `review_section_text`, return
   `ReviewResult(issues)` (no filename-prefixing on messages, since there's
   only one file and no cross-section context to disambiguate — legacy's
   own single-file `review_section` does not prefix messages either,
   confirmed by re-reading lines 1445–1499 referenced in Slice 8's plan).
   This does NOT duplicate `review_document`'s loop logic at the
   `review_section_text` call site — it duplicates roughly 15 lines of
   orchestration glue (section lookup + contract resolution + one
   `review_section_text` call), which is an acceptable, explicit
   trade-off versus extracting a shared private helper purely for two
   callers; if a third caller emerges later, extracting
   `_review_one_section(...)` into a private method both `review_document`
   and `review_section` call becomes justified — not yet.

4. **`_keyword_set`/`_matches_keywords` are pure, added to
   `domain/markdown_text.py`.** Both build directly on
   `normalize_author_key` (already in that file) and operate purely on
   strings/sets with no I/O — the same "generic string utility adjacent to
   `normalize_author_key`" category as `dedupe_strings`/`normalize_for_sort`,
   which already live there. Verified purity by tracing both functions:
   `_keyword_set` only calls `normalize_author_key` + `str.split()` + set
   building; `_matches_keywords` only calls `normalize_author_key` +
   substring `in` checks. No file/network/clock access in either. The
   `_matches_keywords` empty-keywords-matches-everything short-circuit
   (`if not keywords: return True`) is preserved exactly — this matters
   because `pack_context`'s `keywords = _keyword_set(title, section_id,
   " ".join(required))` can legitimately be empty (e.g., a section with no
   title words ≥4 chars and no `required_content`), in which case *every*
   ledger line and *every* manifest fact passes the filter rather than
   none — this is almost certainly intentional (a contract-less section
   gets the full ledger/evidence dump rather than nothing), but is flagged
   here explicitly since an inverted reading ("no keywords = nothing
   matches") would silently break context packs for thin contracts.

5. **`context_pack_dir` becomes `SectionRepository.context_pack_path`,
   mirroring `write_proposal_section`'s precedent from Slice 8.**
   `context_pack_dir(config) = sections_dir / "_context"` is the same
   "well-known subdirectory under the sections tree" shape Slice 8 already
   solved for `_proposals/` via `write_proposal_section`. Decision: add
   two methods to `SectionRepository`:
   `context_pack_path(doc_id: str, order: int, section_id: str) -> Path`
   (returns `sections_dir / "_context" / f"{order:03d}-{section_id}.context.md"`)
   and `document_context_pack_path(doc_id: str) -> Path` (returns
   `sections_dir / "_context" / "000-document.context.md"`), plus a write
   method `write_context_pack(doc_id, path: Path, content: str) -> Path`
   that does `path.parent.mkdir(parents=True, exist_ok=True)` then
   `path.write_text(...)`, mirroring `write_proposal_section`'s shape
   (mkdir-then-write, returns the path). This keeps `SectionRepository`
   as the sole owner of "where things live under the sections tree,"
   consistent with Slice 8's reasoning for `_proposals/`. **Open question
   for implementer/reviewer**: should `context_pack_path`/
   `document_context_pack_path` be two separate methods, or one method
   `context_pack_path(doc_id, order: int | None, section_id: str | None)`
   with `order=None` meaning "document-level pack, ignore section_id"? This
   plan recommends two separate methods (clearer call sites, no sentinel
   `None`-means-special-case argument, consistent with how
   `write_section`/`write_proposal_section` are already two separate
   methods rather than one with a `proposal: bool` flag) — flagged as a
   judgment call, not a forced conclusion.

6. **`read_prompt`/the Fact Ledger file read need no new port method —
   `EvidenceRepository.file_exists`/`read_text` already cover this fully.**
   Confirmed by re-reading the Protocol directly: both methods exist today
   and are already used elsewhere (`EvidenceService.build_rules`,
   `CollectionService.collect_sources`) for the identical "check exists,
   then read text" shape `read_prompt` needs. Decision: `read_prompt` is
   ported as a small method on `ContextPackService` (not a free function,
   not on `EvidenceService` — it has no callers outside this slice's two
   functions, so it doesn't need to be a general-purpose capability),
   taking `prompts_dir: Path` as an explicit parameter — consistent with
   this codebase's "pass paths in via `config['paths'][...]`, never invent
   a typed `Config`" convention (confirmed absent through Slice 7/8, and
   reconfirmed by reading `application/evidence.py`/`application/review.py`
   directly in this slice's research). `ContextPackService.pack_context`/
   `pack_context_document` resolve `prompts_dir = Path(config["paths"]
   ["prompts_dir"])` and `fact_ledger_path = Path(config["paths"]
   ["fact_ledger"])` themselves, then call `self.evidence_repository
   .file_exists(...)`/`read_text(...)` directly — no new Protocol method.

7. **Out-of-scope confirmation** (see full list below): `section_by_id`/
   `section_path_for`/`_as_posix` are not re-ported (Decision per Slice 8
   precedent); everything from Slice 10+ untouched.

## Task breakdown

### Task 1 — Pure domain functions: `_keyword_set` / `_matches_keywords`

**Files to create/modify:**
- Modify `src/docs/domain/markdown_text.py` — add `keyword_set(*texts: str)
  -> set[str]` and `matches_keywords(text: str, keywords: set[str]) ->
  bool` (public names, dropping the leading underscore since this codebase
  has no precedent for porting a private legacy helper as a private
  module-level function when it crosses module boundaries as a reusable
  utility — `dedupe_strings`/`normalize_for_sort` are public despite no
  legacy underscore ambiguity; here legacy's leading underscore signals
  "private within `tesina_harness.py`," not "private API," so dropping it
  on the port is consistent, not a deviation requiring sign-off).
- Modify `tests/unit/domain/test_markdown_text.py`.

**Verbatim legacy reference:** `_keyword_set` (1789–1796),
`_matches_keywords` (1799–1803).

**Planned implementation:**

```python
# additions to src/docs/domain/markdown_text.py

def keyword_set(*texts: str) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        normalized = normalize_author_key(text)
        for token in normalized.split():
            if len(token) >= 4:
                tokens.add(token)
    return tokens


def matches_keywords(text: str, keywords: set[str]) -> bool:
    if not keywords:
        return True
    normalized = normalize_author_key(text)
    return any(keyword in normalized for keyword in keywords)
```

**Planned test code (representative):**

```python
# additions to tests/unit/domain/test_markdown_text.py
from docs.domain.markdown_text import keyword_set, matches_keywords


def test_keyword_set_collects_tokens_of_length_4_or_more():
    assert keyword_set("Resultados del Proyecto") == {"resultados", "proyecto"}


def test_keyword_set_drops_short_tokens():
    assert "del" not in keyword_set("Resultados del Proyecto")


def test_keyword_set_merges_tokens_across_multiple_texts():
    result = keyword_set("Introducción", "alcance")
    assert {"introduccion", "alcance"} <= result


def test_matches_keywords_empty_keywords_matches_everything():
    assert matches_keywords("cualquier texto", set()) is True


def test_matches_keywords_true_when_keyword_substring_present():
    assert matches_keywords("- El alcance del proyecto es claro", {"alcance"}) is True


def test_matches_keywords_false_when_no_keyword_present():
    assert matches_keywords("- Texto sin relación", {"alcance"}) is False
```

**Expected test count:** ~7 new unit tests.

---

### Task 2 — Port + adapter: `AssetRepository` / `FilesystemAssetRepository`

**Files to create/modify:**
- Modify `src/docs/domain/workspace.py` — add `assets_dir(self, doc_id: str)
  -> Path` returning `self.doc_root(doc_id) / "assets"`.
- Create `src/docs/domain/ports/asset_repository.py`.
- Create `src/docs/infrastructure/persistence/filesystem_asset_repository.py`.
- Modify `tests/unit/domain/test_workspace.py` (add `assets_dir` case).
- Create `tests/unit/infrastructure/test_filesystem_asset_repository.py`.

**Verbatim legacy reference:** `assets_dir`/`asset_path` (1819–1825) for
the path-arithmetic half (now split between `Workspace.assets_dir` and
`AssetService.asset_path`, see Task 3); the I/O primitives below come from
`add_asset`/`list_assets`/`remove_asset` (1828–1850).

**Planned implementation:**

```python
# src/docs/domain/ports/asset_repository.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AssetRepository(Protocol):
    def ensure_dir(self, path: Path) -> None: ...
    def is_file(self, path: Path) -> bool: ...
    def copy_file(self, src: Path, dest: Path) -> None: ...
    def glob_docx(self, directory: Path) -> list[Path]: ...
    def remove_file(self, path: Path) -> None: ...
    def file_exists(self, path: Path) -> bool: ...
```

```python
# src/docs/infrastructure/persistence/filesystem_asset_repository.py
from __future__ import annotations

import shutil
from pathlib import Path


class FilesystemAssetRepository:
    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def is_file(self, path: Path) -> bool:
        return path.exists() and path.is_file()

    def copy_file(self, src: Path, dest: Path) -> None:
        shutil.copy2(src, dest)

    def glob_docx(self, directory: Path) -> list[Path]:
        return sorted(directory.glob("*.docx"))

    def remove_file(self, path: Path) -> None:
        if path.exists():
            path.unlink()

    def file_exists(self, path: Path) -> bool:
        return path.exists()
```

```python
# addition to src/docs/domain/workspace.py
def assets_dir(self, doc_id: str) -> Path:
    return self.doc_root(doc_id) / "assets"
```

**Planned test code (representative):**

```python
# additions to tests/unit/domain/test_workspace.py
def test_assets_dir_is_under_doc_root(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    assert workspace.assets_dir("doc-1") == workspace.doc_root("doc-1") / "assets"
```

```python
# tests/unit/infrastructure/test_filesystem_asset_repository.py
from pathlib import Path

from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


def test_copy_file_copies_bytes_and_metadata(tmp_path: Path):
    repo = FilesystemAssetRepository()
    src = tmp_path / "source.docx"
    src.write_bytes(b"docx-bytes")
    dest = tmp_path / "dest.docx"
    repo.copy_file(src, dest)
    assert dest.read_bytes() == b"docx-bytes"


def test_glob_docx_returns_sorted_docx_files_only(tmp_path: Path):
    repo = FilesystemAssetRepository()
    (tmp_path / "b.docx").write_bytes(b"")
    (tmp_path / "a.docx").write_bytes(b"")
    (tmp_path / "c.txt").write_bytes(b"")
    assert [p.name for p in repo.glob_docx(tmp_path)] == ["a.docx", "b.docx"]


def test_remove_file_is_noop_when_absent(tmp_path: Path):
    repo = FilesystemAssetRepository()
    repo.remove_file(tmp_path / "missing.docx")  # must not raise


def test_remove_file_deletes_existing_file(tmp_path: Path):
    repo = FilesystemAssetRepository()
    path = tmp_path / "x.docx"
    path.write_bytes(b"")
    repo.remove_file(path)
    assert not path.exists()


def test_is_file_false_for_directory(tmp_path: Path):
    repo = FilesystemAssetRepository()
    assert repo.is_file(tmp_path) is False
```

**Expected test count:** ~6 (1 `Workspace` + 5 adapter).

---

### Task 3 — Application layer: `AssetService`

**Files to create/modify:**
- Create `src/docs/application/asset.py`.
- Create `tests/integration/test_asset_service.py`.

**Verbatim legacy reference:** `asset_path` (1822–1825), `add_asset`
(1828–1837), `list_assets` (1840–1844), `remove_asset` (1847–1850).

**Planned implementation:**

```python
# src/docs/application/asset.py
from __future__ import annotations

from pathlib import Path

from docs.domain.ports.asset_repository import AssetRepository
from docs.domain.workspace import Workspace


class AssetService:
    def __init__(self, repository: AssetRepository, workspace: Workspace) -> None:
        self.repository = repository
        self.workspace = workspace

    def asset_path(self, doc_id: str, name: str) -> Path:
        safe = name if name.lower().endswith(".docx") else f"{name}.docx"
        return self.workspace.assets_dir(doc_id) / safe

    def add_asset(self, doc_id: str, src: str, name: str = "") -> Path:
        source = Path(src)
        if not self.repository.is_file(source):
            raise FileNotFoundError(f"No existe el archivo a adjuntar: {source}")
        if source.suffix.lower() != ".docx":
            raise ValueError(f"Sólo se admiten archivos .docx como asset: {source.name}")
        target_name = name or source.stem
        target = self.asset_path(doc_id, target_name)
        self.repository.ensure_dir(target.parent)
        self.repository.copy_file(source, target)
        return target

    def list_assets(self, doc_id: str) -> list[str]:
        directory = self.workspace.assets_dir(doc_id)
        if not self.repository.file_exists(directory):
            return []
        return [path.stem for path in self.repository.glob_docx(directory)]

    def remove_asset(self, doc_id: str, name: str) -> None:
        target = self.asset_path(doc_id, name)
        self.repository.remove_file(target)
```

> Parity note: legacy's `add_asset` checks `source.exists() and
> source.is_file()` inline; the port's `is_file(path)` already composes
> both checks (see Task 2's `FilesystemAssetRepository.is_file`), so
> `AssetService.add_asset` calling `self.repository.is_file(source)` is
> behaviorally identical, not a simplification that changes outcomes.

**Planned test code (representative):**

```python
# tests/integration/test_asset_service.py
from pathlib import Path

import pytest

from docs.application.asset import AssetService
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> AssetService:
    return AssetService(FilesystemAssetRepository(), workspace)


def test_add_asset_copies_file_and_appends_docx_suffix(tmp_path, workspace, service):
    source = tmp_path / "cover.docx"
    source.write_bytes(b"docx-bytes")
    target = service.add_asset("doc-1", str(source), name="portada")
    assert target == workspace.assets_dir("doc-1") / "portada.docx"
    assert target.read_bytes() == b"docx-bytes"


def test_add_asset_defaults_name_to_source_stem(tmp_path, workspace, service):
    source = tmp_path / "anexo-a.docx"
    source.write_bytes(b"x")
    target = service.add_asset("doc-1", str(source))
    assert target.name == "anexo-a.docx"


def test_add_asset_raises_when_source_missing(tmp_path, service):
    with pytest.raises(FileNotFoundError):
        service.add_asset("doc-1", str(tmp_path / "missing.docx"))


def test_add_asset_raises_when_source_is_not_docx(tmp_path, service):
    source = tmp_path / "cover.pdf"
    source.write_bytes(b"x")
    with pytest.raises(ValueError):
        service.add_asset("doc-1", str(source))


def test_list_assets_returns_empty_list_when_directory_absent(service):
    assert service.list_assets("doc-1") == []


def test_list_assets_returns_stems_sorted(tmp_path, workspace, service):
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    service.add_asset("doc-1", str(source), name="b-anexo")
    service.add_asset("doc-1", str(source), name="a-portada")
    assert service.list_assets("doc-1") == ["a-portada", "b-anexo"]


def test_remove_asset_deletes_existing_asset(tmp_path, workspace, service):
    source = tmp_path / "src.docx"
    source.write_bytes(b"x")
    service.add_asset("doc-1", str(source), name="portada")
    service.remove_asset("doc-1", "portada")
    assert service.list_assets("doc-1") == []


def test_remove_asset_is_noop_when_asset_absent(service):
    service.remove_asset("doc-1", "no-existe")  # must not raise
```

**Expected test count:** ~8 integration tests.

---

### Task 4 — Port growth: `SectionRepository` context-pack path/write methods

**Files to create/modify:**
- Modify `src/docs/domain/ports/section_repository.py`.

**Rationale:** Confirmed by direct inspection, the current 6-method
`SectionRepository` Protocol has no concept of the `_context/` directory.
Per Design Decision 5, add three methods.

**Planned implementation:**

```python
# additions to src/docs/domain/ports/section_repository.py
class SectionRepository(Protocol):
    ...  # existing 6 methods unchanged
    def context_pack_path(self, doc_id: str, order: int, section_id: str) -> Path: ...
    def document_context_pack_path(self, doc_id: str) -> Path: ...
    def write_context_pack(self, path: Path, content: str) -> Path: ...
```

**Expected test count:** 0 (bare Protocol addition, self-reviewed per
Slice 4–8 Task-2-style precedent — behavior tested at the adapter layer in
Task 5).

---

### Task 5 — Infrastructure: `JsonSectionRepository` context-pack methods

**Files to create/modify:**
- Modify `src/docs/infrastructure/persistence/json_section_repository.py`.
- Modify `tests/unit/infrastructure/test_json_section_repository.py`.

**Planned implementation:**

```python
# additions to src/docs/infrastructure/persistence/json_section_repository.py
def context_pack_path(self, doc_id: str, order: int, section_id: str) -> Path:
    return self._sections_dir(doc_id) / "_context" / f"{order:03d}-{section_id}.context.md"

def document_context_pack_path(self, doc_id: str) -> Path:
    return self._sections_dir(doc_id) / "_context" / "000-document.context.md"

def write_context_pack(self, path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
```

**Planned test code (representative):**

```python
# additions to tests/unit/infrastructure/test_json_section_repository.py
def test_context_pack_path_under_context_subdir(tmp_path):
    repo = JsonSectionRepository(workspace_for(tmp_path))
    path = repo.context_pack_path("doc1", 3, "intro")
    assert path.name == "003-intro.context.md"
    assert path.parent.name == "_context"


def test_document_context_pack_path_is_000_document(tmp_path):
    repo = JsonSectionRepository(workspace_for(tmp_path))
    path = repo.document_context_pack_path("doc1")
    assert path.name == "000-document.context.md"


def test_write_context_pack_creates_dir_and_writes_content(tmp_path):
    repo = JsonSectionRepository(workspace_for(tmp_path))
    target = repo.context_pack_path("doc1", 1, "intro")
    result = repo.write_context_pack(target, "contenido")
    assert result == target
    assert target.read_text(encoding="utf-8") == "contenido"
```

> Implementer note: `workspace_for(tmp_path)` denotes whatever
> `Workspace`-construction helper/fixture this test file already uses
> (check the existing file before assuming a name — not re-derived here
> to avoid guessing at a fixture this plan's author did not directly
> read in full).

**Expected test count:** ~3.

---

### Task 6 — Application layer: `ReviewService.review_section`

**Files to create/modify:**
- Modify `src/docs/application/review.py`.
- Modify `tests/integration/test_review_service.py`.

**Verbatim legacy reference:** orchestration shape mirrors
`review_document`'s loop body (`src/docs/application/review.py:48-85`,
this codebase's own already-ported code, not a new legacy block — see
Design Decision 3). The legacy *call site* this slice ports is
`pack_context`'s `review_section(section_path, config=config,
strict=False)` (line 1908).

**Planned implementation:**

```python
# addition to src/docs/application/review.py
def review_section(
    self,
    doc_id: str,
    template: Template,
    section_id: str,
    strict: bool = False,
    *,
    excluded_terms: dict[str, str],
    is_policy_file: bool,
    first_person_patterns: list[str],
    subjective_terms: list[str],
    secret_patterns: list[str],
    scope_term: str = "",
    scope_focus: str = "",
) -> ReviewResult:
    section = next((s for s in template.sections if s.id == section_id), None)
    if section is None:
        raise FileNotFoundError(f"No existe sección: {section_id}")
    if not self.repository.section_exists(doc_id, section.order, section.id):
        path = self.repository.section_path(doc_id, section.order, section.id)
        raise FileNotFoundError(f"No existe la sección a revisar: {path}")

    metadata, body = self.repository.read_section(doc_id, section.order, section.id)
    section_path = self.repository.section_path(doc_id, section.order, section.id)
    resolved_section_id = metadata.get("section_id") or infer_section_id_from_path(section_path)
    contract = template.section_contracts.get(resolved_section_id, SectionContract())

    issues = review_section_text(
        body,
        metadata,
        resolved_section_id,
        contract,
        template,
        strict,
        excluded_terms=excluded_terms,
        is_policy_file=is_policy_file,
        first_person_patterns=first_person_patterns,
        subjective_terms=subjective_terms,
        secret_patterns=secret_patterns,
        scope_term=scope_term,
        scope_focus=scope_focus,
    )
    return ReviewResult([Issue(issue.severity, issue.message, code=issue.code) for issue in issues])
```

**Planned test code (representative):**

```python
# additions to tests/integration/test_review_service.py
def test_review_section_returns_issues_for_existing_section(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="Sin titulo principal.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_section(
        "doc-1", template, "introduccion",
        excluded_terms={}, is_policy_file=False, first_person_patterns=[],
        subjective_terms=[], secret_patterns=[],
    )
    codes = [issue.code for issue in result.issues]
    assert "structure.missing_title" in codes


def test_review_section_returns_no_issues_for_clean_section(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    _write_section(
        workspace, "doc-1", 1, "introduccion",
        body="# Introducción\n\nProblema, objetivo, metodología, resultados y conclusiones presentes.\n",
        metadata={"section_id": "introduccion"},
    )
    result = service.review_section(
        "doc-1", template, "introduccion",
        excluded_terms={}, is_policy_file=False, first_person_patterns=[],
        subjective_terms=[], secret_patterns=[],
    )
    assert result.issues == []


def test_review_section_raises_when_section_file_missing(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.review_section(
            "doc-1", template, "introduccion",
            excluded_terms={}, is_policy_file=False, first_person_patterns=[],
            subjective_terms=[], secret_patterns=[],
        )


def test_review_section_raises_when_section_id_unknown(workspace, service):
    template = _template(sections=[Section(id="introduccion", title="Introducción", order=1, required=True)])
    with pytest.raises(FileNotFoundError):
        service.review_section(
            "doc-1", template, "no-existe",
            excluded_terms={}, is_policy_file=False, first_person_patterns=[],
            subjective_terms=[], secret_patterns=[],
        )
```

**Expected test count:** ~4 integration tests.

---

### Task 7 — Application layer: `ContextPackService.pack_context`

**Files to create/modify:**
- Create `src/docs/application/context_pack.py`.
- Create `tests/integration/test_context_pack_service.py`.

**Verbatim legacy reference:** `pack_context` (1853–1928), composing
`_keyword_set`/`_matches_keywords` (Task 1), `read_prompt` (Design
Decision 6), `load_manifest_facts` (already on `EvidenceService`),
`review_section` (Task 6).

**Planned implementation:**

```python
# src/docs/application/context_pack.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.markdown_text import keyword_set, matches_keywords
from docs.domain.models.template import SectionContract, Template
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository

_SECTION_PROMPT_NAMES = ["section-planner.md", "section-author.md", "section-reviewer.md"]
_APA_PROMPT_NAME = "apa7-citation-auditor.md"
_MAX_MANIFEST_FACTS = 40


class ContextPackService:
    def __init__(
        self,
        section_repository: SectionRepository,
        evidence_repository: EvidenceRepository,
        evidence_service: EvidenceService,
        review_service: ReviewService,
    ) -> None:
        self.section_repository = section_repository
        self.evidence_repository = evidence_repository
        self.evidence_service = evidence_service
        self.review_service = review_service

    def _read_prompt(self, prompts_dir: Path, name: str) -> str:
        path = prompts_dir / name
        if self.evidence_repository.file_exists(path):
            return self.evidence_repository.read_text(path).strip()
        return ""

    def pack_context(
        self,
        doc_id: str,
        template: Template,
        section_id: str,
        config: dict[str, Any],
        *,
        review_kwargs: dict[str, Any],
    ) -> Path:
        section = next(s for s in template.sections if s.id == section_id)
        contract = template.section_contracts.get(section_id, SectionContract())
        required = contract.required_content
        apa_required = contract.apa_required
        keywords = keyword_set(section.title, section_id, " ".join(required))

        lines: list[str] = [
            f"# Context pack — {section.title}",
            "",
            "_Paquete generado por el arnés. Es el contexto curado para redactar esta sección. "
            "Redacta con `prompts/section-author.md`, luego corre `review-section "
            f"{section_id} --strict --json` y corrige hasta quedar en verde._",
            "",
            "## Contrato de sección",
            "",
            "```json",
            json.dumps(contract.model_dump(), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Checklist de contenido obligatorio",
            "",
        ]
        if required:
            lines.extend(f"- [ ] {item}" for item in required)
        else:
            lines.append("- (Sin `required_content` declarado.)")
        lines.extend(["", f"APA 7 requerido: {'sí' if apa_required else 'no'}.", ""])

        prompts_dir = Path(config["paths"]["prompts_dir"])
        prompt_names = list(_SECTION_PROMPT_NAMES)
        if apa_required:
            prompt_names.append(_APA_PROMPT_NAME)
        lines.extend(["## Prompts del rol", ""])
        for name in prompt_names:
            content = self._read_prompt(prompts_dir, name)
            if content:
                lines.extend([f"### {name}", "", content, ""])

        ledger_path = Path(config["paths"]["fact_ledger"])
        if self.evidence_repository.file_exists(ledger_path):
            ledger_text = self.evidence_repository.read_text(ledger_path)
            ledger_lines = [
                line.strip()
                for line in ledger_text.splitlines()
                if line.strip().startswith("- ") and matches_keywords(line, keywords)
            ]
            if ledger_lines:
                lines.extend(["## Hechos relevantes del ledger", ""])
                lines.extend(ledger_lines)
                lines.append("")

        manifest_facts = [
            fact
            for fact in self.evidence_service.load_manifest_facts(config)
            if matches_keywords(f"{fact.get('claim', '')} {fact.get('title', '')}", keywords)
        ]
        if manifest_facts:
            lines.extend(["## Evidencia relevante (manifests)", ""])
            for fact in manifest_facts[:_MAX_MANIFEST_FACTS]:
                claim = fact.get("claim") or fact.get("title") or ""
                classification = fact.get("classification", "")
                source = fact.get("source") or fact.get("url") or ""
                suffix = f" — {source}" if source else ""
                tag = f"[{classification}] " if classification else ""
                lines.append(f"- {tag}{claim}{suffix}")
            lines.append("")

        if self.section_repository.section_exists(doc_id, section.order, section.id):
            _metadata, body = self.section_repository.read_section(doc_id, section.order, section.id)
            review = self.review_service.review_section(
                doc_id, template, section_id, strict=False, **review_kwargs
            )
            lines.extend(["## Borrador actual", "", "```markdown", body.strip(), "```", ""])
            lines.extend(["## Hallazgos actuales (review-section)", ""])
            if review.issues:
                for issue in review.issues:
                    code = f" ({issue.code})" if issue.code else ""
                    lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
            else:
                lines.append("- Sin hallazgos.")
            lines.append("")
        else:
            lines.extend(
                [
                    "## Borrador actual",
                    "",
                    f"_Aún no existe; ejecuta `build-section {section_id}` para generar el scaffold inicial._",
                    "",
                ]
            )

        out_path = self.section_repository.context_pack_path(doc_id, section.order, section.id)
        return self.section_repository.write_context_pack(out_path, "\n".join(lines))
```

> **Flagged for reviewer — `contract.model_dump()` vs. legacy's raw
> `json.dumps(contract, ...)`:** legacy's `contract` is a plain dict
> straight from `config["section_contracts"][section_id]` (or `{}`), so
> `json.dumps(contract, ...)` serializes exactly what's in the config file.
> This codebase's `contract` is a **typed** `SectionContract` (Pydantic,
> `extra="allow"`); `contract.model_dump()` serializes the typed fields
> **plus** any `extra` keys, in **declared-field order, not necessarily
> matching the original JSON's key order** (though `sort_keys=True`
> neutralizes ordering either way). This should be behaviorally equivalent
> for any contract whose JSON shape was already covered by
> `SectionContract`'s typed fields, but if a legacy contract JSON has
> exotic keys not captured by any typed field, `extra="allow"` should
> still surface them via `model_dump()` — **verify this against a real
   fixture contract with non-standard keys before treating it as settled.**
   Also note: this changes the rendered Context Pack's contract JSON
   block's content type from "whatever was literally in the config dict"
   to "whatever Pydantic considers the contract's full shape," which is a
   meaningful behavior question (not just a refactor) — flagged
   explicitly, not silently assumed equivalent.
>
> **Flagged for reviewer — `review_kwargs` bundle:** `pack_context`'s
> signature takes a `review_kwargs: dict[str, Any]` bundle rather than the
> six individual `excluded_terms`/`is_policy_file`/`first_person_patterns`/
> `subjective_terms`/`secret_patterns`/`scope_term`/`scope_focus` keyword
> arguments `review_document`/`review_section` both require. This is a
> deliberate ergonomics choice to avoid `pack_context` growing a 7-keyword
> signature on top of its own `doc_id`/`template`/`section_id`/`config`
> parameters, but it is **inconsistent** with how `review_document`/
   `review_section` themselves expose those same keywords explicitly,
   un-bundled. Flagged as a judgment call: the alternative is
   `pack_context` repeating the same 7 keyword-only parameters
   `review_section` has, which is more consistent but verbose. Pick one
   and apply it consistently before implementation — do not let this
   plan's choice be treated as final without confirmation.

**Planned test code (representative; implementer fills in full coverage
for each `## ` section the pack can include/omit):**

```python
# tests/integration/test_context_pack_service.py
from pathlib import Path

import pytest

from docs.application.context_pack import ContextPackService
from docs.application.evidence import EvidenceService
from docs.application.review import ReviewService
from docs.domain.models.template import Section, SectionContract, Template
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository

_REVIEW_KWARGS = dict(
    excluded_terms={}, is_policy_file=False, first_person_patterns=[],
    subjective_terms=[], secret_patterns=[],
)


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")


@pytest.fixture
def service(workspace: Workspace) -> ContextPackService:
    section_repo = JsonSectionRepository(workspace)
    evidence_repo = JsonEvidenceRepository()
    return ContextPackService(
        section_repo, evidence_repo, EvidenceService(evidence_repo), ReviewService(section_repo)
    )


def _template() -> Template:
    return Template(
        type="tesina", title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract(required_content=["alcance"])},
    )


def _config(tmp_path: Path) -> dict:
    return {
        "paths": {
            "prompts_dir": str(tmp_path / "prompts"),
            "fact_ledger": str(tmp_path / "00-fact-ledger.md"),
            "source_manifest": str(tmp_path / "source.json"),
            "issues_manifest": str(tmp_path / "issues.json"),
            "code_evidence_manifest": str(tmp_path / "code-evidence.json"),
        },
    }


def test_pack_context_includes_required_content_checklist(tmp_path, workspace, service):
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "- [ ] alcance" in text


def test_pack_context_writes_under_context_subdir(tmp_path, workspace, service):
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    assert out_path == workspace.doc_root("doc-1") / "sections" / "_context" / "001-introduccion.context.md"


def test_pack_context_includes_role_prompt_content_when_present(tmp_path, workspace, service):
    prompts_dir = Path(tmp_path / "prompts")
    prompts_dir.mkdir()
    (prompts_dir / "section-author.md").write_text("Redacta con rigor.", encoding="utf-8")
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    assert "Redacta con rigor." in out_path.read_text(encoding="utf-8")


def test_pack_context_includes_apa_prompt_only_when_apa_required(tmp_path, workspace, service):
    template = Template(
        type="tesina", title="Tesina",
        sections=[Section(id="introduccion", title="Introducción", order=1, required=True)],
        section_contracts={"introduccion": SectionContract(apa_required=True)},
    )
    prompts_dir = Path(tmp_path / "prompts")
    prompts_dir.mkdir()
    (prompts_dir / "apa7-citation-auditor.md").write_text("Audita citas APA.", encoding="utf-8")
    out_path = service.pack_context("doc-1", template, "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    assert "Audita citas APA." in out_path.read_text(encoding="utf-8")


def test_pack_context_filters_ledger_lines_by_keyword(tmp_path, workspace, service):
    ledger_path = Path(_config(tmp_path)["paths"]["fact_ledger"])
    ledger_path.write_text("# Fact Ledger\n\n- El alcance está definido.\n- Otro hecho no relacionado.\n", encoding="utf-8")
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "El alcance está definido." in text


def test_pack_context_includes_manifest_facts_matching_keywords(tmp_path, workspace, service):
    config = _config(tmp_path)
    service.evidence_repository.write_manifest(
        Path(config["paths"]["source_manifest"]),
        {"facts": [{"classification": "confirmado", "claim": "El alcance fue validado.", "source": "a"}]},
    )
    out_path = service.pack_context("doc-1", _template(), "introduccion", config, review_kwargs=_REVIEW_KWARGS)
    assert "El alcance fue validado." in out_path.read_text(encoding="utf-8")


def test_pack_context_caps_manifest_facts_at_40(tmp_path, workspace, service):
    config = _config(tmp_path)
    facts = [{"classification": "confirmado", "claim": f"Alcance hecho {i}"} for i in range(50)]
    service.evidence_repository.write_manifest(Path(config["paths"]["source_manifest"]), {"facts": facts})
    out_path = service.pack_context("doc-1", _template(), "introduccion", config, review_kwargs=_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert text.count("Alcance hecho") == 40


def test_pack_context_includes_current_draft_and_findings_when_section_exists(tmp_path, workspace, service):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text("Sin titulo.\n", encoding="utf-8")
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "## Borrador actual" in text
    assert "structure.missing_title" in text


def test_pack_context_notes_missing_draft_when_section_absent(tmp_path, workspace, service):
    out_path = service.pack_context("doc-1", _template(), "introduccion", _config(tmp_path), review_kwargs=_REVIEW_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "Aún no existe" in text
```

**Expected test count:** ~9 integration tests.

---

### Task 8 — Application layer: `ContextPackService.pack_context_document`

**Files to create/modify:**
- Modify `src/docs/application/context_pack.py`.
- Modify `tests/integration/test_context_pack_service.py`.

**Verbatim legacy reference:** `pack_context_document` (1931–2015).

**Planned implementation:**

```python
# addition to src/docs/application/context_pack.py
import re

from docs.domain.markdown_text import strip_frontmatter_and_markdown

_DOCUMENT_PROMPT_NAMES = ["document-reviewer.md", "docx-builder.md", "format-auditor.md"]
_WORD_RE = re.compile(r"\b[\wÁÉÍÓÚÜÑáéíóúüñ-]+\b")


class ContextPackService:
    ...  # existing methods unchanged

    def pack_context_document(
        self,
        doc_id: str,
        template: Template,
        config: dict[str, Any],
        *,
        review_document_kwargs: dict[str, Any],
    ) -> Path:
        lines: list[str] = [
            "# Context pack — DOCUMENTO COMPLETO",
            "",
            "_Paquete para la revisión global y el cierre del documento. Úsalo con el rol "
            "`document-reviewer.md` y corre `review-document --strict --json` y `verify --strict` "
            "hasta quedar en verde._",
            "",
            "## Estado por sección",
            "",
            "| Sección | Existe | Palabras | PENDIENTE | Autor | Modelo |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for section in sorted(template.sections, key=lambda item: item.order):
            if not self.section_repository.section_exists(doc_id, section.order, section.id):
                lines.append(f"| {section.id} | no | – | – | – | – |")
                continue
            metadata, body = self.section_repository.read_section(doc_id, section.order, section.id)
            section_path = self.section_repository.section_path(doc_id, section.order, section.id)
            raw = section_path.read_text(encoding="utf-8")
            words = len(_WORD_RE.findall(strip_frontmatter_and_markdown(raw)))
            pending = "sí" if "PENDIENTE" in body else "no"
            author = metadata.get("authored_by", "–")
            model = metadata.get("model", "–")
            lines.append(f"| {section.id} | sí | {words} | {pending} | {author} | {model} |")
        lines.append("")

        prompts_dir = Path(config["paths"]["prompts_dir"])
        lines.extend(["## Prompts del rol", ""])
        for name in _DOCUMENT_PROMPT_NAMES:
            content = self._read_prompt(prompts_dir, name)
            if content:
                lines.extend([f"### {name}", "", content, ""])

        review = self.review_service.review_document(doc_id, template, strict=False, **review_document_kwargs)
        lines.extend(["## Hallazgos globales (review-document)", ""])
        if review.issues:
            for issue in review.issues:
                code = f" ({issue.code})" if issue.code else ""
                lines.append(f"- {issue.severity.upper()}{code}: {issue.message}")
        else:
            lines.append("- Sin hallazgos.")
        lines.append("")

        ledger_path = Path(config["paths"]["fact_ledger"])
        if self.evidence_repository.file_exists(ledger_path):
            ledger_text = self.evidence_repository.read_text(ledger_path)
            lines.extend(
                [
                    "## Hechos canónicos (ledger)",
                    "",
                    f"Fuente de verdad: `{ledger_path.resolve().as_posix()}`. Toda afirmación del documento "
                    "debe ser consistente con estos hechos.",
                    "",
                    ledger_text.strip(),
                    "",
                ]
            )

        out_path = self.section_repository.document_context_pack_path(doc_id)
        return self.section_repository.write_context_pack(out_path, "\n".join(lines))
```

> Parity note: legacy reads `path.read_text(...)` twice for the same file
> in the per-section loop — once implicitly via `read_section`-equivalent
> `split_frontmatter(raw)` and once for the raw `_strip_frontmatter_and_markdown(raw)`
> word count, both off the *same* `raw` variable already read once. This
> port preserves "read once, derive both" — `self.section_repository
> .read_section(...)` gives `(metadata, body)` but NOT the raw text, so an
> additional `section_path.read_text(...)` call is required for the word
> count (since `strip_frontmatter_and_markdown` needs the **raw** text
> including frontmatter, to re-split it internally — confirmed by reading
> `strip_frontmatter_and_markdown`'s own `split_frontmatter` call at the
> top). This means the port performs 2 reads (`read_section` then a raw
> `read_text`) where legacy performs 1 (`path.read_text()` then derives
> both `split_frontmatter` and `_strip_frontmatter_and_markdown` from the
> same in-memory string) — a minor, justified I/O-count deviation given
> `SectionRepository.read_section` doesn't expose the raw text, not a
> behavior change. **Flagged for reviewer**: if this extra read is
> considered unacceptable, the alternative is adding a
> `read_section_raw(doc_id, order, section_id) -> str` method to
> `SectionRepository` — not introduced here without justification beyond
> "saves one read," which this plan judges insufficient on its own.

**Planned test code (representative):**

```python
# additions to tests/integration/test_context_pack_service.py
def test_pack_context_document_lists_missing_section_as_no(tmp_path, workspace, service):
    out_path = service.pack_context_document("doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "| introduccion | no | – | – | – | – |" in text


def test_pack_context_document_reports_word_count_and_pending_for_existing_section(tmp_path, workspace, service):
    sections_dir = workspace.doc_root("doc-1") / "sections"
    sections_dir.mkdir(parents=True)
    (sections_dir / "001-introduccion.md").write_text(
        '---\n{"authored_by": "agent-x", "model": "opus"}\n---\n# Introducción\n\nPENDIENTE: completar.\n',
        encoding="utf-8",
    )
    out_path = service.pack_context_document("doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS)
    text = out_path.read_text(encoding="utf-8")
    assert "| introduccion | sí |" in text
    assert "| sí | agent-x | opus |" in text


def test_pack_context_document_writes_to_000_document_path(tmp_path, workspace, service):
    out_path = service.pack_context_document("doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS)
    assert out_path == workspace.doc_root("doc-1") / "sections" / "_context" / "000-document.context.md"


def test_pack_context_document_includes_ledger_text_when_present(tmp_path, workspace, service):
    config = _config(tmp_path)
    Path(config["paths"]["fact_ledger"]).write_text("# Fact Ledger\n\n- Hecho canónico.\n", encoding="utf-8")
    out_path = service.pack_context_document("doc-1", _template(), config, review_document_kwargs=_REVIEW_DOCUMENT_KWARGS)
    assert "Hecho canónico." in out_path.read_text(encoding="utf-8")


def test_pack_context_document_omits_ledger_section_when_ledger_absent(tmp_path, workspace, service):
    out_path = service.pack_context_document("doc-1", _template(), _config(tmp_path), review_document_kwargs=_REVIEW_DOCUMENT_KWARGS)
    assert "## Hechos canónicos (ledger)" not in out_path.read_text(encoding="utf-8")
```

> `_REVIEW_DOCUMENT_KWARGS` denotes the full kwarg bundle
> `ReviewService.review_document` requires (`manifest_exists`,
> `manifest_size`, `excluded_terms`, `is_policy_file`,
> `first_person_patterns`, `subjective_terms`, `secret_patterns`,
> optionally `scope_term`/`scope_focus`) — implementer defines this
> constant in the test file analogous to `_REVIEW_KWARGS` in Task 7.

**Expected test count:** ~5 integration tests.

---

## Out-of-scope confirmation

- **`section_by_id` / `section_path_for`** (legacy 594–605) — not
  re-ported as free functions; satisfied by `Template.sections` +
  `SectionRepository.section_path`, per Slice 8 Design Decision 2.
- **`_as_posix`** (legacy 208–209) — trivial `.resolve().as_posix()`,
  already inlined at call sites throughout (confirmed Slice 4/7
  precedent); this slice's one call site (`pack_context_document`'s
  ledger-path message) inlines it the same way (see Task 8's
  implementation, `ledger_path.resolve().as_posix()`).
- **Legacy's own single-file `review_section`** (lines 1445–1499) —
  already ported as `domain.rules.review_section_text` +
  `ReviewService.review_document`'s loop body, confirmed in Slice 8
  Design Decision 0/1. The *new* `ReviewService.review_section` added in
  this slice's Task 6 is a different thing: a single-section
  orchestration wrapper needed because `pack_context`'s call site expects
  one, not a re-port of legacy's `review_section` under a new name.
- **`format_audit_docx` / `build_docx` / everything from Slice 10+** — not
  touched; out of this line range entirely.
- **Any typed `Config` model** — confirmed absent from the whole codebase
  (reconfirmed in this slice by reading `application/evidence.py`/
  `application/review.py` directly); not introduced here. All new/extended
  service methods take `config: dict[str, Any]` for path-shaped values.
- **CLI commands invoking `pack-context`/`add-asset`/etc.** — no `cli/`
  directory exists yet (confirmed via Slice 7's final review grep); out of
  scope until a CLI slice.
- **`Workspace.prompts_dir`/`Workspace.fact_ledger_path` as typed
  properties** — not introduced; `prompts_dir`/`fact_ledger` remain
  caller-supplied `config["paths"][...]` values, consistent with
  `manual_dir`/`extracted_dir`/`rules_manifest` already being plain config
  values rather than `Workspace` properties (only `documents_dir`/
  `templates_dir`/per-doc subdirectories the codebase has *always* modeled
  as `Workspace`-owned are `Workspace` properties/methods).

## Global constraints

- **Config-as-dict convention.** No typed `Config` Pydantic model exists
  anywhere in this codebase. Every new/extended service method in this
  slice reads `config["paths"][...]` directly for path-shaped values
  (`prompts_dir`, `fact_ledger`, the three manifest paths), exactly like
  every prior slice's services.
- **Parity discipline.** Every ported function must be byte-for-byte
  behaviorally identical to the legacy block quoted above for it,
  including Spanish strings, the `manifest_facts[:40]` slice limit, the
  `_matches_keywords` empty-keywords-matches-everything short-circuit, and
  the exact Markdown table/heading formatting. The one explicitly flagged
  *behavior* question (not just a refactor) is the `contract.model_dump()`
  vs. raw-dict JSON serialization in Task 7 — verify against a real
  fixture before treating it as settled.
- **Single-port-dependency discipline per service — relaxed exactly once,
  documented.** `AssetService` depends only on `AssetRepository`.
  `ReviewService` (already) depends only on `SectionRepository`.
  `EvidenceService` (already) depends only on `EvidenceRepository`.
  `ContextPackService` is the **first and only** service in this codebase
  that composes two ports AND two other application services — see Design
  Decision 2 for the full justification and the documented fallback if
  this is rejected by the reviewer.
- **Document-scoped vs. workspace-shared paths, justified each time.**
  Assets are document-scoped (`doc_root(doc_id)/assets`, Design Decision
  1); the `_context/` pack output directory is document-scoped too
  (already implied by living under `sections_dir`, itself under
  `doc_root(doc_id)`). Neither introduces a new workspace-shared path
  concept.
- **Grow-only ports, justified each time.** Task 4's `SectionRepository`
  growth (3 new methods) and Task 2's brand-new `AssetRepository` are both
  justified against the existing Protocols' actual current shape (read
  directly in this plan's research, not assumed) — confirmed no existing
  port already covers either I/O shape.
- **Strict TDD per task.** Each task above is independently testable and
  committable: failing test → minimal implementation → passing test →
  commit, then independent fresh-context review, exactly as Slices 1–8.
- **No CLI, no orchestration glue in this slice.** This slice stops at
  `AssetService`/`ContextPackService`/`ReviewService.review_section`
  methods. Wiring `prompts_dir`/`fact_ledger`/manifest paths end-to-end
  from a real config file, and exposing any of this through a CLI, is
  explicitly future work.
