# Canonical workspace migration characterization

Objective: Characterize the existing unversioned workspace layout and record the approved canonical workspace/migration contract before implementation.

Scope: fixtures, characterization tests, and the workspace decision/implementation documents only; no schema validation, runtime rejection, or migration code.

Tasks:
- [x] W1 Add sanitized legacy workspace fixture covering registry, document, template, context, sections, inbox identity, assets, provenance, and references.
- [x] W2 Extend characterization tests to assert source paths, bytes, hashes, identities, and malformed registry behavior.
- [x] W3 Update workspace format inventory with observed evidence and unresolved contradictions.
- [x] W4 Reconcile the decision contract: one registered root, exact strict marker, separate-destination migration, exclusions, generated-artifact handling, and recovery.

Authorized scope: tests/fixtures/workspaces/legacy/current-unversioned, tests/** characterization tests, docs/superpowers/specs/2026-09-21-workspace-format-inventory.md, docs/superpowers/plans/2026-09-21-workspace-migration.md, and this task document.
Checks: focused pytest command from characterization worker report; Markdown structural sanity check; git diff --check.
Route: delegated direct; mapping/writer triggers fired because implementation spans multiple files and requires reading existing repositories/tests.
Progress: W1-W4 complete. Characterization evidence: focused pytest 97 passed; Ruff passed; fixture privacy scan passed. Decision reconciliation is documentation-only; commit `6970b05a` records the approved contract, and Markdown sanity plus `git show --check` passed.
Next step: implement Task 2 from the approved contract with failing validator tests first.

