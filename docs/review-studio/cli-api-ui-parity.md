# Review Studio CLI → API → UI parity matrix

This S0.1 inventory is derived from registered Typer leaf-command metadata. A capability is `available` only when an equivalent X20 HTTP operation exists; `planned` commands have no route and must not be rendered as actions. `web+desktop` describes the intended shared frontend, not current UI delivery. UI proof is owned by later slices (especially S7).

| CLI command | API operation | API status | UI surface/action | Owning slice | Required scopes |
| --- | --- | --- | --- | --- | --- |
| `docs apply-corrections` | `POST /v2/documents/{document_id}/corrections/apply` | available | Not exposed yet (API only) | S4 | `documents:write` |
| `docs build-docx` | `POST /v2/documents/{document_id}/build-docx` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs build-ledger` | `POST /v2/documents/{document_id}/build-ledger` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs build-rules` | `POST /v2/documents/{document_id}/build-rules` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs build-section` | `POST /v2/documents/{document_id}/sections/{section_id}/build` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs collect-code-evidence` | `POST /v2/documents/{document_id}/collect-code-evidence` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs collect-issues` | `POST /v2/documents/{document_id}/collect-issues` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs collect-sources` | `POST /v2/documents/{document_id}/collect-sources` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs doctor` | `GET /v2/diagnostics` | available | Not exposed yet (API only) | S0 | `documents:read` |
| `docs explain` | `GET /v2/issue-codes/{code}` | available | Not exposed yet (API only) | S0 | `documents:read` |
| `docs format-audit-docx` | `POST /v2/documents/{document_id}/format-audit-docx` | available | Not exposed yet (API only) | S6 | `documents:read` |
| `docs guide` | — | excluded | Excluded (CLI only): Prints the packaged agent contract (docs/data/AGENTS.md) to stdout so a terminal-driven AI agent can bootstrap itself; the Review Studio is the guided surface and has no agent-instruction action. | S0 | — |
| `docs pack-context` | `POST /v2/documents/{document_id}/context-pack` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs qa-docx` | `POST /v2/documents/{document_id}/qa-docx` | available | Not exposed yet (API only) | S4 | `documents:write` |
| `docs review-document` | `POST /v2/documents/{document_id}/review` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs review-rules` | `POST /v2/documents/{document_id}/review-rules` | available | Not exposed yet (API only) | S6 | `documents:read` |
| `docs review-section` | `POST /v2/documents/{document_id}/sections/{section_id}/review` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs stamp` | — | excluded | Excluded (CLI only): Prints a bare local timestamp for stamps an agent writes by hand; over HTTP the server stamps sections itself, with its own clock, through POST /v2/documents/{document_id}/sections/{section_id}/stamp. | S0 | — |
| `docs stamp-section` | `POST /v2/documents/{document_id}/sections/{section_id}/stamp` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs translate` | `POST /v2/translations` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs asset add` | `POST /v2/documents/{document_id}/assets` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs asset list` | `GET /v2/documents/{document_id}/assets` | available | Not exposed yet (API only) | S2 | `documents:read` |
| `docs asset rm` | `DELETE /v2/documents/{document_id}/assets/{asset_name}` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs context elicit` | `POST /v2/documents/{document_id}/context/requests` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs context ingest` | `POST /v2/documents/{document_id}/context/ingest` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs context rm` | `DELETE /v2/documents/{document_id}/context/{topic_id}` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs context set` | `POST /v2/documents/{document_id}/context` | available | Planned shared web+desktop action; no S0.1 UI | S2 | `documents:write` |
| `docs context show` | `GET /v2/documents/{document_id}/context/{topic_id}` | available | Not exposed yet (API only) | S2 | `documents:read` |
| `docs context status` | `GET /v2/documents/{document_id}/context` | available | Planned shared web+desktop action; no S0.1 UI | S2 | `documents:read` |
| `docs doc current` | `GET /v2/current-document` | available | Workspace page (`#workspace`): active document | S1 | `documents:read` |
| `docs doc delete` | `DELETE /v2/documents/{document_id}` | available | Workspace page (`#workspace`): delete confirmation | S1 | `documents:write` |
| `docs doc init` | — | excluded | Excluded (CLI only): Bootstraps the process current directory (writes docs.config.json and registers it as the local workspace); over HTTP a workspace is created with POST /v2/workspaces. | S1 | — |
| `docs doc list` | `GET /v2/documents` | available | Workspace page (`#workspace`): document list | S1 | `documents:read` |
| `docs doc new` | `POST /v2/documents` | available | Workspace page (`#workspace`): create document dialog | S1 | `documents:write` |
| `docs doc rename` | `PATCH /v2/documents/{document_id}` | available | Workspace page (`#workspace`): rename document dialog | S1 | `documents:write` |
| `docs doc revise` | `POST /v2/documents/{document_id}/revisions` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs doc show` | `GET /v2/documents/{document_id}` | available | Not exposed yet (API only) | S1 | `documents:read` |
| `docs doc status` | `GET /v2/documents/{document_id}/summary` | available | Not exposed yet (API only) | S1 | `documents:read` |
| `docs doc use` | `POST /v2/documents/{document_id}/use` | available | Workspace page (`#workspace`): select document | S1 | `documents:write` |
| `docs document baseline` | `POST /v2/baselines/promotions` | available | Not exposed yet (API only) | S4 | `baselines:write` |
| `docs document build` | `POST /v2/documents/{document_id}/build` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document classify` | `POST /v2/documents/{document_id}/classification` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs document diff` | `POST /v2/artifacts/diff` | available | Not exposed yet (API only) | S4 | `artifacts:read` |
| `docs document evidence` | `GET /v2/runs/{run_id}/evidence` | available | Not exposed yet (API only) | S4 | `passport:read` |
| `docs document import` | `POST /v2/documents/{document_id}/imports` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs document ingest` | `POST /v2/documents/{document_id}/ingest` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs document inspect` | `GET /v2/artifacts/{artifact_id}/inspect` | available | Not exposed yet (API only) | S4 | `artifacts:read` |
| `docs document package` | `POST /v2/documents/{document_id}/package` | available | Not exposed yet (API only) | S5 | `documents:write` |
| `docs document passport` | `GET /v2/runs/{run_id}/passport` | available | Not exposed yet (API only) | S4 | `passport:read` |
| `docs document plan` | `POST /v2/documents/{document_id}/plan` | available | Not exposed yet (API only) | S3 | `documents:read` |
| `docs document prepare` | `POST /v2/documents/{document_id}/prepare` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document publish` | `POST /v2/documents/{document_id}/publications` | available | Not exposed yet (API only) | S5 | `documents:write` |
| `docs document release` | `POST /v2/documents/{document_id}/run` | available | Not exposed yet (API only) | S5 | `documents:write` |
| `docs document run` | `POST /v2/documents/{document_id}/run` | available | Not exposed yet (API only) | S3 | `documents:write` |
| `docs document status` | `GET /v2/documents/{document_id}/status` | available | Workspace page (`#workspace`): document status panel | S6 | `documents:read` |
| `docs document verify` | `POST /v2/documents/{document_id}/verify` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs run cancel` | `POST /v2/runs/{run_id}/cancel` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:write` |
| `docs run list` | `GET /v2/runs` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:read` |
| `docs run retry` | `POST /v2/runs/{run_id}/retry` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:write` |
| `docs run show` | `GET /v2/runs/{run_id}` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:read` |
| `docs run watch` | `GET /v2/runs/{run_id}/progress` | available | Not exposed yet (API only) | S3 | `runs:read` |
| `docs source ingest` | `POST /v2/documents/{document_id}/ingest` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs template create` | `POST /v2/templates` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs template init` | `POST /v2/templates` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs template list` | `GET /v2/templates` | available | Planned shared web+desktop action; no S0.1 UI | S6 | `documents:read` |
| `docs template show` | `GET /v2/templates/{template_name}` | available | Not exposed yet (API only) | S6 | `documents:read` |
| `docs template use` | `POST /v2/templates/{template_name}/use` | available | Not exposed yet (API only) | S6 | `documents:write` |
| `docs template validate` | `POST /v2/templates/{template_name}/validate` | available | Not exposed yet (API only) | S6 | `documents:read` |
| `docs workspace create` | `POST /v2/workspaces` | available | Workspace page (`#workspace`): create dialog | S1 | `workspaces:write` |
| `docs workspace delete` | `DELETE /v2/workspaces/{workspace_id}` | available | Workspace page (`#workspace`): delete confirmation | S1 | `workspaces:write` |
| `docs workspace list` | `GET /v2/workspaces` | available | Workspace page (`#workspace`): switcher | S1 | `workspaces:read` |
| `docs workspace migrate` | `POST /v2/workspaces/{workspace_id}/migrate` | available | Workspace page (`#workspace`): migration dialog | S1 | `workspaces:write` |
| `docs workspace rename` | `PATCH /v2/workspaces/{workspace_id}` | available | Workspace page (`#workspace`): rename dialog | S1 | `workspaces:write` |
| `docs workspace status` | `GET /v2/workspaces/{workspace_id}/status` | available | Workspace page (`#workspace`): migration status | S1 | `workspaces:read` |
| `docs workspace use` | `POST /v2/workspaces/{workspace_id}/use` | available | Workspace page (`#workspace`): switcher selection | S1 | `workspaces:write` |
