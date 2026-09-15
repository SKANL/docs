# Legacy runtime retirement inventory

Baseline: `63b09da` (`origin/main` after PR #73).

| Category | Current location | Target action | Replacement |
|---|---|---|---|
| Legacy application pipeline | `src/docs/application/pipeline.py` | Remove | Native document pipeline |
| Flat compatibility routing | `removed compatibility module` | Remove | Native document/source commands |
| Flat compatibility adapter | `src/docs/application/flat_pipeline_v2.py` | Remove after command migration | Native stage planner/executor |
| Legacy CLI composition | `src/docs/cli/commands/core_app.py` pipeline/verify paths | Remove | `document ingest/prepare/build/verify` |
| Legacy final promotion | `src/docs/cli/commands/doc_app.py` `document publish` | Remove | `document publish` |
| Transitional v2 names | `*_v2.py` application modules | Rename to canonical names | Same native implementation |
| Legacy tests | `tests/unit/application/test_pipeline_service.py`, legacy CLI cases, `tests/integration/test_pipeline_service.py` | Remove or rewrite | Native v2 contract/integration tests |
| Migration documentation | `docs/runtime.md`, compatibility sections | Rewrite/remove | Canonical v2 workflow |
| Authored document sources | CISSP Markdown, context and assets | Preserve | Native v2 inputs |
| Derived legacy outputs | CISSP `output/draft`, `output/body` and old run logs | Remove after v2 rebuild | `output/v2`, v2 manifests and provenance |

This inventory is deliberately committed before deletion so the retirement can be reviewed against a fixed baseline.

