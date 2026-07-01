# Slice 13 — Doctor + Corrections · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 119–151 (`Check`/`DoctorResult`),
2185–2294 (`run_doctor`), 3080–3133 (`apply_corrections`), 3136–3149
(`parse_simple_yaml`). The roadmap's line ranges (2185–2296, 3080–3151) pad
slightly past the actual function bodies to the next blank line — not a
real drift, confirmed by direct read.

## Overview / Scope

This slice ports the harness's two remaining validation/maintenance
capabilities, bundled into one slice per the roadmap ("to avoid a
single-function slice") — but implemented as **two independent services**,
not one class, since they share no collaborators (`DoctorService` needs
`EvidenceRepository`+`AssetService`+`Template`; `CorrectionsService` needs
`SectionRepository`+`EvidenceRepository.hash_text`), matching this
migration's one-service-per-use-case-group discipline and the original
design spec's own module split.

1. Ports `Check`/`DoctorResult` (pure value objects) and `parse_simple_yaml`
   (a hand-rolled minimal `key: value` parser — confirmed NOT a real YAML
   parser, no new dependency needed) into new domain modules.
2. Adds a reusable `section_by_id` pure lookup to `domain/sections.py` —
   legacy never had this as a shared helper; every existing
   `ReviewService` call site reimplements section lookup ad hoc with three
   different, inconsistent error shapes. `apply_corrections` needs
   legacy's exact `ValueError` + "known sections" message.
3. Grows `SectionRepository` with three methods `apply_corrections` needs
   that no existing method covers: resolving a section file with a
   glob-fallback, and reading/writing raw (unparsed) text at an
   already-resolved path.
4. Adds `CorrectionsService.apply_corrections`, composing the grown
   `SectionRepository` + `EvidenceRepository.hash_text` + the two new pure
   functions. The `corrections_applied` JSON state file and the `*.yaml`
   inbox glob are handled as direct application-layer filesystem I/O — no
   new port — per the already-established precedent that simple,
   non-external-tool I/O doesn't need one (see Design Decision 4).
5. Adds `DoctorService.run_doctor`, composing `EvidenceRepository` +
   `AssetService` + a `Template` built internally from the raw `config`
   dict (for the one check, `rules_config`, that needs typed section/
   contract iteration) + direct imports of the already-shipped
   `resolve_pandoc_executable`/`resolve_libreoffice_executable` + a bare
   `shutil.which("gh")` call + plain `Path` existence checks.

One scope decision was resolved by the user before this plan was written
(2026-07-01):

- **Drop the 5 PNG-pipeline-adjacent doctor checks entirely** —
  `poppler_pdfinfo`, `poppler_pdftoppm`, `pypdfium2`, `visual_render_backend`,
  `documents_render_docx`. These exist solely to validate infrastructure for
  the PNG-per-page rendering pipeline Slice 12 permanently excluded
  (2026-06-21 decision: "will be reimplemented differently later").
  `visual_render_backend`/`documents_render_docx` are `required=strict` in
  legacy, meaning a verbatim port would make `doctor --strict` permanently
  unable to pass in this migration. Dropping them keeps `--strict` doctor
  output meaningful, consistent with Slice 12's own full exclusion of this
  pipeline rather than leaving degraded stand-ins.

Two legacy-signature deviations are unavoidable, not optional, and are
documented here rather than silently introduced (same treatment Slice 12
gave its `strict`-mode consequence):

- **`DoctorService.run_doctor` and `CorrectionsService.apply_corrections`
  both take an explicit `doc_id: str` parameter legacy never had.** Legacy
  assumed a single global active document; every doc_id-scoped capability
  in this codebase since Slice 7 (`ReviewService`, `ContextPackService`,
  `DocxAssemblyService`, `QaService`) already takes `doc_id` as its first
  real parameter — asset paths and section files are doc_id-scoped, so
  there is no way to check `asset:{name}` existence or resolve a section
  file without one.

### What is ported in Slice 13

- `Check`/`DoctorResult` (119–151) → new `domain/doctor.py`, verbatim.
- `run_doctor` (2185–2294) → `DoctorService.run_doctor`, verbatim except:
  (a) takes `doc_id` (see above), (b) the 5 PNG-pipeline-adjacent checks
  are dropped (see scope decision above), (c) `pandoc`/`libreoffice`
  resolution uses the already-shipped `resolve_pandoc_executable`/
  `resolve_libreoffice_executable` instead of legacy's `resolve_executable`
  (established Slice 11a/12 precedent, not a new decision), (d) `gh`
  resolution uses a bare `shutil.which("gh")` instead of legacy's
  `resolve_executable("gh", [])` — behaviorally identical (legacy passed an
  empty fallback list, so `resolve_executable` was already just
  `shutil.which` plus a dead bundled-runtime branch that Slice 11a's
  precedent already established as dead weight to drop), (e) the
  `documents_script:{script}` loop reads its directory from
  `config["paths"].get("documents_scripts_dir")` instead of the hardcoded
  `DOCUMENTS_SCRIPTS` constant, mirroring Slice 12's already-accepted
  precedent for the exact same constant.
- `apply_corrections` (3080–3133) → `CorrectionsService.apply_corrections`,
  verbatim except: (a) takes `doc_id`, (b) section-file resolution and raw
  text I/O route through three new `SectionRepository` methods instead of
  inline `Path`/glob code.
- `parse_simple_yaml` (3136–3149) → new `domain/corrections.py`, verbatim,
  no reshaping.
- `section_by_id` (598–603, not previously ported anywhere) → new pure
  function in `domain/sections.py`, verbatim message/exception shape.

### Already satisfied — not re-ported here

- `review_rules(template, manifest_exists, manifest_size, strict)` →
  `docs.domain.rules.review_rules` (Slice 3). `DoctorService` builds a
  `Template` via `Template.model_validate(config)` immediately before this
  call — the only place in this slice that needs the typed view; every
  other check in this slice reads the raw `config` dict directly, matching
  this migration's dominant "config stays a plain dict" convention.
- `structure_parts(config)` → `docs.domain.docx_structure.structure_parts`
  (Slice 10, forward-pulled). Used verbatim for the `asset:{name}` check
  loop.
- `asset_path(config, name)` → `AssetService.asset_path(doc_id, name)`
  (Slice 9), already doc_id-scoped. `DoctorService` calls this then checks
  `.exists()` itself — no new `AssetService` method needed.
- `split_frontmatter(text)` → `docs.domain.markdown_text.split_frontmatter`
  (Slice 6). Reused by `CorrectionsService` for the `body_hash` fallback
  branch only (the write branch needs the raw combined text, hence the new
  `SectionRepository.read_raw_text`/`write_raw_text`).
- `sha256_text(text)` → `EvidenceRepository.hash_text` (Slice 6).
- `resolve_executable("pandoc", ...)` / `resolve_executable("soffice"/
  "libreoffice", ...)` → superseded by `resolve_pandoc_executable`
  (Slice 11a) / `resolve_libreoffice_executable` (Slice 12), both already
  established as direct-import, non-port-mediated free functions
  (Slice 11a Design Decision 4: "a pure filesystem lookup with no
  adapter-state dependency ... correctly stays a bare import").

### Out of scope (confirmed, not re-derived)

- `poppler_pdfinfo`/`poppler_pdftoppm`/`pypdfium2`/`visual_render_backend`/
  `documents_render_docx` checks — dropped per the scope decision above.
- Any CLI surface (`doctor`/`apply-corrections` command wiring) — Slice 15.
- `run_pipeline`/`verify_all`/`log_run` — Slice 14.

## Legacy code blocks (verbatim — as supplied, reused without modification
except where noted above)

### `Check` / `DoctorResult` (lines 119–151)

```python
@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "required": self.required, "detail": self.detail}


@dataclass
class DoctorResult:
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def to_markdown(self) -> str:
        lines = ["# Doctor del arnés", ""]
        for check in self.checks:
            if check.ok:
                marker = "OK"
            elif check.required:
                marker = "FAIL"
            else:
                marker = "WARN"
            lines.append(f"- {marker} `{check.name}`: {check.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": [check.to_dict() for check in self.checks]}
```

### `run_doctor` (lines 2185–2294, annotated with the drop/substitution
points named above)

```python
def run_doctor(config: dict[str, Any], strict: bool = False) -> DoctorResult:
    checks: list[Check] = []

    for name in ["context_dir", "manual_dir"]:
        value = config["paths"].get(name)
        if value:
            path = Path(value)
            checks.append(Check(name, path.exists() and path.is_dir(), str(path)))

    if config["paths"].get("extracted_dir"):
        extracted = Path(config["paths"]["extracted_dir"])
        checks.append(Check("extracted_dir_traceability_only", config["paths"].get("extracted_dir_policy") == "rules_traceability_only", f"{extracted} ({config['paths'].get('extracted_dir_policy', 'missing')})", required=False))

    for name in ["template_docx", "example_pdf", "manual_pdf"]:
        value = config["paths"].get(name)
        if value:
            path = Path(value)
            checks.append(Check(name, path.exists() and path.is_file(), str(path), required=False))

    # Assets .docx referenciados por la estructura deben existir.
    for part in _structure_parts(config):
        if part.get("type") in {"cover_from_asset", "embed_docx"}:
            name = part.get("asset", "")
            path = asset_path(config, name)
            checks.append(Check(f"asset:{name}", path.exists(), str(path) if path.exists() else f"Falta el asset `{name}`. Agrégalo con `asset add`.", required=False))

    rules_result = review_rules(config, strict=False)
    checks.append(Check("rules_config", rules_result.passed, "Contratos, APA 7 y preliminares configurados" if rules_result.passed else rules_result.to_markdown(), required=True))
    rules_path = Path(config["paths"]["rules_manifest"])
    checks.append(Check("rules_manifest", rules_path.exists(), str(rules_path) if rules_path.exists() else "Ejecutar `build-rules`.", required=False))

    checks.append(Check("python", True, sys.executable))
    pandoc = resolve_executable("pandoc", PANDOC_FALLBACKS)
    checks.append(Check("pandoc", bool(pandoc), pandoc or "No encontrado en PATH. Instalar Pandoc para build-docx."))
    libreoffice = resolve_executable("soffice", LIBREOFFICE_FALLBACKS) or resolve_executable(
        "libreoffice", LIBREOFFICE_FALLBACKS
    )
    checks.append(
        Check("libreoffice", bool(libreoffice), libreoffice or "No encontrado en PATH. Instalar LibreOffice para qa-docx.")
    )

    # --- 5 poppler/pypdfium2/Documents-renderer checks DROPPED here (user
    # decision, 2026-07-01) — see "Overview / Scope" above. ---

    for script in config.get("documents_tools", {}).get("scripts", []):
        script_path = DOCUMENTS_SCRIPTS / script
        checks.append(
            Check(
                f"documents_script:{script}",
                script_path.exists(),
                str(script_path) if script_path.exists() else "No encontrado en plugin Documents.",
                required=strict and config.get("documents_tools", {}).get("required_in_strict", True),
            )
        )
    gh = resolve_executable("gh", [])
    checks.append(Check("gh", bool(gh), gh or "No encontrado. Requerido para collect-issues.", required=strict))

    try:
        import docx  # noqa: F401

        checks.append(Check("python-docx", True, "Disponible"))
    except Exception as exc:
        checks.append(Check("python-docx", False, f"No disponible: {exc}"))

    return DoctorResult(checks)
```

### `apply_corrections` (lines 3080–3133)

```python
def apply_corrections(config: dict[str, Any]) -> int:
    inbox = Path(config["paths"]["corrections_inbox_dir"])
    applied_path = Path(config["paths"]["corrections_applied"])
    applied_path.parent.mkdir(parents=True, exist_ok=True)
    if applied_path.exists():
        applied_state = json.loads(applied_path.read_text(encoding="utf-8"))
    else:
        applied_state = {"schema": 1, "applied": []}
    applied_ids = {item["id"] for item in applied_state.get("applied", [])}

    count = 0
    for correction_path in sorted(inbox.glob("*.yaml")) if inbox.exists() else []:
        correction = parse_simple_yaml(correction_path.read_text(encoding="utf-8"))
        correction_id = correction.get("id")
        if not correction_id or correction_id in applied_ids:
            continue
        section_id = correction.get("section_id", "")
        find = correction.get("find", "")
        replace = correction.get("replace", "")
        expected_hash = correction.get("expected_hash", "") or correction.get("expected_body_hash", "")
        if not section_id or not find:
            raise RuntimeError(f"Corrección inválida en {correction_path}: requiere id, section_id y find.")
        section = section_by_id(config, section_id)
        path = section_path_for(config, section)
        if not path.exists():
            matches = sorted(Path(config["paths"]["sections_dir"]).glob(f"*-{section_id}.md"))
            if matches:
                path = matches[0]
            else:
                raise FileNotFoundError(f"No existe sección para corrección {correction_id}: {path}")
        text = path.read_text(encoding="utf-8")
        current_meta, current_body = split_frontmatter(text)
        current_hash = current_meta.get("body_hash") or sha256_text(current_body)
        if expected_hash and expected_hash != current_hash:
            raise RuntimeError(
                f"Corrección {correction_id} esperaba hash {expected_hash}, pero la sección tiene {current_hash}."
            )
        if find not in text:
            raise RuntimeError(f"No se encontró texto objetivo para corrección {correction_id}: {find}")
        path.write_text(text.replace(find, replace, 1), encoding="utf-8")
        applied_state.setdefault("applied", []).append(
            {
                "id": correction_id,
                "section_id": section_id,
                "path": _as_posix(path),
                "expected_hash": expected_hash,
                "applied_at": datetime.now().isoformat(timespec="seconds"),
            }
        )
        applied_ids.add(correction_id)
        count += 1

    applied_path.write_text(json.dumps(applied_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return count
```

### `parse_simple_yaml` (lines 3136–3149)

```python
def parse_simple_yaml(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        data[key.strip()] = value
    return data
```

### `section_by_id` (lines 598–603, not previously ported)

```python
def section_by_id(config: dict[str, Any], section_id: str) -> dict[str, Any]:
    for section in config["sections"]:
        if section["id"] == section_id:
            return section
    known = ", ".join(section["id"] for section in config["sections"])
    raise ValueError(f"Sección desconocida: {section_id}. Secciones disponibles: {known}")
```

## Verified context (read directly this session)

- **`src/docs/domain/ports/evidence_repository.py`** (full file, 10
  methods): confirmed `file_exists(path: Path) -> bool` and
  `file_size(path: Path) -> int` already exist — cover `manifest_exists`/
  `manifest_size` and the `rules_manifest`/`corrections_applied` existence
  checks directly, no port growth needed on this port.
- **`src/docs/domain/ports/section_repository.py`** (full file, 9
  methods): confirmed no existing method reads/writes raw combined text at
  an arbitrary already-resolved `Path`, and no glob-fallback lookup
  exists. `write_context_pack(path, content) -> Path` has the closest
  shape (mkdir-parent + write_text + return path) but is a different
  domain concept (context packs, not section correction text) — not
  reused, a dedicated method is added instead (Design Decision 3).
- **`src/docs/infrastructure/persistence/json_section_repository.py`**
  (full file, 54 lines): confirmed the canonical section-file naming
  convention (`{order:03d}-{section_id}.md` under
  `workspace.doc_root(doc_id) / "sections"`), which the new
  `find_section_file` glob-fallback must search within (`*-{section_id}.md`
  under the same directory, matching legacy's exact glob pattern).
- **`src/docs/application/asset.py`** (full file, 39 lines): confirmed
  `AssetService.asset_path(doc_id, name)` returns a `Path` without
  checking existence — `DoctorService` calls `.exists()` on the result
  itself, matching legacy's own `path.exists()` call immediately after
  `asset_path(...)`.
- **`src/docs/domain/rules.py`** (`review_rules`, lines 280+): confirmed
  exact signature `review_rules(template: Template, manifest_exists: bool,
  manifest_size: int, strict: bool = False) -> ReviewResult`, and that it
  reads `template.sections`/`template.section_contracts` (typed) plus
  `template.model_extra` for everything else — confirming `Template` is a
  structural superset of `config`, safely reconstructible via
  `Template.model_validate(config)`.
- **`src/docs/domain/models/template.py`** (`Section`, lines 30–36):
  confirmed `id: str`, `title: str`, `order: int = 0` — `section_by_id`
  operates on the raw `list[dict[str, Any]]` from `config["sections"]`
  (not a typed `Section`), matching legacy's own dict-based signature and
  keeping `CorrectionsService` free of any `Template` dependency (only
  `DoctorService` needs the typed bridge, for `review_rules` alone).
- **`pyproject.toml`** (confirmed): `defusedxml>=0.7.1`,
  `pydantic>=2.13.4`, `python-docx>=1.2.0` — no YAML library present or
  needed; `parse_simple_yaml` is confirmed (by direct read of its body) to
  be a hand-rolled minimal `key: value` subset parser (no nesting, no
  lists, no anchors), not a real YAML parser.
- **No `.codegraph` index exists** at `C:\code\harness-projects\docs` —
  confirmed absent, same as every prior slice.
- **`CODEX_RUNTIME_BIN`/`DOCUMENTS_SCRIPTS`/`DOCUMENTS_RENDER_DOCX`** —
  confirmed absent from `src/docs` (grepped, corroborating Slice 11a/12's
  own final-review findings) — this slice must not reintroduce any of
  them.
- **`.superpowers/sdd/progress.md`, Slice 6 entry**: independently
  corroborates this slice's exact scope boundary — "`run_doctor` reads
  `rules_manifest`'s mere existence ... plus a long list of external-tool
  checks (`pandoc`, `libreoffice`, `pypdfium2`, `poppler`) entirely
  unrelated to hashing — explicitly out of scope [of Slice 6]."

## Design decisions

1. **Two services, not one class.** `DoctorService` (needs
   `EvidenceRepository`+`AssetService`+`Template`) and `CorrectionsService`
   (needs `SectionRepository`+`EvidenceRepository.hash_text`) share no
   collaborators. The roadmap's "bundled in to avoid a single-function
   slice" is a scheduling reason, not an architectural one — matches every
   other slice's one-service-per-use-case-group discipline and the
   original design spec's own module split (`doctor.py`/`corrections.py`
   as separate application modules).

2. **`DoctorService` builds a `Template` internally via
   `Template.model_validate(config)`, immediately before the one call that
   needs it (`review_rules`).** Every other check in this slice reads the
   raw `config` dict directly — matching the dominant "config stays a
   plain dict" convention this migration has followed since Slice 1.
   `Template` already has `extra="allow"`, and `review_rules` itself
   already treats `template.model_extra` as "the rest of config" — so
   `Template` and `config` are, and always have been, views onto the same
   underlying JSON object. This is the first slice where a single method
   needs both views at once; building the typed view internally (rather
   than requiring the caller to pass a separately-constructed `Template`
   alongside `config`) keeps `DoctorService.run_doctor`'s public signature
   as simple as every sibling service's (`config: dict[str, Any]`, not
   `config: dict[str, Any], template: Template`).

3. **`SectionRepository` grows three methods — `find_section_file`,
   `read_raw_text`, `write_raw_text` — rather than `CorrectionsService`
   doing this I/O directly or a new port being introduced.** The section
   file naming convention (`{order:03d}-{section_id}.md`,
   `*-{section_id}.md` glob fallback) is `SectionRepository`'s domain
   knowledge alone (Slice 5's own convention) — duplicating that glob
   pattern inside `CorrectionsService` would either require exposing the
   naming convention outside the repository or re-deriving it, both worse
   than adding three narrow methods to the port that already owns section
   file paths. This mirrors Slice 9's "grow the existing repository when
   the I/O concept clearly belongs to it" precedent.

4. **The `corrections_applied` JSON state file and the `*.yaml` inbox glob
   get NO new port — direct filesystem I/O inside `CorrectionsService`,
   diverging from this slice's own initial research recommendation of a
   small dedicated port.** On reflection, this is squarely the same
   category of I/O this migration has already and repeatedly allowed
   directly in the application layer without a port: `DocxAssemblyService`
   does tempdir-stripping and file writes directly; `QaService` does
   `mkdir`/`shutil.rmtree`/`write_text` directly. Reading/writing one JSON
   state file and globbing one directory of `.yaml` files is no more
   complex than those already-accepted precedents, and — critically —
   involves no external tool subprocess call, which is the actual
   boundary this migration's "Global constraints" sections have
   consistently drawn ("only external-tool subprocess calls are pushed
   behind a port"). Reusing `EvidenceRepository.write_manifest` for this
   file was considered and rejected: it silently skips writes when the
   payload is unchanged and always stamps a `generated_at` field, neither
   of which matches `apply_corrections`' legacy behavior (always writes
   after a mutation; never adds `generated_at`) — reusing it would be a
   silent, undocumented behavior change, not a legitimate simplification.

5. **`gh` resolution is a bare `shutil.which("gh")` call inside
   `DoctorService`, not `SourceRepository.find_executable` (Slice 7) and
   not a new port method.** Threading `SourceRepository` — a port about
   git/gh *usage* for `CollectionService*, not tool *detection* — into
   `DoctorService` purely for one existence check would be an unrelated
   coupling. `resolve_pandoc_executable`/`resolve_libreoffice_executable`
   both already call `shutil.which(...)` internally rather than depending
   on another port for that; `gh`'s check (legacy passed an empty fallback
   list, so `resolve_executable("gh", [])` was already behaviorally
   identical to a bare `shutil.which`) follows the same direct-call shape,
   just without even needing a dedicated resolver function since there
   are no fallback paths to check.

6. **`resolve_pandoc_executable`/`resolve_libreoffice_executable` are
   imported directly from their infrastructure modules into
   `application/doctor.py`, not routed through any port.** This is not a
   new decision — Slice 11a's Design Decision 4 already established this
   exact exception ("a pure filesystem lookup with no adapter-state
   dependency ... correctly stays a bare import") for
   `DocxAssemblyService`; `DoctorService` is a second consumer of the same
   already-accepted precedent, not a new one.

## Task breakdown

### Task 1 — Pure domain functions (`domain/doctor.py`, `domain/corrections.py`,
`domain/sections.py` addition)

**Files to create/modify:**
- Create `src/docs/domain/doctor.py`.
- Create `src/docs/domain/corrections.py`.
- Modify `src/docs/domain/sections.py`: add `section_by_id`.
- Create `tests/unit/domain/test_doctor.py`.
- Create `tests/unit/domain/test_corrections.py`.
- Modify `tests/unit/domain/test_sections.py`: add `section_by_id` tests.

**Verbatim legacy reference:** `Check`/`DoctorResult` (119–151), verbatim.
`parse_simple_yaml` (3136–3149), verbatim. `section_by_id` (598–603),
verbatim — first port of this function anywhere in this migration.

**Planned implementation:**

```python
# src/docs/domain/doctor.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "required": self.required, "detail": self.detail}


@dataclass
class DoctorResult:
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(check.ok for check in self.checks if check.required)

    def to_markdown(self) -> str:
        lines = ["# Doctor del arnés", ""]
        for check in self.checks:
            if check.ok:
                marker = "OK"
            elif check.required:
                marker = "FAIL"
            else:
                marker = "WARN"
            lines.append(f"- {marker} `{check.name}`: {check.detail}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "checks": [check.to_dict() for check in self.checks]}
```

```python
# src/docs/domain/corrections.py
from __future__ import annotations


def parse_simple_yaml(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        data[key.strip()] = value
    return data
```

```python
# src/docs/domain/sections.py (addition — existing functions untouched)
from typing import Any


def section_by_id(sections: list[dict[str, Any]], section_id: str) -> dict[str, Any]:
    for section in sections:
        if section["id"] == section_id:
            return section
    known = ", ".join(section["id"] for section in sections)
    raise ValueError(f"Sección desconocida: {section_id}. Secciones disponibles: {known}")
```

**Planned test code:**

```python
# tests/unit/domain/test_doctor.py
from __future__ import annotations

from docs.domain.doctor import Check, DoctorResult


def test_check_to_dict_includes_all_fields():
    check = Check("pandoc", True, "/usr/bin/pandoc", required=False)
    assert check.to_dict() == {"name": "pandoc", "ok": True, "required": False, "detail": "/usr/bin/pandoc"}


def test_doctor_result_passed_ignores_non_required_failures():
    result = DoctorResult([Check("optional", False, "missing", required=False)])
    assert result.passed is True


def test_doctor_result_passed_is_false_when_a_required_check_fails():
    result = DoctorResult([Check("required_thing", False, "missing", required=True)])
    assert result.passed is False


def test_doctor_result_to_markdown_uses_ok_fail_warn_markers():
    result = DoctorResult(
        [
            Check("a", True, "fine", required=True),
            Check("b", False, "broken", required=True),
            Check("c", False, "missing but optional", required=False),
        ]
    )
    markdown = result.to_markdown()
    assert "- OK `a`: fine" in markdown
    assert "- FAIL `b`: broken" in markdown
    assert "- WARN `c`: missing but optional" in markdown


def test_doctor_result_to_dict_matches_passed_and_check_dicts():
    check = Check("x", True, "ok")
    result = DoctorResult([check])
    assert result.to_dict() == {"passed": True, "checks": [check.to_dict()]}
```

```python
# tests/unit/domain/test_corrections.py
from __future__ import annotations

from docs.domain.corrections import parse_simple_yaml


def test_parse_simple_yaml_parses_basic_key_value_pairs():
    text = "id: c1\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_skips_blank_lines_and_comments():
    text = "id: c1\n\n# a comment\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_strips_double_and_single_quotes():
    text = 'find: "hello world"\nreplace: \'bye\'\n'
    assert parse_simple_yaml(text) == {"find": "hello world", "replace": "bye"}


def test_parse_simple_yaml_ignores_lines_without_a_colon():
    text = "id: c1\nnot a valid line\nsection_id: intro\n"
    assert parse_simple_yaml(text) == {"id": "c1", "section_id": "intro"}


def test_parse_simple_yaml_handles_colons_inside_the_value():
    text = "find: time: 10:30\n"
    assert parse_simple_yaml(text) == {"find": "time: 10:30"}
```

```python
# tests/unit/domain/test_sections.py (addition)
import pytest

from docs.domain.sections import section_by_id


def test_section_by_id_returns_the_matching_section():
    sections = [{"id": "intro", "order": 1}, {"id": "methods", "order": 2}]
    assert section_by_id(sections, "methods") == {"id": "methods", "order": 2}


def test_section_by_id_raises_value_error_with_known_ids_when_missing():
    sections = [{"id": "intro", "order": 1}, {"id": "methods", "order": 2}]
    with pytest.raises(ValueError, match="Sección desconocida: bogus. Secciones disponibles: intro, methods"):
        section_by_id(sections, "bogus")
```

**Expected test count:** ~12 unit tests (5 + 5 + 2). Self-reviewable — pure
functions/dataclasses, no I/O.

---

### Task 2 — `SectionRepository` Protocol extension

**Files to create/modify:**
- Modify `src/docs/domain/ports/section_repository.py`: add
  `find_section_file`, `read_raw_text`, `write_raw_text`.

**Verbatim legacy reference:** none — new Protocol methods capturing the
capabilities `apply_corrections` needs that no existing method covers
(Design Decision 3). No behavior to test (bare-Protocol precedent, Slice
4/5/9/11a/12 Task 2s).

**Planned implementation:**

```python
# src/docs/domain/ports/section_repository.py (addition — existing methods untouched)
    def find_section_file(self, doc_id: str, section_id: str) -> Path | None: ...
    def read_raw_text(self, path: Path) -> str: ...
    def write_raw_text(self, path: Path, content: str) -> None: ...
```

**Expected test count:** 0 new tests by design. Self-reviewable — diff
against this plan's code block should be byte-for-byte, existing methods
untouched.

---

### Task 3 — `JsonSectionRepository` implementation of the 3 new methods

**Files to create/modify:**
- Modify `src/docs/infrastructure/persistence/json_section_repository.py`:
  implement `find_section_file`, `read_raw_text`, `write_raw_text`.
- Modify `tests/unit/infrastructure/test_json_section_repository.py`
  (existing file — uses `workspace`/`repo` pytest fixtures already defined
  at the top of the file, reuse them): add tests for the 3 new methods.

**Verbatim legacy reference:** the glob-fallback pattern
(`Path(config["paths"]["sections_dir"]).glob(f"*-{section_id}.md")`, from
`apply_corrections` 3080–3133) ported as `find_section_file`, scoped to
`self._sections_dir(doc_id)` (the existing private helper) instead of a
raw `config["paths"]["sections_dir"]` lookup — this repository already
owns that directory resolution for every other method.

**Planned implementation:**

```python
# src/docs/infrastructure/persistence/json_section_repository.py (additions)
    def find_section_file(self, doc_id: str, section_id: str) -> Path | None:
        matches = sorted(self._sections_dir(doc_id).glob(f"*-{section_id}.md"))
        return matches[0] if matches else None

    def read_raw_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_raw_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
```

**Planned test code:**

```python
# tests/unit/infrastructure/test_json_section_repository.py (additions —
# reuse the file's existing `workspace`/`repo` fixtures, shown above for
# reference; do not redefine them)


def test_find_section_file_returns_the_matching_path(repo: JsonSectionRepository):
    repo.write_section("doc1", 2, "intro", "body")
    found = repo.find_section_file("doc1", "intro")
    assert found == repo.section_path("doc1", 2, "intro")


def test_find_section_file_returns_none_when_nothing_matches(repo: JsonSectionRepository):
    assert repo.find_section_file("doc1", "missing") is None


def test_find_section_file_returns_the_first_sorted_match_when_multiple_exist(repo: JsonSectionRepository):
    repo.write_section("doc1", 2, "intro", "second")
    repo.write_section("doc1", 1, "intro", "first")
    found = repo.find_section_file("doc1", "intro")
    assert found == repo.section_path("doc1", 1, "intro")


def test_read_raw_text_returns_the_full_file_content_including_frontmatter(repo: JsonSectionRepository):
    repo.write_section("doc1", 1, "intro", "---\nsection_id: intro\n---\nBody text")
    path = repo.section_path("doc1", 1, "intro")
    assert repo.read_raw_text(path) == "---\nsection_id: intro\n---\nBody text"


def test_write_raw_text_creates_parent_directories_and_writes_content(repo: JsonSectionRepository, tmp_path: Path):
    path = tmp_path / "nested" / "dir" / "file.md"
    repo.write_raw_text(path, "hello")
    assert path.read_text(encoding="utf-8") == "hello"
```

**Expected test count:** ~5 integration tests. Self-reviewable — small,
mechanical additions mirroring existing methods in the same file exactly
(same `mkdir`-then-write shape as `write_section`/`write_context_pack`).

---

### Task 4 — `CorrectionsService.apply_corrections`

**Files to create/modify:**
- Create `src/docs/application/corrections.py`.
- Create `tests/integration/test_corrections_service.py`.

**Verbatim legacy reference:** `apply_corrections` (3080–3133), verbatim
except: `doc_id` added (Overview/Scope), `section_by_id`/section-file
resolution route through the new pure function + `SectionRepository`
methods instead of inline `config["sections"]`/glob code, `sha256_text`
becomes `self.evidence_repository.hash_text`. The `corrections_applied`
JSON read/write and inbox glob remain direct filesystem I/O in the service
(Design Decision 4), unchanged in shape from legacy.

**Planned implementation:**

```python
# src/docs/application/corrections.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from docs.domain.corrections import parse_simple_yaml
from docs.domain.markdown_text import split_frontmatter
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.ports.section_repository import SectionRepository
from docs.domain.sections import section_by_id


class CorrectionsService:
    def __init__(self, section_repository: SectionRepository, evidence_repository: EvidenceRepository) -> None:
        self.section_repository = section_repository
        self.evidence_repository = evidence_repository

    def apply_corrections(self, doc_id: str, config: dict[str, Any]) -> int:
        inbox = Path(config["paths"]["corrections_inbox_dir"])
        applied_path = Path(config["paths"]["corrections_applied"])
        applied_path.parent.mkdir(parents=True, exist_ok=True)
        if applied_path.exists():
            applied_state = json.loads(applied_path.read_text(encoding="utf-8"))
        else:
            applied_state = {"schema": 1, "applied": []}
        applied_ids = {item["id"] for item in applied_state.get("applied", [])}

        count = 0
        for correction_path in sorted(inbox.glob("*.yaml")) if inbox.exists() else []:
            correction = parse_simple_yaml(correction_path.read_text(encoding="utf-8"))
            correction_id = correction.get("id")
            if not correction_id or correction_id in applied_ids:
                continue
            section_id = correction.get("section_id", "")
            find = correction.get("find", "")
            replace = correction.get("replace", "")
            expected_hash = correction.get("expected_hash", "") or correction.get("expected_body_hash", "")
            if not section_id or not find:
                raise RuntimeError(f"Corrección inválida en {correction_path}: requiere id, section_id y find.")
            section = section_by_id(config["sections"], section_id)
            path = self.section_repository.section_path(doc_id, section["order"], section_id)
            if not path.exists():
                fallback = self.section_repository.find_section_file(doc_id, section_id)
                if fallback is not None:
                    path = fallback
                else:
                    raise FileNotFoundError(f"No existe sección para corrección {correction_id}: {path}")
            text = self.section_repository.read_raw_text(path)
            current_meta, current_body = split_frontmatter(text)
            current_hash = current_meta.get("body_hash") or self.evidence_repository.hash_text(current_body)
            if expected_hash and expected_hash != current_hash:
                raise RuntimeError(
                    f"Corrección {correction_id} esperaba hash {expected_hash}, pero la sección tiene {current_hash}."
                )
            if find not in text:
                raise RuntimeError(f"No se encontró texto objetivo para corrección {correction_id}: {find}")
            self.section_repository.write_raw_text(path, text.replace(find, replace, 1))
            applied_state.setdefault("applied", []).append(
                {
                    "id": correction_id,
                    "section_id": section_id,
                    "path": path.resolve().as_posix(),
                    "expected_hash": expected_hash,
                    "applied_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            applied_ids.add(correction_id)
            count += 1

        applied_path.write_text(json.dumps(applied_state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return count
```

**Planned test code:**

```python
# tests/integration/test_corrections_service.py
from __future__ import annotations

import json
from pathlib import Path

import pytest

from docs.application.corrections import CorrectionsService
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    return CorrectionsService(JsonSectionRepository(workspace), JsonEvidenceRepository()), workspace


def _config(tmp_path, sections):
    return {
        "paths": {
            "corrections_inbox_dir": str(tmp_path / "inbox"),
            "corrections_applied": str(tmp_path / "state" / "applied.json"),
        },
        "sections": sections,
    }


def test_apply_corrections_returns_zero_when_inbox_is_empty(tmp_path):
    service, _ = _service(tmp_path)
    config = _config(tmp_path, [{"id": "intro", "order": 1}])
    assert service.apply_corrections("doc1", config) == 0


def test_apply_corrections_replaces_text_and_records_applied_entry(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    count = service.apply_corrections("doc1", config)

    assert count == 1
    updated = section_repo.read_raw_text(section_repo.section_path("doc1", 1, "intro"))
    assert updated == "Hola gente"
    applied_state = json.loads(Path(config["paths"]["corrections_applied"]).read_text(encoding="utf-8"))
    assert applied_state["applied"][0]["id"] == "c1"


def test_apply_corrections_skips_already_applied_ids(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    service.apply_corrections("doc1", config)
    second_count = service.apply_corrections("doc1", config)

    assert second_count == 0


def test_apply_corrections_raises_when_expected_hash_does_not_match(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text(
        "id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\nexpected_hash: deadbeef\n", encoding="utf-8"
    )
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    with pytest.raises(RuntimeError, match="esperaba hash deadbeef"):
        service.apply_corrections("doc1", config)


def test_apply_corrections_falls_back_to_glob_match_when_canonical_path_missing(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    # Write under a different order than the config declares, forcing the fallback glob.
    section_repo.write_section("doc1", 9, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: mundo\nreplace: gente\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    count = service.apply_corrections("doc1", config)

    assert count == 1
    updated = section_repo.read_raw_text(section_repo.section_path("doc1", 9, "intro"))
    assert updated == "Hola gente"


def test_apply_corrections_raises_when_find_text_not_present(tmp_path):
    service, workspace = _service(tmp_path)
    section_repo = JsonSectionRepository(workspace)
    section_repo.write_section("doc1", 1, "intro", "Hola mundo")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "c1.yaml").write_text("id: c1\nsection_id: intro\nfind: ausente\nreplace: x\n", encoding="utf-8")
    config = _config(tmp_path, [{"id": "intro", "order": 1}])

    with pytest.raises(RuntimeError, match="No se encontró texto objetivo"):
        service.apply_corrections("doc1", config)
```

**Expected test count:** ~7 integration tests, real
`JsonSectionRepository`/`JsonEvidenceRepository` adapters, no mocks. Needs
implementer + fresh-context reviewer — the fallback-glob path and the
hash-guard ordering are the two places most likely to hide a subtle bug.

---

### Task 5 — `DoctorService.run_doctor`

**Files to create/modify:**
- Create `src/docs/application/doctor.py`.
- Create `tests/integration/test_doctor_service.py`.

**Verbatim legacy reference:** `run_doctor` (2185–2294), verbatim except
the substitutions and the 5-check drop named in "Overview / Scope" and
"What is ported in Slice 13" above.

**Planned implementation:**

```python
# src/docs/application/doctor.py
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.domain.doctor import Check, DoctorResult
from docs.domain.docx_structure import structure_parts
from docs.domain.models.template import Template
from docs.domain.ports.evidence_repository import EvidenceRepository
from docs.domain.rules import review_rules
from docs.infrastructure.docx.libreoffice_qa_adapter import resolve_libreoffice_executable
from docs.infrastructure.docx.python_docx_assembly_adapter import resolve_pandoc_executable


class DoctorService:
    def __init__(self, evidence_repository: EvidenceRepository, asset_service: AssetService) -> None:
        self.evidence_repository = evidence_repository
        self.asset_service = asset_service

    def run_doctor(self, doc_id: str, config: dict[str, Any], strict: bool = False) -> DoctorResult:
        checks: list[Check] = []

        for name in ["context_dir", "manual_dir"]:
            value = config["paths"].get(name)
            if value:
                path = Path(value)
                checks.append(Check(name, path.exists() and path.is_dir(), str(path)))

        if config["paths"].get("extracted_dir"):
            extracted = Path(config["paths"]["extracted_dir"])
            checks.append(
                Check(
                    "extracted_dir_traceability_only",
                    config["paths"].get("extracted_dir_policy") == "rules_traceability_only",
                    f"{extracted} ({config['paths'].get('extracted_dir_policy', 'missing')})",
                    required=False,
                )
            )

        for name in ["template_docx", "example_pdf", "manual_pdf"]:
            value = config["paths"].get(name)
            if value:
                path = Path(value)
                checks.append(Check(name, path.exists() and path.is_file(), str(path), required=False))

        for part in structure_parts(config):
            if part.get("type") in {"cover_from_asset", "embed_docx"}:
                name = part.get("asset", "")
                path = self.asset_service.asset_path(doc_id, name)
                checks.append(
                    Check(
                        f"asset:{name}",
                        path.exists(),
                        str(path) if path.exists() else f"Falta el asset `{name}`. Agrégalo con `asset add`.",
                        required=False,
                    )
                )

        template = Template.model_validate(config)
        rules_path = Path(config["paths"]["rules_manifest"])
        manifest_exists = self.evidence_repository.file_exists(rules_path)
        manifest_size = self.evidence_repository.file_size(rules_path) if manifest_exists else 0
        rules_result = review_rules(template, manifest_exists, manifest_size, strict=False)
        checks.append(
            Check(
                "rules_config",
                rules_result.passed,
                "Contratos, APA 7 y preliminares configurados" if rules_result.passed else rules_result.to_markdown(),
                required=True,
            )
        )
        checks.append(
            Check("rules_manifest", manifest_exists, str(rules_path) if manifest_exists else "Ejecutar `build-rules`.", required=False)
        )

        checks.append(Check("python", True, sys.executable))
        pandoc = resolve_pandoc_executable(config.get("paths", {}))
        checks.append(Check("pandoc", bool(pandoc), pandoc or "No encontrado en PATH. Instalar Pandoc para build-docx."))
        libreoffice = resolve_libreoffice_executable(config.get("paths", {}))
        checks.append(
            Check("libreoffice", bool(libreoffice), libreoffice or "No encontrado en PATH. Instalar LibreOffice para qa-docx.")
        )

        scripts_dir_value = config.get("paths", {}).get("documents_scripts_dir")
        scripts_dir = Path(scripts_dir_value) if scripts_dir_value else None
        for script in config.get("documents_tools", {}).get("scripts", []):
            script_path = scripts_dir / script if scripts_dir else None
            checks.append(
                Check(
                    f"documents_script:{script}",
                    script_path is not None and script_path.exists(),
                    str(script_path) if script_path is not None and script_path.exists() else "No encontrado en plugin Documents.",
                    required=strict and config.get("documents_tools", {}).get("required_in_strict", True),
                )
            )
        gh = shutil.which("gh")
        checks.append(Check("gh", bool(gh), gh or "No encontrado. Requerido para collect-issues.", required=strict))

        try:
            import docx  # noqa: F401

            checks.append(Check("python-docx", True, "Disponible"))
        except Exception as exc:
            checks.append(Check("python-docx", False, f"No disponible: {exc}"))

        return DoctorResult(checks)
```

**Planned test code:**

```python
# tests/integration/test_doctor_service.py
from __future__ import annotations

import sys
from pathlib import Path

from docs.application.asset import AssetService
from docs.application.doctor import DoctorService
from docs.domain.workspace import Workspace
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository

_MINIMAL_TEMPLATE_FIELDS = {
    "type": "template",
    "title": "T",
    "structure": [],
    "sections": [{"id": "intro", "title": "Intro", "order": 1}],
    "section_contracts": {"intro": {}},
    "context_schema": {},
}


def _service(tmp_path):
    workspace = Workspace(documents_dir=tmp_path / "documents", templates_dir=tmp_path / "templates")
    asset_service = AssetService(FilesystemAssetRepository(), workspace)
    return DoctorService(JsonEvidenceRepository(), asset_service)


def _config(tmp_path, **paths):
    config = dict(_MINIMAL_TEMPLATE_FIELDS)
    config["paths"] = {"rules_manifest": str(tmp_path / "manual-rules.json"), **paths}
    return config


def test_run_doctor_flags_missing_context_and_manual_dirs(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path, context_dir=str(tmp_path / "missing_context"), manual_dir=str(tmp_path / "missing_manual"))

    result = service.run_doctor("doc1", config)

    context_check = next(c for c in result.checks if c.name == "context_dir")
    assert context_check.ok is False


def test_run_doctor_passes_context_dir_check_when_directory_exists(tmp_path):
    (tmp_path / "context").mkdir()
    service = _service(tmp_path)
    config = _config(tmp_path, context_dir=str(tmp_path / "context"))

    result = service.run_doctor("doc1", config)

    context_check = next(c for c in result.checks if c.name == "context_dir")
    assert context_check.ok is True


def test_run_doctor_rules_manifest_check_is_not_required(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    manifest_check = next(c for c in result.checks if c.name == "rules_manifest")
    assert manifest_check.ok is False
    assert manifest_check.required is False


def test_run_doctor_python_check_is_always_ok_and_reports_sys_executable(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    python_check = next(c for c in result.checks if c.name == "python")
    assert python_check.ok is True
    assert python_check.detail == sys.executable


def test_run_doctor_reports_asset_missing_when_structure_references_one(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)
    config["structure"] = [{"type": "cover_from_asset", "asset": "cover"}]

    result = service.run_doctor("doc1", config)

    asset_check = next(c for c in result.checks if c.name == "asset:cover")
    assert asset_check.ok is False
    assert asset_check.required is False


def test_run_doctor_does_not_include_png_pipeline_checks(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    result = service.run_doctor("doc1", config)

    names = {c.name for c in result.checks}
    assert names.isdisjoint({"poppler_pdfinfo", "poppler_pdftoppm", "pypdfium2", "visual_render_backend", "documents_render_docx"})


def test_run_doctor_gh_check_required_only_when_strict(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)

    non_strict = service.run_doctor("doc1", config, strict=False)
    strict = service.run_doctor("doc1", config, strict=True)

    assert next(c for c in non_strict.checks if c.name == "gh").required is False
    assert next(c for c in strict.checks if c.name == "gh").required is True


def test_run_doctor_result_passed_reflects_rules_config_failure(tmp_path):
    service = _service(tmp_path)
    config = _config(tmp_path)
    config["section_contracts"] = {}  # missing contract for "intro" -> rules_config fails

    result = service.run_doctor("doc1", config)

    assert result.passed is False
```

**Expected test count:** ~8 integration tests, real `JsonEvidenceRepository`/
`FilesystemAssetRepository`/`AssetService` adapters, no mocks. **Highest-risk
task in this slice** — needs implementer +
fresh-context reviewer. The reviewer should specifically verify: (a) the
`Template.model_validate(config)` bridge doesn't raise on a minimal config
(Pydantic validation errors would be a new failure mode legacy never had),
(b) the 5 PNG-pipeline checks are genuinely absent (grep-verifiable), (c)
`gh`/`pandoc`/`libreoffice` checks use the correct already-shipped resolver
functions and not a reintroduced `resolve_executable`, (d) the
`documents_script` loop's `required` boolean expression matches legacy's
exact `strict and config.get(...).get("required_in_strict", True)` logic.

## Global constraints

- Config stays a plain `dict[str, Any]` everywhere except the one internal
  `Template.model_validate(config)` bridge inside `DoctorService` — no
  service's public signature takes a `Template` parameter.
- `domain/doctor.py`, `domain/corrections.py`, and the `section_by_id`
  addition to `domain/sections.py` import nothing from application/
  infrastructure/cli.
- `SectionRepository` stays a bare `Protocol` — no default method bodies.
- No new third-party pip dependency (`parse_simple_yaml` is confirmed
  hand-rolled, not a real YAML parser — no `PyYAML`/`ruamel.yaml` added).
- `poppler_pdfinfo`/`poppler_pdftoppm`/`pypdfium2`/`visual_render_backend`/
  `documents_render_docx`/`CODEX_RUNTIME_BIN`/`DOCUMENTS_SCRIPTS`/
  `DOCUMENTS_RENDER_DOCX`/`resolve_executable` (the legacy general-purpose
  one, not `resolve_pandoc_executable`/`resolve_libreoffice_executable`)
  must not appear anywhere in `src/docs` after this slice (grep-verifiable).
- Every task is TDD: failing test first, minimal implementation, full
  suite run (`rtk pytest -q`) after each task, commit per task.
- Every test must be a real assertion against real behavior — no
  placeholder tests.

## Risks and open judgment calls

1. **RESOLVED — drop the 5 PNG-pipeline-adjacent doctor checks entirely
   (user decision, 2026-07-01).** See "Overview / Scope". Downstream
   effect: `doctor --strict` in this migration never fails on
   infrastructure this migration doesn't and won't have yet; a future
   PNG-rendering slice should add its own doctor checks back in in
   whatever shape matches its actual (different) implementation, not
   reuse these exact five.
2. **`doc_id` added to both services' public signatures — unavoidable, not
   a judgment call, but flagged for visibility** since it's the one place
   this slice's signatures diverge from legacy beyond internal
   substitutions. Every doc_id-scoped service since Slice 7 already has
   this shape; `DoctorService`/`CorrectionsService` are not exceptions.
3. **Low-stakes, plan-author's call, not escalated:** Task 1 bundles three
   small pure additions across three different files (two new, one
   existing) into a single task. A reviewer could plausibly ask to split
   `domain/sections.py`'s addition from the two new files, since it
   touches an existing, already-large-ish domain module rather than
   creating a fresh one — flagged for the assigned reviewer's judgment,
   not treated as load-bearing, mirroring Slice 12's identical Task-1
   granularity note.
4. **Low-stakes:** Task 4's fallback-glob test
   (`test_apply_corrections_falls_back_to_glob_match_when_canonical_path_missing`)
   writes the section under an order (9) that doesn't match the config's
   declared order (1) to force the canonical path to miss — this is a
   slightly artificial setup (a real mismatch would more likely come from
   a section being renumbered after a correction was authored) but
   exercises the exact legacy fallback branch correctly; flagged so a
   reviewer doesn't mistake the artificiality for a defect in the test's
   premise.
