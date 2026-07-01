# Slice 12 — QA & PDF Rendering · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 2862–3079 (`qa_docx` through
`render_qa_report`), **excluding** `render_docx_pages` (2961–3008) and
`render_pdf_with_pypdfium` (3011–3038) — the PNG-per-page rendering pipeline
the user explicitly ruled out of this migration (roadmap.md Slice 12 row,
decision dated 2026-06-21: "will be reimplemented differently later").

## Overview / Scope

Slice 11b closed out the DOCX assembly/layout/TOC pipeline. Slice 12 ports
the harness's **QA pipeline**: given an already-assembled `.docx`, convert it
to PDF via LibreOffice, run the format audit (already ported,
`FormatAuditService`, Slice 10) and a set of optional external "Documents"
lint scripts, then render a single markdown QA report to disk.

This slice does four things:

1. Ports the two pure functions in this range — `render_qa_report` (the QA
   report renderer) and `ensure_child_path` (a path-containment guard used
   before a recursive delete) — into a new domain module, `domain/qa.py`.
2. Adds a new port, `QaRenderPort`, for the two external-tool capabilities
   that have no existing port to grow into: `render_docx_to_pdf`
   (LibreOffice subprocess) and `run_documents_audits` (subprocess-per-script
   orchestration for an optional external lint toolset).
3. Implements `LibreOfficeQaAdapter`, this migration's **first LibreOffice
   subprocess call** — mirroring the `resolve_pandoc_executable` shape
   Slice 11a already established for pandoc (Design Decision 1 below).
4. Adds `QaService.qa_docx`, a new "service composes service" orchestrator
   (mirrors `DocxAssemblyService(port, asset_service)` from Slice 11a) that
   wires `QaRenderPort` + the already-shipped `FormatAuditService` together,
   exactly replicating legacy `qa_docx`'s control flow.

Three real judgment calls came up while researching this slice and were
decided by the user before this plan was written (not inferred silently):

- **Strict-mode PNG requirement (user decision, 2026-07-01): keep verbatim.**
  Legacy's `qa_docx(strict=True)` raises `RuntimeError` whenever no PNG pages
  were produced. Since PNG rendering is permanently out of scope, this slice
  ports that behavior byte-for-byte: `strict=True` **always** raises before
  running any audit, exactly like Slice 11a shipped `_stub`-suffixed
  placeholders as "documented, not silently working" rather than quietly
  changing behavior. `strict=False` (the common case) works fully
  end-to-end, including the format audit, the Documents audits, and the
  written QA report.
- **`DOCUMENTS_SCRIPTS` path (user decision, 2026-07-01): route through
  config, not a hardcoded Codex-plugin-cache path.** Legacy hardcodes
  `Path.home() / ".codex" / "plugins" / "cache" / ...` — a path specific to a
  Codex CLumn install that will essentially never exist in this project's
  environment. This slice reads `config["paths"].get("documents_scripts_dir")`
  instead — legacy's own `_computed_paths()` already exposes this exact value
  under that key when going through full config resolution, so this is not
  an invented config concept, just resolving the existing one through
  config instead of a hardcoded module constant (consistent with this
  migration's "config-as-dict, no hidden globals" convention).
- **No stub functions for the excluded PNG renderers (user decision,
  2026-07-01): omit them entirely.** Unlike Slice 11a's `_stub` placeholders
  (which existed because *other, in-scope* code in the same slice needed a
  syntactically valid call target pending a same-migration follow-up),
  `render_docx_pages`/`render_pdf_with_pypdfium` are never getting a
  drop-in replacement under these exact signatures — the roadmap says "will
  be reimplemented differently later," implying a different shape entirely.
  `QaService.qa_docx` inlines `pngs: list[Path] = []` directly, with a
  comment citing this decision, rather than adding two placeholder functions
  nothing will ever "unstub."

### What is ported in Slice 12 (verbatim except where a design decision says
otherwise, legacy 2862–3079 minus the PNG-rendering exclusion)

- `qa_docx` (2862–2889) — becomes `QaService.qa_docx`, verbatim control flow
  except the PNG branch (per the strict-mode decision above, the branch is
  unconditionally taken, not removed — the *outcome* is identical to legacy
  running in an environment where PNG rendering was never available).
- `run_documents_audits` (2892–2920) — becomes
  `LibreOfficeQaAdapter.run_documents_audits`, verbatim except the scripts
  directory is read from `config["paths"]["documents_scripts_dir"]` instead
  of the hardcoded `DOCUMENTS_SCRIPTS` constant.
- `ensure_child_path` (2923–2927) — verbatim, moved to `domain/qa.py`.
- `render_docx_to_pdf` (2930–2958) — becomes
  `LibreOfficeQaAdapter.render_docx_to_pdf`, verbatim except LibreOffice
  resolution uses a new `resolve_libreoffice_executable(paths)` helper
  (mirrors `resolve_pandoc_executable`'s Slice 11a shape: `shutil.which` →
  `paths.get("libreoffice_bin")` → `paths.get("libreoffice_fallbacks", [])`
  → `None`; the legacy `CODEX_RUNTIME_BIN` bundled-lookup branch is dropped,
  same precedent Slice 11a already applied to pandoc).
- `render_qa_report` (3041–3077) — verbatim, moved to `domain/qa.py`.

### Already satisfied — not re-ported here

- `format_audit_docx` (legacy 2016) → `FormatAuditService.audit_format`
  (`docs.application.format_audit`, Slice 10). `qa_docx`'s call site is
  rewritten from the legacy free function to
  `self.format_audit_service.audit_format(docx_path, config, strict=strict)`.
- `Issue`/`ReviewResult` (legacy 155–181) → `docs.domain.review` (Slice 3).
  Confirmed `ReviewResult` is `@dataclass(frozen=True)` but its single field
  is a mutable `list[Issue]` — `audit.issues.append(...)` (legacy's own
  in-place mutation, preserved verbatim) works because only reassigning the
  dataclass's own fields is frozen, not mutating an object a field points to.
- `resolve_pandoc_executable` shape (Slice 11a,
  `python_docx_assembly_adapter.py`) — not reused directly (pandoc-specific),
  but its exact probing order is the template `resolve_libreoffice_executable`
  copies (Design Decision 1).

### Out of scope (confirmed, not re-derived)

- `render_docx_pages` (2961–3008) / `render_pdf_with_pypdfium` (3011–3038) —
  permanently excluded per the 2026-06-21 user decision (see above). No stub
  placeholders added (2026-07-01 decision).
- `run_doctor`/`Check`/`DoctorResult`/`apply_corrections`/`parse_simple_yaml`
  — Slice 13.
- `run_pipeline`/`verify_all`/`log_run` — Slice 14.
- Any CLI surface — Slice 15.

## Legacy code blocks (verbatim — as supplied, reused without modification
except where noted above)

### `qa_docx` (lines 2862–2889)

```python
def qa_docx(config: dict[str, Any], docx_path: Path, strict: bool = False) -> Path:
    if not docx_path.exists():
        raise FileNotFoundError(f"No existe DOCX para QA: {docx_path}")

    output_dir = Path(config["paths"]["output_qa_dir"]) / docx_path.stem
    if output_dir.exists():
        ensure_child_path(Path(config["paths"]["output_qa_dir"]), output_dir)
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_pdf = render_docx_to_pdf(config, docx_path, output_dir)

    pngs: list[Path] = []
    if strict:
        pngs = render_docx_pages(config, docx_path, output_dir)
        if not pngs:
            raise RuntimeError(f"QA estricto requiere PNG por página y no se generó ninguno en: {output_dir}")

    audit = format_audit_docx(docx_path, strict=strict, config=config)
    document_audits = run_documents_audits(config, docx_path, output_dir, strict=strict)
    if strict:
        for item in document_audits:
            if not item["ok"]:
                audit.issues.append(Issue("error", f"Auditoría Documents falló: {item['name']}"))
    report = render_qa_report(docx_path, expected_pdf, pngs, audit, document_audits)
    (output_dir / "qa-report.md").write_text(report, encoding="utf-8")
    if strict and not audit.passed:
        raise RuntimeError(f"QA estricto falló; revisar {output_dir / 'qa-report.md'}")
    return output_dir
```

### `run_documents_audits` (lines 2892–2920)

```python
def run_documents_audits(config: dict[str, Any], docx_path: Path, output_dir: Path, strict: bool = False) -> list[dict[str, Any]]:
    if not config.get("documents_tools", {}).get("enabled", True):
        return []
    safe_scripts = ["heading_audit.py", "section_audit.py", "style_lint.py", "table_geometry.py"]
    results: list[dict[str, Any]] = []
    for script in safe_scripts:
        script_path = DOCUMENTS_SCRIPTS / script
        if not script_path.exists():
            results.append({"name": script, "ok": not strict, "stdout": "", "stderr": "script no encontrado"})
            continue
        proc = subprocess.run(
            [sys.executable, str(script_path), str(docx_path.resolve())],
            cwd=output_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        out_path = output_dir / f"documents-{script.removesuffix('.py')}.txt"
        out_path.write_text((proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
        results.append(
            {
                "name": script,
                "ok": proc.returncode == 0,
                "stdout": proc.stdout[-2000:] if proc.stdout else "",
                "stderr": proc.stderr[-2000:] if proc.stderr else "",
                "report": _as_posix(out_path),
            }
        )
    return results
```

### `ensure_child_path` (lines 2923–2927)

```python
def ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved == child_resolved or parent_resolved not in child_resolved.parents:
        raise RuntimeError(f"Ruta insegura para limpieza recursiva: {child_resolved}")
```

### `render_docx_to_pdf` (lines 2930–2958)

```python
def render_docx_to_pdf(config: dict[str, Any], docx_path: Path, output_dir: Path) -> Path:
    libreoffice = resolve_executable("soffice", LIBREOFFICE_FALLBACKS) or resolve_executable(
        "libreoffice", LIBREOFFICE_FALLBACKS
    )
    if not libreoffice:
        raise RuntimeError("LibreOffice/soffice no está disponible en PATH. Instálalo para renderizar QA visual.")

    expected_pdf = output_dir / f"{docx_path.stem}.pdf"
    if expected_pdf.exists():
        expected_pdf.unlink()
    with tempfile.TemporaryDirectory(prefix="tesina_lo_profile_") as profile:
        subprocess.run(
            [
                libreoffice,
                f"-env:UserInstallation={Path(profile).resolve().as_uri()}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    if not expected_pdf.exists() or expected_pdf.stat().st_size == 0:
        raise RuntimeError(f"LibreOffice no produjo el PDF esperado: {expected_pdf}")
    return expected_pdf
```

### `render_qa_report` (lines 3041–3077)

```python
def render_qa_report(docx_path: Path, pdf_path: Path, pngs: list[Path], audit: ReviewResult, document_audits: list[dict[str, Any]] | None = None) -> str:
    document_audits = document_audits or []
    lines = [
        "# QA DOCX",
        "",
        f"- DOCX: {docx_path}",
        f"- PDF: {pdf_path} ({pdf_path.stat().st_size if pdf_path.exists() else 0} bytes)",
        f"- PNG pages: {len(pngs)}",
        "- Índice dinámico: el campo TOC se actualiza al abrir el DOCX en Word o con Ctrl+A y F9; el render de QA puede mostrar el texto de actualización pendiente.",
        "",
        "## Auditoría de formato",
        "",
        audit.to_markdown(),
        "",
        "## Auditorías Documents",
        "",
    ]
    if document_audits:
        for item in document_audits:
            marker = "OK" if item.get("ok") else "FAIL"
            lines.append(f"- {marker} `{item.get('name')}`: {item.get('report', '')}")
    else:
        lines.append("- No ejecutadas.")
    lines.extend(
        [
            "",
        "## Checklist visual manual",
        "",
        "- [ ] Sin texto cortado o solapado.",
        "- [ ] Portada preservada y páginas no-portada con márgenes de 2.5 cm.",
        "- [ ] Paginación visible desde Introducción.",
        "- [ ] Títulos en jerarquía institucional.",
        "- [ ] Tablas sin colores y sólo líneas horizontales.",
        "- [ ] Figuras con caption inferior.",
        ]
    )
    return "\n".join(lines)
```

### `resolve_executable` (lines 2297–2307, reference only — superseded)

Cited for context only: this is the legacy general-purpose executable
resolver. Slice 11a already established that this migration does **not**
port it as-is (it dropped the `CODEX_RUNTIME_BIN` bundled-lookup branch for
`resolve_pandoc_executable`); this slice's `resolve_libreoffice_executable`
follows that same already-accepted precedent, not this legacy function.

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

## Verified context (read directly this session)

- **`src/docs/infrastructure/docx/python_docx_assembly_adapter.py`**
  (`resolve_pandoc_executable`, lines 19–30, read directly): confirmed the
  exact shape to mirror for `resolve_libreoffice_executable` —
  `shutil.which(...)` first, then `paths.get("<tool>_bin")` checked via
  `Path(...).exists() and Path(...).is_file()`, then a loop over
  `paths.get("<tool>_fallbacks", [])` with the same existence check, else
  `None`. No `CODEX_RUNTIME_BIN` branch. `paths` is the plain
  `config["paths"]` dict, not a typed model.
- **`src/docs/domain/ports/docx_audit_port.py`** (full file, 13 lines):
  confirmed the established port style — bare `Protocol`, no default
  bodies, one method per line, `from __future__ import annotations` +
  `pathlib.Path` + `typing.Any, Protocol` imports only. `QaRenderPort`
  follows this exactly.
- **`src/docs/infrastructure/docx/python_docx_audit_adapter.py`** and
  **`filesystem_source_repository.py`** (grepped for the class declaration
  line): confirmed adapters in this codebase **never** inherit from their
  Protocol (`class PythonDocxAuditAdapter:`, `class
  FilesystemSourceRepository:` — structural typing only, no `(Port)` base
  class anywhere). `LibreOfficeQaAdapter` follows this — no inheritance
  from `QaRenderPort`, and the adapter module does not import the port at
  all (only the service and tests need the port name for type hints).
- **Integration test convention, migration-wide** (confirmed via
  `docs/.superpowers/sdd/progress.md`, Slice 4 Task 4 and Slice 5 Task 4
  log entries: "using the real JsonEvidenceRepository adapter, no mocks",
  "using the real JsonSectionRepository adapter, no mocks"): every
  service-level integration test in this migration exercises a **real**
  adapter, never a hand-written fake port. `QaService`'s tests (Task 4)
  follow this — real `LibreOfficeQaAdapter` + real `PythonDocxAuditAdapter`
  wrapped in a real `FormatAuditService`, `skipif`-guarded on LibreOffice
  exactly like `DocxAssemblyService`'s tests are guarded on pandoc — not
  hand-written fake ports.
- **`src/docs/application/format_audit.py`** (full file, 18 lines):
  confirmed `FormatAuditService`'s single-port constructor
  (`def __init__(self, port: DocxAuditPort)`) and its
  existence-guard-then-wrap pattern
  (`if not docx_path.exists(): raise FileNotFoundError(...)`). `QaService`
  reuses the identical existence-guard wording style (message text differs,
  matching `qa_docx`'s own legacy message) and takes a second constructor
  argument, `format_audit_service: FormatAuditService`, mirroring
  `DocxAssemblyService.__init__(self, port, asset_service)` (Slice 11a) as
  the second "service composes service" instance in this migration.
- **`src/docs/domain/review.py`** (`Issue`/`ReviewResult`, lines 1–27): both
  are `@dataclass(frozen=True)`. `Issue(severity: str, message: str, code:
  str = "")` is positional-compatible with legacy's
  `Issue("error", f"Auditoría Documents falló: {item['name']}")` call — no
  change needed at that call site. `ReviewResult.issues` is a
  `list[Issue]` with `field(default_factory=list)`; confirmed
  `audit.issues.append(...)` is legal despite the dataclass being frozen,
  because only the dataclass's own `__setattr__` is blocked, not mutation of
  an object one of its fields references.
- **`pyproject.toml`** (confirmed): dependencies are exactly
  `defusedxml>=0.7.1`, `pydantic>=2.13.4`, `python-docx>=1.2.0`.
  `pypdfium2` is correctly absent (consistent with the PNG-rendering
  exclusion — nothing to add or remove there). No new third-party
  dependency is needed for this slice; LibreOffice is an external tool
  invoked via `subprocess`, exactly like pandoc in Slice 11a.
- **No `.codegraph` index exists** at `C:\code\harness-projects\docs` —
  confirmed absent; direct `Read`/`Grep` used throughout instead of
  `codegraph_explore`.
- **Test convention** (from Slice 11a's
  `tests/integration/test_python_docx_assembly_adapter.py`): every
  DOCX-related port in this migration is tested against its **real**
  adapter, never a hand-written fake, with
  `@pytest.mark.skipif(shutil.which("pandoc") is None, ...)` guarding
  pandoc-dependent tests. This slice extends the identical convention with
  `@pytest.mark.skipif(shutil.which("soffice") is None and
  shutil.which("libreoffice") is None, ...)` for LibreOffice-dependent
  tests — real subprocess calls, no mocking.

## Design decisions

1. **`resolve_libreoffice_executable(paths)` mirrors
   `resolve_pandoc_executable`'s exact probing order, dropping the legacy
   `CODEX_RUNTIME_BIN` bundled-lookup branch — applying an already-accepted
   precedent, not a fresh design choice.** Slice 11a's Design Decision 4
   already established that the bundled-runtime lookup is dead weight in
   this project's environment and was dropped for pandoc. The only new
   wrinkle: legacy tries **two** executable names (`"soffice"` then
   `"libreoffice"`) before falling through to configured paths — preserved
   here as `shutil.which("soffice") or shutil.which("libreoffice")`.

2. **`QaRenderPort` is a new port, not a growth of `DocxAssemblyPort` or
   `DocxAuditPort`.** `insert_toc_field` was added to `DocxAssemblyPort` in
   Slice 11b because it operates on the same artifact family via the same
   underlying tool (python-docx) as that port's other methods. LibreOffice
   PDF conversion and the Documents-scripts subprocess orchestration are a
   different external-tool family entirely (LibreOffice binary + arbitrary
   external scripts, not python-docx/zip manipulation) — a new port keeps
   `DocxAssemblyPort`/`DocxAuditPort` scoped to what they already mean.

3. **`LibreOfficeQaAdapter` is a "fat adapter" — both methods' full
   subprocess-orchestration logic lives directly in the adapter, not split
   into a thin port + application-layer judgment.** This is the same
   deliberate exception Slice 10's `PythonDocxAuditAdapter` already
   established: `render_docx_to_pdf` and `run_documents_audits` have no
   separable raw-fact/judgment boundary in legacy (they *are* the
   subprocess call plus straightforward interpretation of its exit code) —
   forcing an artificial split would just relocate the same logic behind an
   extra layer of indirection.

4. **`documents_scripts_dir` is read from `config["paths"]`, matching
   `output_qa_dir`'s treatment.** Neither key exists anywhere in
   `src/docs` yet (confirmed via grep) and neither is backed by a
   `Workspace` property — both are consumed as raw `config["paths"][...]`
   dict lookups, exactly like `DocxAssemblyService.build()` already does
   for `config["paths"]["output_draft_dir"]`. No `Workspace` change is
   implied or needed; this is a continuation of the established
   config-as-dict convention, not a new pattern.

5. **`ensure_child_path` and `render_qa_report` live together in a new
   `domain/qa.py`, both pure, both independently unit-tested.** This
   mirrors `docx_structure.py`'s precedent of giving small pure Path/text
   guards their own testable domain unit rather than burying them as
   private helpers inside the application service.

6. **`QaService.qa_docx`'s PNG branch is inlined, not routed through a
   stubbed function.** Per the 2026-07-01 user decision: `pngs: list[Path]
   = []` is set directly in the service body, with a comment citing the
   scope exclusion and its date. The subsequent `if strict and not pngs:
   raise RuntimeError(...)` reproduces legacy's `if strict: pngs =
   render_docx_pages(...); if not pngs: raise ...` exactly in observable
   behavior — under `strict=True`, both versions always raise before
   reaching the format audit, since PNG rendering is unavailable in both
   (legacy in an environment lacking the render pipeline; here, always).

7. **Test strategy: real LibreOffice subprocess calls, `skipif`-guarded,
   no mocking — extending Slice 11a's Design Decision 7 to a new external
   tool.** `run_documents_audits`' "script not found" branch is exercised
   directly (no scripts directory configured / a configured directory
   missing the script) rather than mocked, since it requires no external
   tool to hit deterministically.

## Task breakdown

### Task 1 — Pure domain functions (`domain/qa.py`)

**Files to create/modify:**
- Create `src/docs/domain/qa.py`.
- Create `tests/unit/domain/test_qa.py`.

**Verbatim legacy reference:** `render_qa_report` (3041–3077) and
`ensure_child_path` (2923–2927), both verbatim, no reshaping.

**Planned implementation:**

```python
# src/docs/domain/qa.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from docs.domain.review import ReviewResult


def ensure_child_path(parent: Path, child: Path) -> None:
    parent_resolved = parent.resolve()
    child_resolved = child.resolve()
    if parent_resolved == child_resolved or parent_resolved not in child_resolved.parents:
        raise RuntimeError(f"Ruta insegura para limpieza recursiva: {child_resolved}")


def render_qa_report(
    docx_path: Path,
    pdf_path: Path,
    pngs: list[Path],
    audit: ReviewResult,
    document_audits: list[dict[str, Any]] | None = None,
) -> str:
    document_audits = document_audits or []
    lines = [
        "# QA DOCX",
        "",
        f"- DOCX: {docx_path}",
        f"- PDF: {pdf_path} ({pdf_path.stat().st_size if pdf_path.exists() else 0} bytes)",
        f"- PNG pages: {len(pngs)}",
        "- Índice dinámico: el campo TOC se actualiza al abrir el DOCX en Word o con Ctrl+A y F9; el render de QA puede mostrar el texto de actualización pendiente.",
        "",
        "## Auditoría de formato",
        "",
        audit.to_markdown(),
        "",
        "## Auditorías Documents",
        "",
    ]
    if document_audits:
        for item in document_audits:
            marker = "OK" if item.get("ok") else "FAIL"
            lines.append(f"- {marker} `{item.get('name')}`: {item.get('report', '')}")
    else:
        lines.append("- No ejecutadas.")
    lines.extend(
        [
            "",
            "## Checklist visual manual",
            "",
            "- [ ] Sin texto cortado o solapado.",
            "- [ ] Portada preservada y páginas no-portada con márgenes de 2.5 cm.",
            "- [ ] Paginación visible desde Introducción.",
            "- [ ] Títulos en jerarquía institucional.",
            "- [ ] Tablas sin colores y sólo líneas horizontales.",
            "- [ ] Figuras con caption inferior.",
        ]
    )
    return "\n".join(lines)
```

**Planned test code:**

```python
# tests/unit/domain/test_qa.py
from __future__ import annotations

from pathlib import Path

import pytest

from docs.domain.qa import ensure_child_path, render_qa_report
from docs.domain.review import Issue, ReviewResult


def test_ensure_child_path_accepts_a_real_child(tmp_path):
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    ensure_child_path(parent, child)  # must not raise


def test_ensure_child_path_rejects_identical_paths(tmp_path):
    parent = tmp_path / "same"
    parent.mkdir()
    with pytest.raises(RuntimeError, match="Ruta insegura"):
        ensure_child_path(parent, parent)


def test_ensure_child_path_rejects_a_non_child_path(tmp_path):
    parent = tmp_path / "parent"
    other = tmp_path / "other"
    parent.mkdir()
    other.mkdir()
    with pytest.raises(RuntimeError, match="Ruta insegura"):
        ensure_child_path(parent, other)


def test_render_qa_report_includes_pdf_size_and_png_count(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert f"- PDF: {pdf_path} ({pdf_path.stat().st_size} bytes)" in report
    assert "- PNG pages: 0" in report


def test_render_qa_report_reports_missing_pdf_as_zero_bytes(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "missing.pdf"
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert f"- PDF: {pdf_path} (0 bytes)" in report


def test_render_qa_report_embeds_format_audit_markdown(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    audit = ReviewResult([Issue("error", "Margen incorrecto")])
    report = render_qa_report(docx_path, pdf_path, [], audit)
    assert audit.to_markdown() in report


def test_render_qa_report_lists_document_audits_with_ok_and_fail_markers(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    document_audits = [
        {"name": "heading_audit.py", "ok": True, "report": "out/heading.txt"},
        {"name": "section_audit.py", "ok": False, "report": "out/section.txt"},
    ]
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult(), document_audits)
    assert "- OK `heading_audit.py`: out/heading.txt" in report
    assert "- FAIL `section_audit.py`: out/section.txt" in report


def test_render_qa_report_notes_no_document_audits_when_list_is_empty(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult(), [])
    assert "- No ejecutadas." in report


def test_render_qa_report_includes_manual_checklist_items(tmp_path):
    docx_path = tmp_path / "doc.docx"
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    report = render_qa_report(docx_path, pdf_path, [], ReviewResult())
    assert "- [ ] Sin texto cortado o solapado." in report
    assert "- [ ] Figuras con caption inferior." in report
```

**Expected test count:** ~10 unit tests. Self-reviewable — pure functions,
no I/O beyond `Path.resolve()`/`Path.stat()` reads and `tmp_path` fixtures.

---

### Task 2 — `QaRenderPort` (new port)

**Files to create/modify:**
- Create `src/docs/domain/ports/qa_render_port.py`.

**Verbatim legacy reference:** none — this is a new Protocol capturing the
two external-tool capabilities `render_docx_to_pdf`/`run_documents_audits`
need, per Design Decision 2. No behavior to test (per the Slice 4/5 Task 2
precedent: bare Protocols get no dedicated test file).

**Planned implementation:**

```python
# src/docs/domain/ports/qa_render_port.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class QaRenderPort(Protocol):
    def render_docx_to_pdf(self, config: dict[str, Any], docx_path: Path, output_dir: Path) -> Path: ...
    def run_documents_audits(
        self, config: dict[str, Any], docx_path: Path, output_dir: Path, strict: bool
    ) -> list[dict[str, Any]]: ...
```

**Expected test count:** 0 new tests by design (matches Slice 4 Task 2 /
Slice 5 Task 2 precedent). Self-reviewable — diff against this plan's code
block should be byte-for-byte.

---

### Task 3 — `LibreOfficeQaAdapter` (first LibreOffice subprocess call in
this migration)

**Files to create/modify:**
- Create `src/docs/infrastructure/docx/libreoffice_qa_adapter.py`.
- Create `tests/integration/test_libreoffice_qa_adapter.py`.

**Verbatim legacy reference:** `render_docx_to_pdf` (2930–2958) verbatim
except LibreOffice resolution goes through the new
`resolve_libreoffice_executable(paths)` (Design Decision 1) instead of
`resolve_executable(name, fallbacks)`. `run_documents_audits` (2892–2920)
verbatim except the scripts directory comes from
`config["paths"].get("documents_scripts_dir")` instead of the hardcoded
`DOCUMENTS_SCRIPTS` constant (Design Decision 4).

**Planned implementation:**

```python
# src/docs/infrastructure/docx/libreoffice_qa_adapter.py
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def resolve_libreoffice_executable(paths: dict[str, Any]) -> str | None:
    resolved = shutil.which("soffice") or shutil.which("libreoffice")
    if resolved:
        return resolved
    configured = paths.get("libreoffice_bin")
    if configured and Path(configured).exists() and Path(configured).is_file():
        return str(configured)
    for candidate in paths.get("libreoffice_fallbacks", []):
        candidate_path = Path(candidate)
        if candidate_path.exists() and candidate_path.is_file():
            return str(candidate_path)
    return None


class LibreOfficeQaAdapter:
    def render_docx_to_pdf(self, config: dict[str, Any], docx_path: Path, output_dir: Path) -> Path:
        paths = config.get("paths", {})
        libreoffice = resolve_libreoffice_executable(paths)
        if not libreoffice:
            raise RuntimeError(
                "LibreOffice/soffice no está disponible en PATH. Instálalo para renderizar QA visual."
            )

        expected_pdf = output_dir / f"{docx_path.stem}.pdf"
        if expected_pdf.exists():
            expected_pdf.unlink()
        with tempfile.TemporaryDirectory(prefix="docs_lo_profile_") as profile:
            subprocess.run(
                [
                    libreoffice,
                    f"-env:UserInstallation={Path(profile).resolve().as_uri()}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(output_dir),
                    str(docx_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        if not expected_pdf.exists() or expected_pdf.stat().st_size == 0:
            raise RuntimeError(f"LibreOffice no produjo el PDF esperado: {expected_pdf}")
        return expected_pdf

    def run_documents_audits(
        self, config: dict[str, Any], docx_path: Path, output_dir: Path, strict: bool = False
    ) -> list[dict[str, Any]]:
        if not config.get("documents_tools", {}).get("enabled", True):
            return []
        scripts_dir_value = config.get("paths", {}).get("documents_scripts_dir")
        scripts_dir = Path(scripts_dir_value) if scripts_dir_value else None
        safe_scripts = ["heading_audit.py", "section_audit.py", "style_lint.py", "table_geometry.py"]
        results: list[dict[str, Any]] = []
        for script in safe_scripts:
            script_path = scripts_dir / script if scripts_dir else None
            if script_path is None or not script_path.exists():
                results.append({"name": script, "ok": not strict, "stdout": "", "stderr": "script no encontrado"})
                continue
            proc = subprocess.run(
                [sys.executable, str(script_path), str(docx_path.resolve())],
                cwd=output_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            out_path = output_dir / f"documents-{script.removesuffix('.py')}.txt"
            out_path.write_text(
                (proc.stdout or "") + ("\nSTDERR:\n" + proc.stderr if proc.stderr else ""), encoding="utf-8"
            )
            results.append(
                {
                    "name": script,
                    "ok": proc.returncode == 0,
                    "stdout": proc.stdout[-2000:] if proc.stdout else "",
                    "stderr": proc.stderr[-2000:] if proc.stderr else "",
                    "report": out_path.resolve().as_posix(),
                }
            )
        return results
```

**Planned test code:**

```python
# tests/integration/test_libreoffice_qa_adapter.py
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from docx import Document

from docs.infrastructure.docx.libreoffice_qa_adapter import (
    LibreOfficeQaAdapter,
    resolve_libreoffice_executable,
)

_HAS_LIBREOFFICE = shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def test_resolve_libreoffice_executable_prefers_path_lookup():
    if not _HAS_LIBREOFFICE:
        pytest.skip("LibreOffice not installed")
    assert resolve_libreoffice_executable({}) is not None


def test_resolve_libreoffice_executable_falls_back_to_configured_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fake_bin = tmp_path / "soffice.exe"
    fake_bin.write_text("", encoding="utf-8")
    assert resolve_libreoffice_executable({"libreoffice_bin": str(fake_bin)}) == str(fake_bin)


def test_resolve_libreoffice_executable_returns_none_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert resolve_libreoffice_executable({}) is None


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_render_docx_to_pdf_produces_a_non_empty_pdf(tmp_path):
    docx_path = tmp_path / "doc.docx"
    Document().save(docx_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    pdf_path = LibreOfficeQaAdapter().render_docx_to_pdf({"paths": {}}, docx_path, output_dir)

    assert pdf_path == output_dir / "doc.pdf"
    assert pdf_path.stat().st_size > 0


def test_render_docx_to_pdf_raises_when_libreoffice_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "docs.infrastructure.docx.libreoffice_qa_adapter.resolve_libreoffice_executable", lambda paths: None
    )
    docx_path = tmp_path / "doc.docx"
    Document().save(docx_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    with pytest.raises(RuntimeError, match="LibreOffice/soffice no está disponible"):
        LibreOfficeQaAdapter().render_docx_to_pdf({"paths": {}}, docx_path, output_dir)


def test_run_documents_audits_returns_empty_list_when_disabled(tmp_path):
    result = LibreOfficeQaAdapter().run_documents_audits(
        {"documents_tools": {"enabled": False}}, tmp_path / "doc.docx", tmp_path
    )
    assert result == []


def test_run_documents_audits_marks_missing_scripts_dir_as_not_found_non_strict(tmp_path):
    result = LibreOfficeQaAdapter().run_documents_audits({}, tmp_path / "doc.docx", tmp_path, strict=False)
    assert len(result) == 4
    assert all(item["ok"] is True and item["stderr"] == "script no encontrado" for item in result)


def test_run_documents_audits_marks_missing_scripts_dir_as_failing_strict(tmp_path):
    result = LibreOfficeQaAdapter().run_documents_audits({}, tmp_path / "doc.docx", tmp_path, strict=True)
    assert all(item["ok"] is False for item in result)


def test_run_documents_audits_runs_a_real_configured_script_and_captures_output(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "heading_audit.py"
    script.write_text("print('ok from heading_audit')\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    docx_path = tmp_path / "doc.docx"
    Document().save(docx_path)

    result = LibreOfficeQaAdapter().run_documents_audits(
        {"paths": {"documents_scripts_dir": str(scripts_dir)}}, docx_path, output_dir
    )

    heading_result = next(item for item in result if item["name"] == "heading_audit.py")
    assert heading_result["ok"] is True
    assert "ok from heading_audit" in heading_result["stdout"]
    assert Path(heading_result["report"]).exists()
```

**Expected test count:** ~9 integration tests (3 skipif-guarded on
LibreOffice being installed, 6 that need no external tool). **Highest-risk
task in this slice** — needs implementer + fresh-context reviewer. The
reviewer should specifically verify: (a) the LibreOffice-unavailable test
actually exercises the raise path without needing LibreOffice installed
(via monkeypatching the resolver, not skipping), (b) the "script not found"
branch's `not strict` vs `strict` polarity matches legacy exactly (non-strict
reports `ok: True` for a missing script; strict reports `ok: False`), (c) the
real-script-execution test's captured `stdout`/`report` path are genuinely
read back from disk, not asserted against the in-memory `proc` object only.

---

### Task 4 — `QaService.qa_docx` (composes `QaRenderPort` + `FormatAuditService`)

**Files to create/modify:**
- Create `src/docs/application/qa.py`.
- Create `tests/integration/test_qa_service.py`.

**Verbatim legacy reference:** `qa_docx` (2862–2889), verbatim control flow
except: (a) the format-audit call site is rewritten to
`self.format_audit_service.audit_format(docx_path, config, strict=strict)`,
(b) the PNG branch is inlined per Design Decision 6 (`pngs: list[Path] =
[]`, no `render_docx_pages` call — under `strict=True` this still always
raises, matching legacy's observable behavior in an environment without PNG
rendering).

**Planned implementation:**

```python
# src/docs/application/qa.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from docs.application.format_audit import FormatAuditService
from docs.domain.ports.qa_render_port import QaRenderPort
from docs.domain.qa import ensure_child_path, render_qa_report
from docs.domain.review import Issue


class QaService:
    def __init__(self, port: QaRenderPort, format_audit_service: FormatAuditService) -> None:
        self.port = port
        self.format_audit_service = format_audit_service

    def qa_docx(self, config: dict[str, Any], docx_path: Path, strict: bool = False) -> Path:
        if not docx_path.exists():
            raise FileNotFoundError(f"No existe DOCX para QA: {docx_path}")

        output_dir = Path(config["paths"]["output_qa_dir"]) / docx_path.stem
        if output_dir.exists():
            ensure_child_path(Path(config["paths"]["output_qa_dir"]), output_dir)
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        expected_pdf = self.port.render_docx_to_pdf(config, docx_path, output_dir)

        # PNG-per-page rendering is permanently out of scope (user decision,
        # 2026-06-21) — will be reimplemented differently later. Verbatim
        # strict-mode consequence preserved: strict QA still requires PNG
        # evidence and therefore always raises here until that capability
        # lands under a future, differently-shaped slice.
        pngs: list[Path] = []
        if strict and not pngs:
            raise RuntimeError(f"QA estricto requiere PNG por página y no se generó ninguno en: {output_dir}")

        audit = self.format_audit_service.audit_format(docx_path, config, strict=strict)
        document_audits = self.port.run_documents_audits(config, docx_path, output_dir, strict)
        if strict:
            for item in document_audits:
                if not item["ok"]:
                    audit.issues.append(Issue("error", f"Auditoría Documents falló: {item['name']}"))
        report = render_qa_report(docx_path, expected_pdf, pngs, audit, document_audits)
        (output_dir / "qa-report.md").write_text(report, encoding="utf-8")
        if strict and not audit.passed:
            raise RuntimeError(f"QA estricto falló; revisar {output_dir / 'qa-report.md'}")
        return output_dir
```

**Planned test code:**

Per the migration-wide "real adapter, no mocked ports" convention (Slice 4
Task 4 / Slice 5 Task 4 precedent), these tests use the real
`LibreOfficeQaAdapter` (Task 3) and the real `PythonDocxAuditAdapter`
(Slice 10) wrapped in a real `FormatAuditService` — not hand-written fakes.
Tests that need an actual rendered PDF, or the exact PNG-shortfall message
(only reachable once `render_docx_to_pdf` has succeeded), are `skipif`-guarded
on LibreOffice. The missing-file guard and a bare "strict still raises"
assertion (which may be satisfied either by the PNG guard or by
`render_docx_to_pdf` itself raising first, per its unconditional legacy
ordering — see Task 4's Planned implementation) do not need the guard.

```python
# tests/integration/test_qa_service.py
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from docx import Document

from docs.application.format_audit import FormatAuditService
from docs.application.qa import QaService
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter

_HAS_LIBREOFFICE = shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _make_service() -> QaService:
    return QaService(LibreOfficeQaAdapter(), FormatAuditService(PythonDocxAuditAdapter()))


def _make_docx(tmp_path: Path) -> Path:
    path = tmp_path / "doc.docx"
    Document().save(path)
    return path


def test_qa_docx_raises_when_docx_missing(tmp_path):
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}
    with pytest.raises(FileNotFoundError, match="No existe DOCX para QA"):
        service.qa_docx(config, tmp_path / "missing.docx")


@pytest.mark.skipif(_HAS_LIBREOFFICE, reason="requires LibreOffice to be unavailable")
def test_qa_docx_strict_raises_when_libreoffice_unavailable(tmp_path):
    # render_docx_to_pdf runs first (Design Decision 6: render-before-guard
    # order matches legacy), so without LibreOffice it raises its own
    # RuntimeError before the code ever reaches the PNG guard.
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    with pytest.raises(RuntimeError):
        service.qa_docx(config, docx_path, strict=True)


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_strict_always_raises_since_png_rendering_is_out_of_scope(tmp_path):
    # Only reachable when render_docx_to_pdf succeeds (i.e. LibreOffice is
    # installed): the PNG-per-page guard still always raises in strict mode.
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    with pytest.raises(RuntimeError, match="QA estricto requiere PNG por página"):
        service.qa_docx(config, docx_path, strict=True)


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_non_strict_writes_report_and_returns_output_dir(tmp_path):
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}

    output_dir = service.qa_docx(config, docx_path, strict=False)

    assert output_dir == tmp_path / "qa" / "doc"
    report_text = (output_dir / "qa-report.md").read_text(encoding="utf-8")
    assert "# QA DOCX" in report_text
    assert (output_dir / "doc.pdf").stat().st_size > 0


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_cleans_up_a_pre_existing_output_dir(tmp_path):
    docx_path = _make_docx(tmp_path)
    output_dir = tmp_path / "qa" / "doc"
    output_dir.mkdir(parents=True)
    stale_file = output_dir / "stale.txt"
    stale_file.write_text("old", encoding="utf-8")

    service = _make_service()
    config = {"paths": {"output_qa_dir": str(tmp_path / "qa")}}
    service.qa_docx(config, docx_path, strict=False)

    assert not stale_file.exists()
    assert (output_dir / "qa-report.md").exists()


@pytest.mark.skipif(not _HAS_LIBREOFFICE, reason="LibreOffice not installed")
def test_qa_docx_reports_configured_documents_audit_results(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "heading_audit.py").write_text("print('ok')\n", encoding="utf-8")
    docx_path = _make_docx(tmp_path)
    service = _make_service()
    config = {
        "paths": {
            "output_qa_dir": str(tmp_path / "qa"),
            "documents_scripts_dir": str(scripts_dir),
        }
    }

    output_dir = service.qa_docx(config, docx_path, strict=False)

    report_text = (output_dir / "qa-report.md").read_text(encoding="utf-8")
    assert "- OK `heading_audit.py`" in report_text
    assert "- OK `section_audit.py`" in report_text  # not found -> ok under non-strict
```

**Expected test count:** ~6 integration tests (2 runnable without
LibreOffice — the missing-file guard and the LibreOffice-unavailable strict
raise — 4 `skipif`-guarded on LibreOffice being installed). Needs
implementer + fresh-context reviewer — this is the composition point
(mirrors 11b's Task 5/11a's Task 4 review posture): the reviewer should
specifically confirm `render_docx_to_pdf` genuinely runs **before** the
strict-mode PNG guard (matching legacy's unconditional render call, Design
Decision 6) rather than the other way around, that the format audit/the
Documents audits only run after both, and that the non-strict path's
report/cleanup/return-value behavior matches legacy line-for-line against a
real rendered PDF, not a synthetic one.

## Global constraints

- Config stays a plain `dict[str, Any]` everywhere — no typed `Config`
  model introduced by this slice, consistent with every prior slice.
- No new third-party pip dependency. LibreOffice remains an external,
  non-pip tool (like pandoc), invoked via `subprocess`.
- `domain/qa.py` imports only `pathlib`, `typing`, and
  `docs.domain.review` — no application/infrastructure imports (hexagonal
  boundary, verified by grep before merge).
- `QaRenderPort` stays a bare `Protocol` — no default method bodies.
- `LibreOfficeQaAdapter` may import `subprocess`/`shutil`/`sys`/`tempfile`
  freely (infrastructure layer); `application/qa.py` may do direct
  filesystem I/O (`mkdir`, `shutil.rmtree`, `write_text`) without a port,
  matching `DocxAssemblyService`'s already-accepted precedent — only
  external-tool subprocess calls are pushed behind `QaRenderPort`.
- Every task is TDD: failing test first, minimal implementation, full
  suite run (`rtk pytest -q`) after each task, commit per task.
- `render_docx_pages`/`render_pdf_with_pypdfium` must not appear anywhere in
  `src/docs` after this slice (grep-verifiable) — no stub, no partial port.

## Risks and open judgment calls

All three judgment calls flagged during research were resolved by explicit
user decision before this plan was written (2026-07-01):

1. **RESOLVED — strict-mode PNG requirement stays verbatim (always
   raises).** See "Overview / Scope" and Design Decision 6. Downstream
   effect: `qa_docx(strict=True)` is a documented non-functional path until
   a future, differently-shaped slice reimplements PNG rendering; `qa_docx`
   with `strict=False` is the fully working path this slice delivers.
2. **RESOLVED — `documents_scripts_dir` routes through `config["paths"]`,
   not a hardcoded Codex path.** See Design Decision 4. Downstream effect:
   in any environment without that config key set, `run_documents_audits`
   reports every script as "no encontrado" — a graceful, already-legacy
   fallback behavior, just reached via a different (and more portable)
   input path.
3. **RESOLVED — no `_stub`-suffixed placeholders for the two excluded PNG
   functions.** See Design Decision 6 and the Overview. Downstream effect:
   a future PNG-rendering slice will need to *add* the PNG branch back into
   `QaService.qa_docx` (replacing the inlined `pngs: list[Path] = []` and
   the always-true guard), rather than swap out an existing stub function —
   flagged here so that future slice's author isn't surprised there's no
   stub seam waiting for it, unlike Slice 11a → 11b's handoff.
4. **Open, low-stakes: task splitting (4 tasks, not 3).** Task 1 bundles
   `ensure_child_path` and `render_qa_report` into a single task since both
   are small, pure, and land in the same new file — a plausible reviewer
   could ask to split them, but there's no risk-shape difference between
   them (both are simple, fully covered by unit tests) that would justify a
   fresh-context reviewer approving one while rejecting the other. Flagged
   for the assigned reviewer's judgment, not treated as load-bearing.
