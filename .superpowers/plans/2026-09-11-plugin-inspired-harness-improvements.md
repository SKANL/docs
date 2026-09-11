# Plugin-inspired harness improvements

## Objective
Improve the native `docs` harness using design lessons from Documents, PDF, and Template Creator without importing, invoking, or depending on those plugins. Markdown, templates, configuration, and source assets remain authoritative; DOCX remains primary and HTML/PDF are derived.

## Implemented scope

- Artifact contracts: deterministic artifact references, verification findings/reports, render profiles, and lifecycle states.
- Provenance: content-addressed provenance models with legacy compatibility.
- Atomic transforms: scratch-space execution, output validation, and safe publication/rollback.
- Render verification: internal PDF/DOCX rendering checks, previews, blank-page and layout checks.
- Structural audit: headings, tables, captions, references, assets, and format-independent findings.
- Template fidelity: optional geometry/style/component/slot/asset/fidelity contract with legacy normalization.
- Pipeline QA gates: render/structural errors block assembly; optional tools degrade explicitly.
- Review dimensions: editorial, evidence, consistency, structural, accessibility, and visual findings.
- Documentation: native contracts, QA evidence paths, degradation rules, provenance, and plugin boundary.
- Regression preservation: deterministic writer invariant and characterization snapshots updated for the intentional review dimension field.

## Constraints

- No plugin imports, manifests, connectors, CODEX_HOME paths, or plugin dependencies.
- No authored section content is overwritten by scaffolding or visual generation.
- Optional external tools remain lazy and degradable.
- Outputs are generated only through the harness pipeline.
- Internal and delivery CISSP documents remain separate.

## Verification and delivery

1. Run the unit/integration/architecture suite, Ruff, and mypy.
2. Run `review-document --json`, `pipeline assemble --format docx --format html --format pdf`, `verify --json`, and `doc mark-final` per document.
3. Render final PDFs to PNG previews and inspect blank pages, overflow, tables, captions, references, covers, and embedded visual labels.
4. Record exact final PDF paths and preserve output/final as the approved snapshot.

## Known boundary

The implementation keeps legacy run logs readable and preserves existing document behavior. The current provenance model and QA gates are native harness capabilities; future work may deepen run-level provenance binding for every published artifact without changing the public plugin boundary.
