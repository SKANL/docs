# Slice 15 — CLI Surface · Implementation Plan

Branch: `design/harness-migration`
Legacy reference: `tesina_harness.py` lines 3355–3525 (`command_*` flat
commands: `doctor`/`collect-sources`/`build-rules`/`review-rules`/
`collect-issues`/`collect-code-evidence`/`build-ledger`/`build-section`/
`pack-context`/`review-section`/`review-document`/`build-docx`/`qa-docx`/
`format-audit-docx`/`apply-corrections`/`stamp`/`pipeline`/`verify`/
`stamp-section`/`history`), 3593–3691 (`template`/`doc`/`asset` command
groups + their `create_document`/`delete_document`/`rename_document`
helpers), 3694–3768 (`context` command group), 3771–3937 (`build_parser`,
the argparse tree), 3940–3951 (`main`). Plus the two CLI-layer helpers every
command leans on: `resolve_config` (351–362) and `_emit_result` (3152–3157),
and — transitively — the config-assembly machinery `resolve_config` depends
on that has never been migrated (`load_document` 329–348, `_deep_merge` 223–230,
`_expand_tokens` 196–205, `_standard_tokens` 212–220, `_computed_paths`
297–322). See Judgment call 1.

## Overview / Scope

**This is the FINALE of the migration.** Slice 15 is the fourteenth-and-last
slice: it ports the entire user-facing surface of `tesina_harness.py` — 37
`command_*` functions and the argparse tree — onto **Typer**, wiring each
command to the real application services shipped in Slices 1–14. After this
slice, `python -m docs` (or the `docs` console script) reproduces every legacy
subcommand, and the monolith has been fully replaced by the
domain/application/infrastructure/**cli** hexagon the roadmap set out to build.

The CLI is a **thin adapter** and nothing more. Every command does exactly
three things, in order: (1) resolve inputs (the active/target document's
`config` dict + `Template`, plus flags), (2) call **one** application-service
method (or one pure domain function, for `review-rules`), (3) format the
returned value object to stdout as markdown or `--json`. No business logic
lives in the CLI layer — that boundary discipline, held across all 14 prior
slices, is the whole point of having spent 14 slices extracting the services
this slice merely calls.

Five things happen in this slice:

1. Adds the project's first third-party CLI dependency, **`typer`**
   (`uv add typer`), and a console-script entrypoint (`docs = "docs.cli.main:main"`).
   Task 1 only.
2. Builds the CLI **composition root** (`src/docs/cli/_shared.py`): a `Deps`
   container that constructs the `Workspace` + every repository adapter +
   every application service exactly as `tests/integration/*`'s `_service()`
   helpers already do by hand, plus the two shared helpers every command
   needs — `resolve_context(...)` (the migrated `resolve_config` equivalent,
   see Judgment call 1) and `emit_result(...)` (the migrated `_emit_result`).
3. Builds the Typer **app** (`src/docs/cli/main.py`): a global `--doc` option,
   the 20 flat commands, and the four nested command groups (`template`,
   `doc`, `asset`, `context`) as Typer sub-apps.
4. Wires all 37 commands to the real service methods read from
   `src/docs/application/*` (Tasks 1–8).
5. Surfaces the two known, already-decided gaps cleanly rather than faking
   them: `build-section` (Slice 6/8/14's unmodeled `source_hash`/`prompt_hash`,
   Judgment call 3) and `context elicit`'s interactive-TTY branch (never
   migrated, Judgment call 4).

### Judgment calls resolved before writing task code (all made by the plan author — this run is unattended; each is the most defensible reading of what's already shipped, not a guess)

1. **The config-assembly pipeline is new CLI-layer groundwork this slice
   must add — it is not scope creep, and it is the single load-bearing
   prerequisite for every other command.** Every application service consumes
   a flat `config: dict[str, Any]` and reads keys like `config["paths"]
   ["rules_manifest"]`, `config["sections"]`, `config["evidence_sources"]`,
   `config["privacy"]`. **Confirmed by grep: nothing in `src/docs` builds
   that dict.** Every one of the 21 existing `tests/integration/*` files
   constructs `config` by hand in a fixture. Legacy assembled it in
   `resolve_config` (351–362) → `load_document` (329–348), which deep-merges
   the raw template JSON under the raw `document.json`, token-expands the
   result, then overlays per-document computed paths. Slices 1–14 each shipped
   a service that *requires* this dict but every one deferred building the
   assembler to "the CLI" (exactly the deferral pattern Slice 14's Judgment
   call 1 used for `resolve_normative_settings`). Slice 15's commands are the
   first — and only — callers that must turn a `doc_id` into a live `config`,
   so this is the first place the assembler is genuinely load-bearing.
   Decision: port it now as `Deps.resolve_context(doc_id) -> ResolvedContext`
   (holding `doc_id`, `config: dict`, `template: Template`) in the CLI layer,
   reusing the already-migrated `JsonDocumentRepository.read_document` /
   `load_template` ports to read the two JSON documents (no new file I/O
   outside a port), a verbatim port of legacy `_deep_merge`/`_expand_tokens`,
   and a `_computed_paths` reproduction scoped to the per-document
   `Workspace.doc_root(doc_id)` subtree. This lands in `cli/` (composition
   layer — it is exactly the wiring a composition root exists to do) and is
   reused read-only by Tasks 2–8.
2. **The harness-global path/token constants have no library equivalent and
   are dropped or made per-document — same call every prior slice made for
   `REPO_ROOT`/`RUNS_DIR`/`CODEX_RUNTIME_BIN`.** Legacy `_computed_paths`
   (297–322) and `_standard_tokens` (212–220) hardcode `REPO_ROOT`,
   `TESINA_ROOT`, `HARNESS_ROOT`, `DOCUMENTS_SCRIPTS`, `DOCUMENTS_RENDER_DOCX`
   — "the script's own location on disk," which does not exist for an
   installed library (Slice 7 Design Decision 4, reapplied; Slice 12/13 already
   dropped the Documents-plugin-cache path and PNG pipeline for the same
   reason). Decision: (a) the `Workspace` roots (`documents_dir`,
   `templates_dir`) come from env vars `DOCS_DOCUMENTS_DIR` / `DOCS_TEMPLATES_DIR`
   with cwd-relative defaults (`./documents`, `./templates`) — a testable,
   injectable composition-root concern; (b) `repo_root` becomes a
   caller-supplied `--repo-root` option (default `Path.cwd()`) on the four
   commands whose services already require it as a parameter (`pipeline`,
   `verify`, `collect-issues`, `collect-code-evidence`), mirroring
   `PipelineService.run_pipeline`'s existing `repo_root: Path` signature; (c)
   `prompts_dir` defaults to the per-document `doc_root/prompts` (per-document
   convention, Slice 14 Judgment call 6) but is still overridable by any
   `paths.prompts_dir` a template/document sets; (d) legacy's `{repo_root}`/
   `{harness_root}`-style template tokens are expanded against a token map
   built from the resolved workspace/cwd, and any unresolved harness token is
   left literal (computed paths always win the final overlay, exactly as in
   legacy `load_document` 343–346).
3. **`build-section` surfaces the unmodeled-`source_hash`/`prompt_hash` gap
   as a clean CLI error — it does not silently fake or "fix" it.** This is
   the identical gap Slice 14 Judgment call 3 documented: `ReviewService.
   build_section` (Slice 8) takes `body`, `source_hash`, `prompt_hash`, and
   three other hashes as **required** parameters, because computing them needs
   a draft renderer plus a `prompts_dir`-scoped prompt-hashing concept this
   migration has never modeled (deferred in Slice 6, reconfirmed in Slice 8
   and Slice 14 — grepped again this session, still absent). Legacy
   `command_build_section` (3407–3411) called a self-contained
   `build_section(config, section_id)` that rendered the body and computed
   those hashes internally; that function was never ported. Decision: the
   `build-section` command raises a clean `typer.Exit(code=1)` after printing
   a one-line explanation to stderr (the same message
   `PipelineService`'s `stage_build_sections` raises), citing Slice 6/8/14.
   It does NOT call `ReviewService.build_section` with faked hashes. This is a
   real, currently-permanent limitation surfaced honestly, closeable later
   without touching Slice 15's shape once a future slice models
   draft-rendering + `prompts_dir`.
4. **`context elicit` drops the interactive-TTY branch entirely and always
   writes the requests questionnaire — the stdin Q&A loop was never migrated
   and has no place in a testable hexagonal CLI.** Legacy
   `command_context_elicit` (3713–3723) branched on `sys.stdin.isatty()`:
   the TTY branch called `elicit_interactive` (legacy 845+, a blocking
   `input()` loop), the non-TTY branch called `write_requests_file`.
   `elicit_interactive` was **never ported to any service** (grep-confirmed);
   it is pure terminal I/O. The non-TTY branch's building block *is* migrated
   — `context_markdown.render_requests` (Slice 2) — but no service composes it
   into a "write the questionnaire" operation. Decision: (a) add one small
   application method `ContextService.write_requests_file(doc_id, template,
   only_topic="") -> Path` composing the already-migrated `status` +
   `render_requests` + `ContextRepository.write_requests` (business logic
   stays in the application layer, CLI stays thin); (b) `context elicit`
   always calls it — the interactive `isatty()`/`input()` loop is explicitly
   out of scope for this migration (UI concern, no testable seam); (c) the
   legacy `--requests` flag is kept as an accepted-but-inert option for
   command-line compatibility, since the questionnaire is now the only
   behavior. Flagged in Risks.
5. **Exit codes are preserved verbatim from legacy per command.** `doctor`
   returns `0` on pass / `2` on fail (3359). `review-rules`/`review-section`/
   `review-document`/`pipeline`/`verify`/`format-audit-docx` return `0`/`1`
   (3380, 3434, 3441, 3463, 3491, 3500). `context status` returns `0` if all
   topics complete else `1` (3710). Every other command returns `0`. In Typer
   these are `raise typer.Exit(code=n)`; a plain return is exit `0`.

## Legacy code blocks (verbatim — as supplied, reused without modification except where noted above)

### CLI-layer helpers: `resolve_config` (351–362) and `_emit_result` (3152–3157)

```python
def resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    """Carga el documento indicado por --doc, o el activo. Compatible con el flujo legacy --config."""
    doc = getattr(args, "doc", None)
    if doc:
        return load_document(doc)
    if active_doc_id():
        return load_document(active_doc_id())
    legacy = getattr(args, "config", DEFAULT_CONFIG)
    if Path(legacy).exists():
        return load_report_config(legacy)
    raise RuntimeError("No hay documento activo ni configuración legacy. Usa `doc new <id>`.")


def _emit_result(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
```

### Config-assembly machinery `resolve_config` depends on (329–348, 223–230, 196–205, 297–322 — never migrated, ported into the CLI composition layer this slice)

```python
def load_document(doc_id: str | None = None) -> dict[str, Any]:
    """Resuelve plantilla + document.json + rutas computadas en un dict retrocompatible con el antiguo `config`."""
    doc_id = doc_id or active_doc_id()
    if not doc_id:
        raise RuntimeError("No hay documento activo. Usa `doc new <id>` o `doc use <id>`.")
    path = document_json_path(doc_id)
    if not path.exists():
        raise FileNotFoundError(f"No existe el documento `{doc_id}` ({path}). Crea con `doc new {doc_id}`.")
    document = json.loads(path.read_text(encoding="utf-8"))
    template = load_template(document["template"])
    resolved = _deep_merge(template, document)
    resolved = _expand_tokens(resolved, _standard_tokens())
    paths = dict(resolved.get("paths", {}))
    paths.update(_computed_paths(doc_root_for(doc_id)))
    resolved["paths"] = paths
    resolved["doc_id"] = doc_id
    return resolved


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def _expand_tokens(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _expand_tokens(item, tokens) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_tokens(item, tokens) for item in value]
    if isinstance(value, str):
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
        return value
    return value


def _computed_paths(doc_root: Path) -> dict[str, str]:
    sections = doc_root / "sections"
    return {
        # ... per-document keys (context_dir, sections_dir, rules_manifest,
        # fact_ledger, source_manifest, issues_manifest, code_evidence_manifest,
        # corrections_inbox_dir, corrections_applied, output_draft_dir,
        # output_final_dir, output_qa_dir, runs_dir, assets_dir, prompts_dir, ...)
        # plus harness-global keys (repo_root, tesina_root, documents_scripts_dir,
        # documents_render_docx) DROPPED per Judgment call 2.
    }
```

### Flat `command_*` functions (3355–3525, representative subset — all 20 follow the resolve→call-one-service→emit shape)

```python
def command_doctor(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    result = run_doctor(config, strict=args.strict)
    _emit_result(result, getattr(args, "json", False))
    return 0 if result.passed else 2


def command_pipeline(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    summary = run_pipeline(config, args.stage_set, strict=args.strict)
    if getattr(args, "json", False):
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        lines = [f"# Pipeline `{summary['stage_set']}` (strict={summary['strict']})", ""]
        for stage in summary["stages"]:
            marker = "OK" if stage["ok"] else "FAIL"
            lines.append(f"- {marker} `{stage['stage']}` ({stage['duration_s']}s): {stage['detail'].splitlines()[0] if stage['detail'] else ''}")
        lines.append("")
        lines.append("PASÓ" if summary["passed"] else "FALLÓ")
        print("\n".join(lines))
    return 0 if summary["passed"] else 1


def command_verify(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    docx_path = Path(args.docx) if args.docx else None
    result = verify_all(config, docx_path=docx_path, strict=args.strict)
    log_run("verify", {"strict": args.strict, "passed": result.passed, "issues": [issue.to_dict() for issue in result.issues]}, config=config)
    _emit_result(result, getattr(args, "json", False))
    return 0 if result.passed else 1


def command_history(args: argparse.Namespace) -> int:
    config = resolve_config(args)
    records = list_runs(limit=args.limit, config=config)
    if getattr(args, "json", False):
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    if not records:
        print("Sin corridas registradas en runs/.")
        return 0
    lines = ["# Historial de corridas", ""]
    for record in records:
        status = record.get("passed")
        marker = "OK" if status else ("FAIL" if status is False else "·")
        lines.append(f"- {record.get('timestamp', '')} {marker} `{record.get('command', '')}` @ {record.get('git_commit', '')}")
    print("\n".join(lines))
    return 0
```

(The remaining flat commands — `collect_sources`/`build_rules`/`review_rules`/
`collect_issues`/`collect_code_evidence`/`build_ledger`/`build_section`/
`pack_context`/`review_section`/`review_document`/`build_docx`/`qa_docx`/
`format_audit_docx`/`apply_corrections`/`stamp`/`stamp_section` — are quoted
inline in their owning task's "Verbatim legacy reference" below with exact
line numbers.)

### `build_parser` argparse tree (3771–3937) and `main` (3940–3951)

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
```

`build_parser` defines the global `--config`/`--doc` options, 20 flat
subparsers, and the four nested groups (`template list|show`,
`doc new|list|show|current|use|rename|delete`, `asset add|list|rm`,
`context status|elicit|ingest|show|set|rm`), each with its per-command flags.
The full mapping of every subparser's arguments/flags to its Typer equivalent
is given per-command in Tasks 1–8.

## Already satisfied — not re-ported here

Every service method the CLI calls already exists; this slice invents no new
application/domain logic (the two small exceptions —
`ContextService.write_requests_file`, Judgment call 4, and the CLI-layer
config assembler, Judgment call 1 — are noted at their tasks):

- `run_doctor` → `DoctorService.run_doctor(doc_id, config, strict)` (Slice 13).
- `collect_sources`/`collect_issues`/`collect_code_evidence` →
  `CollectionService.collect_sources(config)` / `.collect_issues(config, repo_root)`
  / `.collect_code_evidence(config, repo_root)` (Slice 7).
- `build_rules` → `EvidenceService.build_rules(config)` (Slice 4).
- `render_fact_ledger` → `EvidenceService.render_fact_ledger(config,
  context_confirmed_lines)` (Slice 8).
- `review_rules` → pure `docs.domain.rules.review_rules(template,
  manifest_exists, manifest_size, strict)` (Slice 3).
- `review_section`/`review_document` → `ReviewService.review_section` /
  `.review_document` (Slices 5/9, normative kwargs from Slice 14's
  `resolve_normative_settings`).
- `pack_context`/`pack_context_document` → `ContextPackService` (Slice 9).
- `build_docx` → `DocxAssemblyService.build(doc_id, config, output)`
  (Slices 11a/11b).
- `qa_docx` → `QaService.qa_docx(config, docx_path, strict)` (Slice 12).
- `format_audit_docx` → `FormatAuditService.audit_format(docx_path, config,
  strict)` (Slice 10).
- `apply_corrections` → `CorrectionsService.apply_corrections(doc_id, config)`
  (Slice 13).
- `stamp_section` → `ReviewService.stamp_section(doc_id, template, section_id,
  authored_by, model, now=...)` (Slice 6).
- `run_pipeline`/`verify_all`/`log_run`/`list_runs` → `PipelineService`
  (Slice 14).
- `create_document`/`delete_document`/`rename_document`/`set_active`/
  `active_doc_id`/`list_templates`/`load_template` →
  `DocumentService.create/delete/rename/use/current/list` +
  `JsonDocumentRepository.read_document/load_template/list_templates`
  (Slice 1).
- `context_completion`/`write_topic`/`read_topic`/`regenerate_context_index`/
  `topic_file_path`/`ingest_requests` → `ContextService.status/set/show/
  remove/ingest` (Slice 2).
- `add_asset`/`list_assets`/`remove_asset` → `AssetService.add_asset/
  list_assets/remove_asset(doc_id, ...)` (Slice 9).
- `resolve_normative_settings`, `_context_confirmed_lines` (for `build-ledger`)
  → `docs.domain.normative` + the `PipelineService` build-ledger stage's
  approach (Slice 14).

### Out of scope (confirmed, not re-derived)

- **`build-section`'s draft-rendering + `source_hash`/`prompt_hash`** — remains
  deferred per Slice 6/8/14; the CLI command surfaces a clean error (Judgment
  call 3), it does not implement the renderer.
- **`context elicit`'s interactive TTY loop** (`elicit_interactive`) — never
  migrated, permanently out of scope (Judgment call 4); the CLI only writes
  the questionnaire.
- **Legacy `--config report.yaml` compatibility mode** (`resolve_config`'s
  final `load_report_config` fallback, 358–361) — this migration is
  document-first; there is no `report.yaml` in the new layout and
  `load_report_config` (184–193) reads harness-global tokens that don't exist
  in a library. The CLI's `--doc`/active-document resolution fully replaces it.
  Flagged in Risks as an intentional drop.
- **The PNG-per-page QA pipeline** — permanently out of scope (2026-06-21
  decision); `qa-docx --strict` still raises exactly as `QaService.qa_docx`
  already does.

## Task breakdown

### Task 1 — CLI skeleton, composition root, and core commands (doctor, pipeline, verify, history, stamp)

**Files to create/modify:**
- Modify `pyproject.toml`: add `typer` to `dependencies` and a
  `[project.scripts]` entry `docs = "docs.cli.main:main"` (run `uv add typer`).
- Create `src/docs/cli/__init__.py` (empty).
- Create `src/docs/cli/_shared.py` (composition root: `Deps`,
  `ResolvedContext`, `resolve_context`, `emit_result`, config-assembly
  helpers).
- Create `src/docs/cli/main.py` (Typer `app`, global `--doc`, the five core
  commands, `main()` entrypoint).
- Create `tests/integration/test_cli_core.py`.

**Verbatim legacy reference:** `resolve_config` (351–362) and `_emit_result`
(3152–3157), quoted in full above; the config-assembly machinery
`load_document`/`_deep_merge`/`_expand_tokens`/`_computed_paths` (329–348,
223–230, 196–205, 297–322), ported into `_shared.py` per Judgment calls 1–2;
`command_doctor` (3355–3359), `command_pipeline` (3478–3491), `command_verify`
(3494–3500), `command_history` (3510–3525), `command_stamp` (3473–3475), all
quoted above; `main` (3940–3951).

**Planned implementation:**

```python
# src/docs/cli/_shared.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docs.application.asset import AssetService
from docs.application.collection import CollectionService
from docs.application.context import ContextService
from docs.application.context_pack import ContextPackService
from docs.application.corrections import CorrectionsService
from docs.application.doctor import DoctorService
from docs.application.documents import DocumentService
from docs.application.docx_assembly import DocxAssemblyService
from docs.application.evidence import EvidenceService
from docs.application.format_audit import FormatAuditService
from docs.application.pipeline import PipelineService
from docs.application.qa import QaService
from docs.application.review import ReviewService
from docs.domain.models.template import Template
from docs.domain.workspace import Workspace
from docs.infrastructure.docx.libreoffice_qa_adapter import LibreOfficeQaAdapter
from docs.infrastructure.docx.python_docx_assembly_adapter import PythonDocxAssemblyAdapter
from docs.infrastructure.docx.python_docx_audit_adapter import PythonDocxAuditAdapter
from docs.infrastructure.persistence.filesystem_asset_repository import FilesystemAssetRepository
from docs.infrastructure.persistence.filesystem_source_repository import FilesystemSourceRepository
from docs.infrastructure.persistence.json_context_repository import JsonContextRepository
from docs.infrastructure.persistence.json_evidence_repository import JsonEvidenceRepository
from docs.infrastructure.persistence.json_repository import JsonDocumentRepository
from docs.infrastructure.persistence.json_section_repository import JsonSectionRepository


@dataclass(frozen=True)
class ResolvedContext:
    doc_id: str
    config: dict[str, Any]
    template: Template


def build_workspace() -> Workspace:
    """Workspace roots from env (injectable in tests), cwd-relative defaults.
    Legacy hardcoded HARNESS_ROOT/documents & templates; no library equivalent
    (Judgment call 2)."""
    documents_dir = Path(os.environ.get("DOCS_DOCUMENTS_DIR", "documents"))
    templates_dir = Path(os.environ.get("DOCS_TEMPLATES_DIR", "templates"))
    return Workspace(documents_dir=documents_dir, templates_dir=templates_dir)


class Deps:
    """Composition root — builds every adapter + service exactly as the
    integration-test _service() helpers do, plus config assembly."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace or build_workspace()
        document_repo = JsonDocumentRepository(self.workspace)
        evidence_repo = JsonEvidenceRepository()
        section_repo = JsonSectionRepository(self.workspace)
        source_repo = FilesystemSourceRepository()
        context_repo = JsonContextRepository(self.workspace)
        self.document_repository = document_repo
        self.context_repository = context_repo
        self.source_repository = source_repo

        asset_service = AssetService(FilesystemAssetRepository(), self.workspace)
        evidence_service = EvidenceService(evidence_repo)
        review_service = ReviewService(section_repo)
        collection_service = CollectionService(source_repo, evidence_repo)
        context_pack_service = ContextPackService(section_repo, evidence_repo, evidence_service, review_service)
        docx_assembly_service = DocxAssemblyService(PythonDocxAssemblyAdapter(), asset_service)
        format_audit_service = FormatAuditService(PythonDocxAuditAdapter())
        qa_service = QaService(LibreOfficeQaAdapter(), format_audit_service)
        doctor_service = DoctorService(evidence_repo, asset_service)

        self.assets = asset_service
        self.evidence = evidence_service
        self.review = review_service
        self.collection = collection_service
        self.context_pack = context_pack_service
        self.docx = docx_assembly_service
        self.format_audit = format_audit_service
        self.qa = qa_service
        self.doctor = doctor_service
        self.documents = DocumentService(document_repo)
        self.corrections = CorrectionsService(section_repo, evidence_repo)
        self.context = ContextService(context_repo, document_repo)
        self.pipeline = PipelineService(
            doctor_service, evidence_service, evidence_repo, collection_service, source_repo,
            review_service, context_pack_service, context_repo, docx_assembly_service,
            format_audit_service, qa_service, self.workspace,
        )

    # ── config assembly (migrated resolve_config / load_document) ──────────
    def resolve_context(self, doc: str = "") -> ResolvedContext:
        doc_id = doc or self.document_repository.active_id()
        if not doc_id:
            raise RuntimeError("No hay documento activo. Usa `doc new <id>` o `doc use <id>`.")
        document = self.document_repository.read_document(doc_id)      # Document (extra allowed)
        template = self.document_repository.load_template(document.template)
        merged = _deep_merge(template.model_dump(), document.model_dump())
        merged = _expand_tokens(merged, _standard_tokens(self.workspace))
        paths = dict(merged.get("paths", {}))
        paths.update(_computed_paths(self.workspace.doc_root(doc_id)))
        # prompts_dir: per-document default, template/document override wins if set
        paths.setdefault("prompts_dir", str(self.workspace.doc_root(doc_id) / "prompts"))
        merged["paths"] = paths
        merged["doc_id"] = doc_id
        return ResolvedContext(doc_id=doc_id, config=merged, template=Template.model_validate(merged))


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _deep_merge(base.get(key), value) if key in base else value
        return merged
    return override if override is not None else base


def _expand_tokens(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _expand_tokens(v, tokens) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_tokens(v, tokens) for v in value]
    if isinstance(value, str):
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
    return value


def _standard_tokens(workspace: Workspace) -> dict[str, str]:
    # Harness-global tokens have no library equivalent (Judgment call 2);
    # expand only what the workspace/cwd can supply. Unresolved tokens stay literal.
    return {
        "{templates_dir}": str(workspace.templates_dir.resolve()),
        "{documents_dir}": str(workspace.documents_dir.resolve()),
        "{cwd}": str(Path.cwd().resolve()),
    }


def _computed_paths(doc_root: Path) -> dict[str, str]:
    sections = doc_root / "sections"
    context = doc_root / "context"
    corrections = doc_root / "corrections"
    output = doc_root / "output"
    return {
        "context_dir": str(context),
        "context_index": str(context / "index.json"),
        "context_requests": str(context / "_requests.md"),
        "assets_dir": str(doc_root / "assets"),
        "sections_dir": str(sections),
        "source_manifest": str(sections / "source-manifest.json"),
        "issues_manifest": str(sections / "issues-manifest.json"),
        "code_evidence_manifest": str(sections / "code-evidence-manifest.json"),
        "rules_manifest": str(sections / "manual-rules.json"),
        "fact_ledger": str(sections / "00-fact-ledger.md"),
        "corrections_inbox_dir": str(corrections / "inbox"),
        "corrections_applied": str(corrections / "applied.json"),
        "output_draft_dir": str(output / "draft"),
        "output_final_dir": str(output / "final"),
        "output_qa_dir": str(output / "qa"),
        "runs_dir": str(doc_root / "runs"),
    }


def emit_result(result: Any, as_json: bool) -> None:
    """Migrated _emit_result (3152-3157). Prints to stdout."""
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_markdown())
```

```python
# src/docs/cli/main.py
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import typer

from docs.cli._shared import Deps, ResolvedContext, emit_result

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False, help="Arnés multi-documento para Word.")


@app.callback()
def _root(ctx: typer.Context, doc: str = typer.Option("", "--doc", help="ID del documento (por defecto, el activo).")) -> None:
    # One Deps per invocation; commands read ctx.obj.
    ctx.obj = {"deps": Deps(), "doc": doc}


def _ctx(ctx: typer.Context) -> tuple[Deps, str]:
    return ctx.obj["deps"], ctx.obj["doc"]


@app.command()
def doctor(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.doctor.run_doctor(resolved.doc_id, resolved.config, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 2)


@app.command()
def pipeline(
    ctx: typer.Context,
    stage_set: str = typer.Argument(..., help="prep | assemble | all"),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
    repo_root: Path = typer.Option(Path.cwd, "--repo-root"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    summary = deps.pipeline.run_pipeline(
        resolved.doc_id, resolved.template, resolved.config, stage_set, repo_root=repo_root, strict=strict
    )
    if as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        lines = [f"# Pipeline `{summary['stage_set']}` (strict={summary['strict']})", ""]
        for stage in summary["stages"]:
            marker = "OK" if stage["ok"] else "FAIL"
            head = stage["detail"].splitlines()[0] if stage["detail"] else ""
            lines.append(f"- {marker} `{stage['stage']}` ({stage['duration_s']}s): {head}")
        lines.extend(["", "PASÓ" if summary["passed"] else "FALLÓ"])
        print("\n".join(lines))
    raise typer.Exit(code=0 if summary["passed"] else 1)


@app.command()
def verify(
    ctx: typer.Context,
    docx: str = typer.Argument("", help="DOCX opcional; por defecto el draft."),
    strict: bool = typer.Option(False, "--strict"),
    as_json: bool = typer.Option(False, "--json"),
    repo_root: Path = typer.Option(Path.cwd, "--repo-root"),
) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    docx_path = Path(docx) if docx else None
    result = deps.pipeline.verify_all(resolved.doc_id, resolved.template, resolved.config, docx_path=docx_path, strict=strict)
    deps.pipeline.log_run(
        resolved.doc_id, resolved.config, repo_root, "verify",
        {"strict": strict, "passed": result.passed, "issues": [i.to_dict() for i in result.issues]},
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command()
def history(ctx: typer.Context, limit: int = typer.Option(20, "--limit"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    records = deps.pipeline.list_runs(resolved.doc_id, resolved.config, limit=limit)
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return
    if not records:
        print("Sin corridas registradas en runs/.")
        return
    lines = ["# Historial de corridas", ""]
    for record in records:
        status = record.get("passed")
        marker = "OK" if status else ("FAIL" if status is False else "·")
        lines.append(f"- {record.get('timestamp', '')} {marker} `{record.get('command', '')}` @ {record.get('git_commit', '')}")
    print("\n".join(lines))


@app.command()
def stamp() -> None:
    print(datetime.now().isoformat(timespec="seconds"))


def main(argv: list[str] | None = None) -> int:
    try:
        app(args=argv, standalone_mode=False)
    except typer.Exit as exc:
        return exc.exit_code
    except Exception as exc:  # legacy main() parity (3945-3947)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**Planned test code:**

```python
# tests/integration/test_cli_core.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina",
    "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": False}],
    "section_contracts": {"introduccion": {}},
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    documents = tmp_path / "documents"
    templates = tmp_path / "templates"
    documents.mkdir()
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(documents))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def _new_doc(doc_id="doc1"):
    result = runner.invoke(app, ["doc", "new", doc_id, "--template", "tesina"])
    assert result.exit_code == 0, result.output


def test_stamp_prints_iso_timestamp(workspace):
    result = runner.invoke(app, ["stamp"])
    assert result.exit_code == 0
    assert "T" in result.output.strip()  # ISO 8601


def test_doctor_returns_exit_2_when_checks_fail(workspace):
    _new_doc()
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code in (0, 2)  # env-dependent (pandoc/gh), never crash
    assert "Doctor del arnés" in result.output


def test_doctor_json_emits_dict(workspace):
    _new_doc()
    result = runner.invoke(app, ["doctor", "--json"])
    payload = json.loads(result.output)
    assert "passed" in payload and "checks" in payload


def test_resolve_context_errors_when_no_active_document(workspace):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    assert "No hay documento activo" in (result.output + str(result.exception or ""))


def test_history_reports_empty_when_no_runs(workspace):
    _new_doc()
    result = runner.invoke(app, ["history"])
    assert result.exit_code == 0
    assert "Sin corridas" in result.output


def test_pipeline_prep_runs_and_reports_a_summary(workspace, monkeypatch):
    _new_doc()
    monkeypatch.setattr("shutil.which", lambda name: None)  # gh unavailable
    result = runner.invoke(app, ["pipeline", "prep"])
    assert result.exit_code in (0, 1)
    assert "Pipeline `prep`" in result.output


def test_pipeline_unknown_stage_set_errors_cleanly(workspace):
    _new_doc()
    result = runner.invoke(app, ["pipeline", "bogus"])
    assert result.exit_code == 1
    assert "Conjunto de etapas desconocido" in (result.output + str(result.exception or ""))
```

**Expected test count:** ~7 integration tests. **Highest-risk task in this
slice** — needs implementer + fresh-context reviewer. The reviewer must
specifically verify: (a) `resolve_context` reproduces legacy `load_document`'s
merge/overlay order (template under document, then computed paths win) —
diff the resolved `config["paths"]` against a hand-built fixture; (b) the
`Deps` service graph matches `test_pipeline_service.py::_service` exactly
(same adapters, same wiring), since every later task depends on it; (c)
`main()` maps `typer.Exit` codes through and preserves legacy's `ERROR:` stderr
line for unexpected exceptions; (d) the `--doc` global option reaches every
command via `ctx.obj`. This task also unblocks Tasks 2–8, so its `workspace`
fixture and `_new_doc` helper become the shared CLI test harness.

---

### Task 2 — Collection & rules commands (collect-sources, build-rules, review-rules, collect-issues, collect-code-evidence, build-ledger)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add the six commands.
- Create `tests/integration/test_cli_collection.py`.

**Verbatim legacy reference:** `command_collect_sources` (3362–3366),
`command_build_rules` (3369–3373), `command_review_rules` (3376–3380),
`command_collect_issues` (3383–3387), `command_collect_code_evidence`
(3390–3394), `command_build_ledger` (3397–3404). Two migration adaptations:
(a) `review-rules` — legacy called `review_rules(config, strict)`; the
migrated `docs.domain.rules.review_rules` is pure and takes
`(template, manifest_exists, manifest_size, strict)`, so the command builds
`manifest_exists`/`manifest_size` from `config["paths"]["rules_manifest"]`
via the `DocumentRepository`/evidence file-state ports exactly as
`DoctorService.run_doctor` (doctor.py 64–66) and
`PipelineService._rules_manifest_state` already do; (b) `build-ledger` —
legacy passed `load_context(config)` into `render_fact_ledger`, but the
migrated `EvidenceService.render_fact_ledger(config, context_confirmed_lines)`
takes a pre-computed confirmed-lines list, so the command builds it from the
`ContextRepository` + `Template` the same way `PipelineService`'s build-ledger
stage does (Slice 14 `_context_confirmed_lines`, reused inline here — the
sensitive-field drop documented in Slice 14 Judgment call 4 carries over
unchanged).

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)
from docs.cli._shared import emit_result
from docs.domain.rules import review_rules as domain_review_rules


@app.command("collect-sources")
def collect_sources(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_sources(resolved.config))


@app.command("build-rules")
def build_rules(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.evidence.build_rules(resolved.config))


@app.command("review-rules")
def review_rules(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
    result = domain_review_rules(resolved.template, manifest_exists, manifest_size, strict=strict)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("collect-issues")
def collect_issues(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_issues(resolved.config, repo_root))


@app.command("collect-code-evidence")
def collect_code_evidence(ctx: typer.Context, repo_root: Path = typer.Option(Path.cwd, "--repo-root")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.collection.collect_code_evidence(resolved.config, repo_root))


@app.command("build-ledger")
def build_ledger(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = Path(resolved.config["paths"]["fact_ledger"])
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _context_confirmed_lines(deps, resolved.doc_id, resolved.template)
    path.write_text(deps.evidence.render_fact_ledger(resolved.config, lines), encoding="utf-8")
    print(path)


def _rules_manifest_state(deps: Deps, config: dict) -> tuple[bool, int]:
    rules_path = Path(config["paths"]["rules_manifest"])
    exists = rules_path.exists()
    return exists, (rules_path.stat().st_size if exists else 0)


def _context_confirmed_lines(deps: Deps, doc_id: str, template) -> list[str]:
    # Mirrors PipelineService._context_confirmed_lines (Slice 14 JC4): sensitive
    # topic fields are skipped, not mis-classified.
    lines: list[str] = []
    for topic in template.context_schema.topics:
        values = deps.context_repository.read_topic(doc_id, topic)
        if isinstance(values, dict):
            for field in topic.fields:
                value = values.get(field.key, "")
                if not value or field.sensitive:
                    continue
                lines.append(f"{field.label}: {value}")
        elif isinstance(values, str) and values.strip():
            lines.append(f"{topic.title or topic.id}: {values.strip()[:160]}")
    return lines
```

**Planned test code:**

```python
# tests/integration/test_cli_collection.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina", "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
    "section_contracts": {},
    "context_schema": {"topics": []},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def test_collect_sources_prints_manifest_path(ws):
    result = runner.invoke(app, ["collect-sources"])
    assert result.exit_code == 0
    assert result.output.strip().endswith("source-manifest.json")
    assert Path(result.output.strip()).exists()


def test_build_rules_prints_manifest_path(ws):
    result = runner.invoke(app, ["build-rules"])
    assert result.exit_code == 0
    assert Path(result.output.strip()).exists()


def test_review_rules_exit_1_when_manifest_missing_under_strict(ws):
    result = runner.invoke(app, ["review-rules", "--strict"])
    assert result.exit_code == 1
    assert "Revisión" in result.output


def test_review_rules_json_mode(ws):
    result = runner.invoke(app, ["review-rules", "--json"])
    payload = json.loads(result.output)
    assert "passed" in payload and "issues" in payload


def test_collect_issues_errors_cleanly_without_gh(ws, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = runner.invoke(app, ["collect-issues"])
    assert result.exit_code == 1  # RuntimeError -> main() ERROR path


def test_build_ledger_writes_and_prints_path(ws):
    result = runner.invoke(app, ["build-ledger"])
    assert result.exit_code == 0
    ledger = Path(result.output.strip())
    assert ledger.exists() and ledger.read_text(encoding="utf-8").startswith("# Fact Ledger")
```

**Expected test count:** ~6 integration tests. Self-reviewable for
`collect-sources`/`build-rules`/`build-ledger` (each is one service call +
print). Needs a fresh-context reviewer note on `review-rules` and
`build-ledger`: the reviewer should confirm `_rules_manifest_state` matches
`DoctorService`/`PipelineService`'s file-state computation and that
`_context_confirmed_lines` is byte-identical to `PipelineService`'s (same
sensitive-field skip), so `build-ledger` and the pipeline's `build-ledger`
stage produce the same ledger.

---

### Task 3 — Section commands (build-section, pack-context, review-section, review-document)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add the four commands.
- Create `tests/integration/test_cli_section.py`.

**Verbatim legacy reference:** `command_build_section` (3407–3411),
`command_pack_context` (3414–3424, the `all`/`document`/`<section>`
branching), `command_review_section` (3427–3434), `command_review_document`
(3437–3441). Adaptations: (a) `build-section` — legacy `build_section(config,
section_id)` was never ported (Judgment call 3); the command raises a clean
error and never calls `ReviewService.build_section` with faked hashes; (b)
`pack-context`/`review-section`/`review-document` build normative kwargs via
`resolve_normative_settings(config)` (Slice 14) since the migrated
`ContextPackService`/`ReviewService` methods take them as required keyword
arguments (context_pack.py 42–56 / review.py 25–40, 125–139);
`pack-context`/`review-document` additionally pass `manifest_exists`/
`manifest_size`.

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)
from docs.domain.normative import resolve_normative_settings

_BUILD_SECTION_UNAVAILABLE = (
    "build-section requiere un renderer de borradores y source_hash/prompt_hash "
    "aún no modelados en esta migración (ver Slice 6 y Slice 8, Design Decision 4)."
)


@app.command("build-section")
def build_section(ctx: typer.Context, section_id: str = typer.Argument(...)) -> None:
    # Judgment call 3: surface the unmodeled gap cleanly, do not fake hashes.
    print(f"ERROR: {_BUILD_SECTION_UNAVAILABLE}", file=sys.stderr)
    raise typer.Exit(code=1)


@app.command("pack-context")
def pack_context(ctx: typer.Context, section_id: str = typer.Argument(..., help="<id> | all | document")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)

    def pack_one(sid: str) -> Path:
        return deps.context_pack.pack_context(resolved.doc_id, resolved.template, sid, resolved.config, **normative)

    def pack_document() -> Path:
        return deps.context_pack.pack_context_document(
            resolved.doc_id, resolved.template, resolved.config,
            manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
        )

    if section_id == "all":
        for section in resolved.template.sections:
            print(pack_one(section.id))
        print(pack_document())
    elif section_id == "document":
        print(pack_document())
    else:
        print(pack_one(section_id))


@app.command("review-section")
def review_section(ctx: typer.Context, section: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    result = deps.review.review_section(resolved.doc_id, resolved.template, section, strict=strict, **normative)
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("review-document")
def review_document(ctx: typer.Context, strict: bool = typer.Option(False, "--strict"), as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    normative = resolve_normative_settings(resolved.config)
    manifest_exists, manifest_size = _rules_manifest_state(deps, resolved.config)
    result = deps.review.review_document(
        resolved.doc_id, resolved.template, strict=strict,
        manifest_exists=manifest_exists, manifest_size=manifest_size, **normative,
    )
    emit_result(result, as_json)
    raise typer.Exit(code=0 if result.passed else 1)
```

**Planned test code:**

```python
# tests/integration/test_cli_section.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina", "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1, "required": True}],
    "section_contracts": {"introduccion": {"required_content": ["contexto"]}},
    "context_schema": {"topics": []},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def test_build_section_surfaces_unmodeled_gap_cleanly(ws):
    result = runner.invoke(app, ["build-section", "introduccion"])
    assert result.exit_code == 1
    assert "build-section requiere" in result.output


def test_review_document_exit_1_when_required_section_missing(ws):
    result = runner.invoke(app, ["review-document"])
    assert result.exit_code == 1
    assert "Revisión" in result.output


def test_review_document_json_mode(ws):
    result = runner.invoke(app, ["review-document", "--json"])
    payload = json.loads(result.output)
    assert payload["passed"] is False  # required section absent


def test_review_section_errors_when_section_absent(ws):
    result = runner.invoke(app, ["review-section", "introduccion"])
    assert result.exit_code == 1  # FileNotFoundError -> main() ERROR path


def test_pack_context_document_writes_a_pack(ws):
    result = runner.invoke(app, ["pack-context", "document"])
    assert result.exit_code == 0
    assert Path(result.output.strip()).exists()


def test_pack_context_all_prints_one_line_per_section_plus_document(ws):
    result = runner.invoke(app, ["pack-context", "all"])
    assert result.exit_code == 0
    assert len([ln for ln in result.output.splitlines() if ln.strip()]) == 2  # 1 section + document
```

**Expected test count:** ~6 integration tests. Needs implementer +
fresh-context reviewer: the reviewer must confirm (a) `build-section` never
reaches `ReviewService.build_section` (grep the command body — it only prints
and exits); (b) the normative kwargs unpacked into
`pack_context`/`review_section`/`review_document` match those methods'
required keyword-only parameters exactly (no `TypeError` at call time); (c)
`pack-context`'s `all`/`document`/`<id>` branching matches legacy
`command_pack_context` (3414–3424) line-for-line.

---

### Task 4 — DOCX commands (build-docx, qa-docx, format-audit-docx, apply-corrections, stamp-section)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add the five commands.
- Create `tests/integration/test_cli_docx.py`.

**Verbatim legacy reference:** `command_build_docx` (3444–3449),
`command_qa_docx` (3452–3456), `command_format_audit_docx` (3459–3463),
`command_apply_corrections` (3466–3470), `command_stamp_section` (3503–3507).
Adaptations: (a) `build-docx` → `DocxAssemblyService.build(doc_id, config,
output)` (output is `--output` or `None`); (b) `apply-corrections` →
`CorrectionsService.apply_corrections(doc_id, config)` (the `doc_id` param the
migrated service added, corrections.py 21); (c) `stamp-section` →
`ReviewService.stamp_section(doc_id, template, section_id, authored_by, model,
now=...)`, where `now = datetime.now().isoformat(timespec="seconds")` is
injected by the CLI (the service takes it as a keyword-only parameter,
review.py 169–178).

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)


@app.command("build-docx")
def build_docx(ctx: typer.Context, output: str = typer.Option("", "--output")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.docx.build(resolved.doc_id, resolved.config, Path(output) if output else None))


@app.command("qa-docx")
def qa_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.qa.qa_docx(resolved.config, Path(docx), strict=strict))


@app.command("format-audit-docx")
def format_audit_docx(ctx: typer.Context, docx: str = typer.Argument(...), strict: bool = typer.Option(False, "--strict")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    result = deps.format_audit.audit_format(Path(docx), resolved.config, strict=strict)
    print(result.to_markdown())
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("apply-corrections")
def apply_corrections(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    count = deps.corrections.apply_corrections(resolved.doc_id, resolved.config)
    print(f"Correcciones aplicadas: {count}")


@app.command("stamp-section")
def stamp_section(ctx: typer.Context, section_id: str = typer.Argument(...), by: str = typer.Option(..., "--by"), model: str = typer.Option("", "--model")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    now = datetime.now().isoformat(timespec="seconds")
    print(deps.review.stamp_section(resolved.doc_id, resolved.template, section_id, authored_by=by, model=model, now=now))
```

**Planned test code:**

```python
# tests/integration/test_cli_docx.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina", "title": "Tesina",
    "sections": [{"id": "introduccion", "title": "Introducción", "order": 1}],
    "section_contracts": {}, "context_schema": {"topics": []},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def test_apply_corrections_reports_zero_when_inbox_empty(ws):
    result = runner.invoke(app, ["apply-corrections"])
    assert result.exit_code == 0
    assert "Correcciones aplicadas: 0" in result.output


def test_build_docx_errors_cleanly_without_sections(ws):
    result = runner.invoke(app, ["build-docx"])
    assert result.exit_code == 1  # RuntimeError (no sections / no pandoc) -> ERROR path


def test_format_audit_docx_errors_when_docx_missing(ws):
    result = runner.invoke(app, ["format-audit-docx", str(ws / "missing.docx")])
    assert result.exit_code == 1  # FileNotFoundError -> ERROR path


def test_qa_docx_errors_when_docx_missing(ws):
    result = runner.invoke(app, ["qa-docx", str(ws / "missing.docx")])
    assert result.exit_code == 1


def test_stamp_section_errors_when_section_absent(ws):
    result = runner.invoke(app, ["stamp-section", "introduccion", "--by", "gpt"])
    assert result.exit_code == 1  # FileNotFoundError: section not written yet
```

**Expected test count:** ~5 integration tests (error-path-heavy, since happy
paths need pandoc/LibreOffice). Self-reviewable — every command is a single
service call + print + exit code; the only judgment is `stamp-section`
injecting `now`, which the reviewer should confirm matches `command_stamp`'s
`timespec="seconds"` format. A reviewer may optionally add pandoc/LibreOffice
`skipif`-guarded happy-path tests mirroring `test_docx_assembly_service.py`.

---

### Task 5 — `template` command group (list, show)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add a `template` Typer sub-app and register
  it via `app.add_typer(template_app, name="template")`.
- Create `tests/integration/test_cli_template.py`.

**Verbatim legacy reference:** `command_template_list` (3593–3601),
`command_template_show` (3604–3607), and their argparse wiring (3865–3871).
Adaptation: `list_templates()`/`load_template(name)` module functions →
`JsonDocumentRepository.list_templates()` / `.load_template(name)` (Slice 1,
json_repository.py 74–85); `template show` prints the resolved template as
JSON via `Template.model_dump` (the migrated `load_template` returns a
`Template`, not a raw dict).

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)

template_app = typer.Typer(help="Gestiona los tipos de documento (plantillas).")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    names = deps.document_repository.list_templates()
    if not names:
        print("No hay plantillas en templates/.")
        return
    for name in names:
        template = deps.document_repository.load_template(name)
        print(f"- {name}: {template.title}")


@template_app.command("show")
def template_show(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    template = deps.document_repository.load_template(name)
    print(json.dumps(template.model_dump(), ensure_ascii=False, indent=2))
```

**Planned test code:**

```python
# tests/integration/test_cli_template.py
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Plantilla Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_template_list_shows_name_and_title(ws):
    result = runner.invoke(app, ["template", "list"])
    assert result.exit_code == 0
    assert "- tesina: Plantilla Tesina" in result.output


def test_template_list_empty_message(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    (tmp_path / "templates").mkdir()
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(tmp_path / "templates"))
    result = runner.invoke(app, ["template", "list"])
    assert result.exit_code == 0
    assert "No hay plantillas" in result.output


def test_template_show_prints_resolved_json(ws):
    result = runner.invoke(app, ["template", "show", "tesina"])
    payload = json.loads(result.output)
    assert payload["title"] == "Plantilla Tesina"


def test_template_show_unknown_errors_cleanly(ws):
    result = runner.invoke(app, ["template", "show", "nope"])
    assert result.exit_code == 1  # FileNotFoundError -> ERROR path
```

**Expected test count:** ~4 integration tests. Self-reviewable — two commands,
both read-only repository calls. Reviewer note: confirm `template show` prints
valid JSON parseable back to the template shape (no Pydantic object leaking
into `json.dumps`).

---

### Task 6 — `doc` command group (new, list, show, current, use, rename, delete)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add a `doc` Typer sub-app and register it.
- Create `tests/integration/test_cli_doc.py`.

**Verbatim legacy reference:** `command_doc_new` (3610–3618),
`command_doc_list` (3621–3630), `command_doc_current` (3633–3636),
`command_doc_show` (3639–3645), `command_doc_use` (3648–3651),
`command_doc_rename` (3654–3657), `command_doc_delete` (3660–3665), plus the
`create_document`/`delete_document`/`rename_document` helpers (3536–3590) and
argparse wiring (3873–3898). Adaptation: all seven map onto
`DocumentService.create/list/current/use/rename/delete` (documents.py 32–75)
and `JsonDocumentRepository.read_document` (json_repository.py 62–66) for
`doc show`; `doc new`'s "default to the first available template" logic and
`doc delete`'s `--yes` guard are preserved in the command (they are CLI-policy,
not domain logic — legacy kept them in `command_*` too, 3611–3613 / 3661–3662).

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)

doc_app = typer.Typer(help="CRUD de documentos (workspaces aislados).")
app.add_typer(doc_app, name="doc")


@doc_app.command("new")
def doc_new(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), template: str = typer.Option("", "--template"), title: str = typer.Option("", "--title")) -> None:
    deps, _ = _ctx(ctx)
    template_name = template or (deps.document_repository.list_templates()[:1] or [""])[0]
    if not template_name:
        raise RuntimeError("No hay plantillas disponibles. Crea una en templates/.")
    document = deps.documents.create(doc_id, template_name, title=title)
    path = deps.workspace.doc_root(doc_id) / "document.json"
    print(path)
    print(f"Documento `{doc_id}` creado desde `{template_name}` y marcado como activo.")
    print("Siguiente paso: `context status` y `context elicit` para llenar el contexto.")


@doc_app.command("list")
def doc_list(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    summaries = deps.documents.list()
    if not summaries:
        print("No hay documentos. Crea uno con `doc new <id>`.")
        return
    active = deps.documents.current()
    for item in summaries:
        marker = "*" if item.id == active else " "
        print(f"{marker} {item.id}  [{item.template}]  {item.title}")


@doc_app.command("current")
def doc_current(ctx: typer.Context) -> None:
    deps, _ = _ctx(ctx)
    print(deps.documents.current() or "(ninguno)")


@doc_app.command("show")
def doc_show(ctx: typer.Context, doc_id: str = typer.Argument("", metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    target = doc_id or deps.documents.current()
    if not target:
        raise RuntimeError("No hay documento activo.")
    document = deps.document_repository.read_document(target)
    print(json.dumps(document.model_dump(), ensure_ascii=False, indent=2))


@doc_app.command("use")
def doc_use(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id")) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.use(doc_id)
    print(f"Documento activo: {doc_id}")


@doc_app.command("rename")
def doc_rename(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), new_id: str = typer.Argument(...)) -> None:
    deps, _ = _ctx(ctx)
    deps.documents.rename(doc_id, new_id)
    print(f"Renombrado: {doc_id} → {new_id}")


@doc_app.command("delete")
def doc_delete(ctx: typer.Context, doc_id: str = typer.Argument(..., metavar="id"), yes: bool = typer.Option(False, "--yes")) -> None:
    deps, _ = _ctx(ctx)
    if not yes:
        raise RuntimeError(f"Confirma el borrado de `{doc_id}` con --yes.")
    deps.documents.delete(doc_id)
    print(f"Documento `{doc_id}` eliminado.")
```

**Planned test code:**

```python
# tests/integration/test_cli_doc.py
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    return tmp_path


def test_doc_new_creates_and_activates(ws):
    result = runner.invoke(app, ["doc", "new", "alpha"])
    assert result.exit_code == 0
    assert "creado desde `tesina`" in result.output
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_list_marks_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    out = runner.invoke(app, ["doc", "list"]).output
    assert "* beta" in out and "  alpha" in out


def test_doc_show_prints_document_json(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    payload = json.loads(runner.invoke(app, ["doc", "show"]).output)
    assert payload["id"] == "alpha"


def test_doc_use_switches_active(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    runner.invoke(app, ["doc", "new", "beta"])
    runner.invoke(app, ["doc", "use", "alpha"])
    assert runner.invoke(app, ["doc", "current"]).output.strip() == "alpha"


def test_doc_rename(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    result = runner.invoke(app, ["doc", "rename", "alpha", "gamma"])
    assert result.exit_code == 0 and "alpha → gamma" in result.output


def test_doc_delete_requires_yes(ws):
    runner.invoke(app, ["doc", "new", "alpha"])
    assert runner.invoke(app, ["doc", "delete", "alpha"]).exit_code == 1
    assert runner.invoke(app, ["doc", "delete", "alpha", "--yes"]).exit_code == 0


def test_doc_list_empty_message(ws):
    result = runner.invoke(app, ["doc", "list"])
    assert "No hay documentos" in result.output
```

**Expected test count:** ~7 integration tests. Self-reviewable — every command
is one `DocumentService`/repository call plus a print. Reviewer note: confirm
`doc new`'s default-template selection and `doc delete`'s `--yes` guard match
legacy (3611–3613 / 3661–3662), and that `doc list`'s active-marker column
matches `command_doc_list` (3628–3629).

---

### Task 7 — `asset` command group (add, list, rm)

**Files to create/modify:**
- Modify `src/docs/cli/main.py`: add an `asset` Typer sub-app and register it.
- Create `tests/integration/test_cli_asset.py`.

**Verbatim legacy reference:** `command_asset_add` (3668–3673),
`command_asset_list` (3676–3684), `command_asset_rm` (3687–3691), and argparse
wiring (3900–3911). Adaptation: `add_asset`/`list_assets`/`remove_asset`
module functions → `AssetService.add_asset(doc_id, src, name)` /
`.list_assets(doc_id)` / `.remove_asset(doc_id, name)` (asset.py 18–38), each
taking the `doc_id` the migrated service made explicit.

**Planned implementation:**

```python
# src/docs/cli/main.py (additions)

asset_app = typer.Typer(help="Adjunta archivos .docx al documento (portada, anexos).")
app.add_typer(asset_app, name="asset")


@asset_app.command("add")
def asset_add(ctx: typer.Context, path: str = typer.Argument(...), name: str = typer.Option("", "--name")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    target = deps.assets.add_asset(resolved.doc_id, path, name=name)
    print(target)
    print(f"Asset `{target.stem}` agregado. Úsalo en la estructura con cover_from_asset o embed_docx.")


@asset_app.command("list")
def asset_list(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    names = deps.assets.list_assets(resolved.doc_id)
    if not names:
        print("No hay assets. Agrega uno con `asset add <ruta.docx>`.")
        return
    for name in names:
        print(f"- {name}")


@asset_app.command("rm")
def asset_rm(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.assets.remove_asset(resolved.doc_id, name)
    print(f"Asset `{name}` eliminado.")
```

**Planned test code:**

```python
# tests/integration/test_cli_asset.py
from __future__ import annotations

import json

import pytest
from docx import Document as DocxDocument
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {"type": "tesina", "title": "Tesina", "sections": [], "section_contracts": {}}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def _make_docx(tmp_path, name="cover.docx"):
    path = tmp_path / name
    DocxDocument().save(path)
    return path


def test_asset_list_empty_message(ws):
    result = runner.invoke(app, ["asset", "list"])
    assert result.exit_code == 0
    assert "No hay assets" in result.output


def test_asset_add_then_list(ws):
    src = _make_docx(ws)
    add = runner.invoke(app, ["asset", "add", str(src), "--name", "portada"])
    assert add.exit_code == 0 and "agregado" in add.output
    listed = runner.invoke(app, ["asset", "list"]).output
    assert "- portada" in listed


def test_asset_add_rejects_non_docx(ws):
    bad = ws / "notes.txt"
    bad.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["asset", "add", str(bad)])
    assert result.exit_code == 1  # ValueError -> ERROR path


def test_asset_rm(ws):
    src = _make_docx(ws)
    runner.invoke(app, ["asset", "add", str(src), "--name", "portada"])
    result = runner.invoke(app, ["asset", "rm", "portada"])
    assert result.exit_code == 0 and "eliminado" in result.output
    assert "No hay assets" in runner.invoke(app, ["asset", "list"]).output
```

**Expected test count:** ~4 integration tests. Self-reviewable — three
single-service-call commands. Reviewer note: confirm `asset add` prints both
the path and the follow-up hint line exactly as `command_asset_add`
(3671–3672).

---

### Task 8 — `context` command group (status, elicit, ingest, show, set, rm)

**Files to create/modify:**
- Modify `src/docs/application/context.py`: add
  `ContextService.write_requests_file` (Judgment call 4).
- Modify `src/docs/cli/main.py`: add a `context` Typer sub-app and register it.
- Modify `tests/integration/test_context_service.py`: add tests for the new
  service method.
- Create `tests/integration/test_cli_context.py`.

**Verbatim legacy reference:** `command_context_status` (3694–3710),
`command_context_elicit` (3713–3723), `command_context_ingest` (3726–3730),
`command_context_show` (3733–3739), `command_context_set` (3742–3758),
`command_context_rm` (3761–3768), and argparse wiring (3913–3935).
Adaptations: (a) `context status` → `ContextService.status(doc_id, template)`
returning `list[TopicStatus]`, formatted to markdown/JSON and exit-coded on
all-complete exactly as `command_context_status` (3703–3710); (b) `context
elicit` → the new `ContextService.write_requests_file`, dropping the
interactive TTY branch (Judgment call 4); (c) `ingest`/`show`/`set`/`rm` →
`ContextService.ingest`/`show`/`set`/`remove` (context.py 64–106), where
`set` takes `(doc_id, template, topic_id, value, field)` — legacy's positional
`field`/`value` order (3928–3931) is preserved as Typer arguments.

**Planned implementation:**

```python
# src/docs/application/context.py (addition — Judgment call 4)
    def write_requests_file(self, doc_id: str, template: Template, only_topic: str = "") -> Path:
        """Non-interactive elicitation: render the pending-fields questionnaire
        and persist it. Composes the already-migrated status + render_requests +
        ContextRepository.write_requests. The interactive TTY loop (legacy
        elicit_interactive) is out of scope for this migration."""
        self._require_document(doc_id)
        statuses = self.status(doc_id, template)
        pairs = [(s, self.context_repo.read_topic(doc_id, self._find_topic(template, s.id))) for s in statuses]
        text = render_requests(template.context_schema, pairs, only_topic=only_topic)
        return self.context_repo.write_requests(doc_id, text)
```

```python
# (add the import at the top of context.py)
from docs.infrastructure.persistence.context_markdown import parse_requests, render_requests
```

```python
# src/docs/cli/main.py (additions)

context_app = typer.Typer(help="Elicita y gestiona el contexto atómico del documento.")
app.add_typer(context_app, name="context")


@context_app.command("status")
def context_status(ctx: typer.Context, as_json: bool = typer.Option(False, "--json")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    statuses = deps.context.status(resolved.doc_id, resolved.template)
    if as_json:
        print(json.dumps([{"id": s.id, "title": s.title, "complete": not s.missing, "missing": s.missing} for s in statuses], ensure_ascii=False, indent=2))
        return
    if not statuses:
        print("La plantilla no define context_schema.")
        return
    lines = ["# Estado del contexto", ""]
    for s in statuses:
        marker = "OK" if not s.missing else "FALTA"
        missing = f" — faltan: {', '.join(s.missing)}" if s.missing else ""
        lines.append(f"- {marker} `{s.id}` ({s.title}){missing}")
    print("\n".join(lines))
    raise typer.Exit(code=0 if all(not s.missing for s in statuses) else 1)


@context_app.command("elicit")
def context_elicit(ctx: typer.Context, topic: str = typer.Option("", "--topic"), requests: bool = typer.Option(False, "--requests", help="(compat) el cuestionario es el único modo disponible.")) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    path = deps.context.write_requests_file(resolved.doc_id, resolved.template, only_topic=topic)
    print(path)
    print("Rellena el cuestionario y corre `context ingest`.")


@context_app.command("ingest")
def context_ingest(ctx: typer.Context) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    written = deps.context.ingest(resolved.doc_id, resolved.template)
    print(f"Temas ingeridos: {', '.join(written) or 'ninguno'}.")


@context_app.command("show")
def context_show(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.show(resolved.doc_id, topic))


@context_app.command("set")
def context_set(ctx: typer.Context, topic: str = typer.Argument(...), field: str = typer.Argument(..., help="Clave del campo (ignorada en temas de prosa)."), value: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    print(deps.context.set(resolved.doc_id, resolved.template, topic, value, field=field))


@context_app.command("rm")
def context_rm(ctx: typer.Context, topic: str = typer.Argument(...)) -> None:
    deps, doc = _ctx(ctx)
    resolved = deps.resolve_context(doc)
    deps.context.remove(resolved.doc_id, resolved.template, topic)
    print(f"Tema `{topic}` eliminado.")
```

**Planned test code:**

```python
# tests/integration/test_cli_context.py
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from docs.cli.main import app

runner = CliRunner()

_TEMPLATE = {
    "type": "tesina", "title": "Tesina", "sections": [], "section_contracts": {},
    "context_schema": {"topics": [
        {"id": "proyecto", "title": "Proyecto", "required": True,
         "fields": [{"key": "nombre", "label": "Nombre", "required": True}]},
    ]},
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    (tmp_path / "documents").mkdir()
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "tesina.json").write_text(json.dumps(_TEMPLATE), encoding="utf-8")
    monkeypatch.setenv("DOCS_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("DOCS_TEMPLATES_DIR", str(templates))
    runner.invoke(app, ["doc", "new", "doc1", "--template", "tesina"])
    return tmp_path


def test_context_status_exit_1_when_incomplete(ws):
    result = runner.invoke(app, ["context", "status"])
    assert result.exit_code == 1
    assert "FALTA `proyecto`" in result.output


def test_context_set_then_status_complete(ws):
    assert runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"]).exit_code == 0
    result = runner.invoke(app, ["context", "status"])
    assert result.exit_code == 0
    assert "OK `proyecto`" in result.output


def test_context_set_then_show(ws):
    runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"])
    result = runner.invoke(app, ["context", "show", "proyecto"])
    assert result.exit_code == 0 and "Mi App" in result.output


def test_context_elicit_writes_questionnaire(ws):
    result = runner.invoke(app, ["context", "elicit"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines()[0].endswith("_requests.md")


def test_context_ingest_reports_topics(ws):
    runner.invoke(app, ["context", "elicit"])
    # ingest with an unfilled questionnaire writes nothing
    result = runner.invoke(app, ["context", "ingest"])
    assert result.exit_code == 0 and "Temas ingeridos" in result.output


def test_context_rm(ws):
    runner.invoke(app, ["context", "set", "proyecto", "nombre", "Mi App"])
    result = runner.invoke(app, ["context", "rm", "proyecto"])
    assert result.exit_code == 0 and "eliminado" in result.output
```

```python
# tests/integration/test_context_service.py (addition)
def test_write_requests_file_renders_pending_questionnaire(service, template):
    # service/template fixtures per this file's existing conventions
    service.create_document_fixture("doc1")  # or the file's existing setup
    path = service.context.write_requests_file("doc1", template)
    text = path.read_text(encoding="utf-8")
    assert "`proyecto`" in text  # pending topic rendered as a question block
```

**Expected test count:** ~6 CLI integration tests + ~1 service test (~7 total).
Needs implementer + fresh-context reviewer for the new
`ContextService.write_requests_file` method — the reviewer must verify: (a) it
composes `status` + `render_requests` + `write_requests` without duplicating
any parsing/rendering logic (all three already exist); (b) `context set`'s
Typer argument order (`topic field value`) matches legacy `ctx_set`
(3928–3931) so scripted invocations keep working; (c) `context status`'s
exit-code-on-all-complete matches `command_context_status` (3709–3710); (d)
the dropped interactive branch is genuinely absent (grep the command for
`isatty`/`input` — there must be none).

## Global constraints

- **Every task is TDD**: failing test first, minimal implementation, full
  suite run (`rtk pytest -q`) after each task, commit per task.
- **`typer` is added once, in Task 1** (`uv add typer`), with a
  `[project.scripts]` entrypoint `docs = "docs.cli.main:main"`. No other new
  third-party dependency.
- **The CLI layer is a thin adapter.** Every command: resolve context → call
  **one** application-service method (or one pure domain function, for
  `review-rules`) → format the returned value object to stdout. No business
  logic, no domain rules, no persistence decisions in `cli/`. The only
  computation the CLI performs is argument marshalling, `resolve_normative_settings`
  (a pure domain call), `_rules_manifest_state`/`_context_confirmed_lines`
  (thin file-state/context reads that mirror existing service internals
  verbatim), and output formatting — matching the hexagonal boundary held
  across all 14 prior slices.
- **`cli/` imports application + domain, never the reverse.** No module under
  `src/docs/domain` or `src/docs/application` may import from `docs.cli`
  (grep-verifiable). The one application-layer addition this slice makes
  (`ContextService.write_requests_file`, Judgment call 4) lives in the
  application layer, not the CLI.
- **`build-section`'s NotImplementedError-equivalent gap is surfaced, not
  fixed** (Judgment call 3). The command must never call
  `ReviewService.build_section` with fabricated `source_hash`/`prompt_hash`;
  it prints a clean error and exits `1`.
- **Config assembly reuses the ports, not raw file reads.**
  `Deps.resolve_context` reads documents/templates only through
  `JsonDocumentRepository` (Judgment call 1); it introduces no new filesystem
  access outside an existing port.
- **Exit codes are byte-for-byte legacy parity** (Judgment call 5): `doctor`
  0/2; `review-rules`/`review-section`/`review-document`/`pipeline`/`verify`/
  `format-audit-docx` 0/1; `context status` 0/1; everything else 0. Unexpected
  exceptions map to legacy's `main()` `ERROR: {exc}` on stderr + exit 1.
- **Spanish user-facing strings are preserved verbatim** from legacy
  `command_*` (this is an existing Spanish-language CLI being migrated, not new
  copy — the persona's language rules do not apply to migrated artifacts).
- **No harness-global constants** (`REPO_ROOT`, `HARNESS_ROOT`,
  `DOCUMENTS_DIR`, `RUNS_DIR`, `DEFAULT_CONFIG`, `TEMPLATES_DIR`,
  `DOCUMENTS_SCRIPTS`) may appear in `src/docs` after this slice
  (grep-verifiable) — workspace roots come from env/cwd, `repo_root` from
  `--repo-root` (Judgment call 2).

## Risks and open judgment calls

1. **RESOLVED — the config-assembly pipeline is ported into the CLI
   composition layer** (Judgment call 1). Risk: `Deps.resolve_context` is the
   single point every command depends on; a merge-order bug there breaks all
   37 commands at once. Mitigation: Task 1's fresh-context review specifically
   diffs the resolved `config["paths"]` against a hand-built fixture and
   confirms template-under-document merge order + computed-paths-win overlay
   match legacy `load_document` (340–347). Downstream note: because
   `resolve_context` calls `Template.model_validate(merged)`, a template/document
   that produces a config failing Pydantic validation will surface as a clean
   `ValidationError` → `main()` `ERROR:` line, not a crash — acceptable and
   consistent with legacy raising on malformed config.
2. **RESOLVED — `build-section` surfaces its gap, does not implement it**
   (Judgment call 3). Downstream effect: `docs build-section <id>` always exits
   `1` with an explanatory message until a future slice models
   draft-rendering + `prompts_dir`. Identical, inherited limitation from
   Slice 14's `build-sections` pipeline stage — not a regression introduced
   here.
3. **RESOLVED — `context elicit` drops the interactive TTY loop**
   (Judgment call 4). Downstream effect: `docs context elicit` always writes
   the `_requests.md` questionnaire; there is no interactive prompt mode. The
   `--requests` flag is accepted-but-inert for compatibility. A future slice
   could add an interactive adapter behind a port if desired, without touching
   this slice's shape.
4. **Intentional drop — legacy `--config report.yaml` compatibility mode.**
   `resolve_config`'s final `load_report_config` fallback (358–361) is not
   ported; this migration is document-first and has no `report.yaml`.
   `resolve_context` resolves via `--doc`/active-document only. Flagged so a
   reviewer does not mistake the absent branch for an oversight. If a legacy
   `report.yaml` must still be readable, that is a separate, additive
   follow-up (a `--config` option that bypasses `resolve_context`), not part of
   this slice's scope.
5. **Low-stakes, plan-author's call, not escalated:** each later task adds its
   commands to the single `cli/main.py` file (rather than one module per
   group). This mirrors legacy's single-file `build_parser` and Slice 14's
   pattern of tasks 4/5/6 all growing `application/pipeline.py`. Sub-agents run
   the tasks sequentially (TDD, commit per task), so additive edits to
   `main.py` do not conflict. A reviewer could reasonably prefer one
   `cli/commands/<group>.py` module per task with a `register(app)` hook; that
   refactor is cheap and non-load-bearing, flagged for their judgment rather
   than pre-decided.
6. **Low-stakes:** the `--repo-root` option (default `Path.cwd()`) appears on
   `pipeline`/`verify`/`collect-issues`/`collect-code-evidence` because their
   services require `repo_root`. In legacy this was the implicit `REPO_ROOT`
   module constant. A reviewer should confirm the default (`Path.cwd`, passed
   as a Typer default-factory, not evaluated at import time) is the intended
   "the directory the user runs `docs` from" semantics; if a project ever needs
   a fixed repo root, it is a one-line env-var addition, not a reshape.
