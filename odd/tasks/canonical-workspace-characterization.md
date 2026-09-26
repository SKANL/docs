# Canonical workspace migration characterization

Objective: Characterize the existing unversioned workspace layout before implementing migration.

Scope: fixtures and characterization tests only; no schema validation, runtime rejection, or migration code.

Tasks:
- [x] W1 Add sanitized legacy workspace fixture covering registry, document, template, context, sections, inbox identity, assets, provenance, and references.
- [x] W2 Extend characterization tests to assert source paths, bytes, hashes, identities, and malformed registry behavior.
- [x] W3 Update workspace format inventory with observed evidence and unresolved contradictions.

Authorized scope: tests/fixtures/workspaces/legacy/current-unversioned, tests/** characterization tests, docs/superpowers/specs/2026-09-21-workspace-format-inventory.md.
Checks: focused pytest command from worker report; git diff --check.
Route: delegated direct; mapping/writer triggers fired because implementation spans multiple files and requires reading existing repositories/tests.
Progress: W1-W3 complete. Focused pytest: 97 passed; Ruff passed; git diff --check passed.\nEvidence: delegated writer report; fixture privacy scan passed.
Next step: delegate one bounded writer.

