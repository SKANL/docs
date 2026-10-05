# Review Studio CLI → API → UI parity matrix

This S0.1 inventory is derived from registered Typer leaf-command metadata. A capability is `available` only when an equivalent X20 HTTP operation exists; `planned` commands have no route and must not be rendered as actions. `web+desktop` describes the intended shared frontend, not current UI delivery. UI proof is owned by later slices (especially S7).

| CLI command | API operation | API status | UI surface/action | Owning slice | Required scopes |
| --- | --- | --- | --- | --- | --- |
| `docs apply-corrections` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs build-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-ledger` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-rules` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-section` | `POST /v2/documents/{document_id}/sections/{section_id}/build` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs collect-code-evidence` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs collect-issues` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs collect-sources` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs doctor` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs explain` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs format-audit-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs guide` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs pack-context` | `POST /v2/documents/{document_id}/context-pack` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs qa-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs review-document` | `POST /v2/documents/{document_id}/review` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs review-rules` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs review-section` | `POST /v2/documents/{document_id}/sections/{section_id}/review` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs stamp` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs stamp-section` | `POST /v2/documents/{document_id}/sections/{section_id}/stamp` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs translate` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
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
| `docs doc init` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc list` | `GET /v2/documents` | available | Workspace page (`#workspace`): document list | S1 | `documents:read` |
| `docs doc new` | `POST /v2/documents` | available | Workspace page (`#workspace`): create document dialog | S1 | `documents:write` |
| `docs doc rename` | `PATCH /v2/documents/{document_id}` | available | Workspace page (`#workspace`): rename document dialog | S1 | `documents:write` |
| `docs doc revise` | `POST /v2/documents/{document_id}/revisions` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs doc show` | `GET /v2/documents/{document_id}` | available | Not exposed yet (API only) | S1 | `documents:read` |
| `docs doc status` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc use` | `POST /v2/documents/{document_id}/use` | available | Workspace page (`#workspace`): select document | S1 | `documents:write` |
| `docs document baseline` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document build` | `POST /v2/documents/{document_id}/build` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document classify` | `POST /v2/documents/{document_id}/classification` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs document diff` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document evidence` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document import` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs document ingest` | `POST /v2/documents/{document_id}/ingest` | available | Not exposed yet (API only) | S2 | `documents:write` |
| `docs document inspect` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document package` | — | planned | Planned shared web+desktop action; no S0.1 UI | S5 | — |
| `docs document passport` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document plan` | `POST /v2/documents/{document_id}/plan` | available | Not exposed yet (API only) | S3 | `documents:read` |
| `docs document prepare` | `POST /v2/documents/{document_id}/prepare` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document publish` | — | planned | Planned shared web+desktop action; no S0.1 UI | S5 | — |
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
| `docs template create` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template init` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template list` | `GET /v2/templates` | available | Planned shared web+desktop action; no S0.1 UI | S6 | `documents:read` |
| `docs template show` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template use` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template validate` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs workspace create` | `POST /v2/workspaces` | available | Workspace page (`#workspace`): create dialog | S1 | `workspaces:write` |
| `docs workspace delete` | `DELETE /v2/workspaces/{workspace_id}` | available | Workspace page (`#workspace`): delete confirmation | S1 | `workspaces:write` |
| `docs workspace list` | `GET /v2/workspaces` | available | Workspace page (`#workspace`): switcher | S1 | `workspaces:read` |
| `docs workspace migrate` | `POST /v2/workspaces/{workspace_id}/migrate` | available | Workspace page (`#workspace`): migration dialog | S1 | `workspaces:write` |
| `docs workspace rename` | `PATCH /v2/workspaces/{workspace_id}` | available | Workspace page (`#workspace`): rename dialog | S1 | `workspaces:write` |
| `docs workspace status` | `GET /v2/workspaces/{workspace_id}/status` | available | Workspace page (`#workspace`): migration status | S1 | `workspaces:read` |
| `docs workspace use` | `POST /v2/workspaces/{workspace_id}/use` | available | Workspace page (`#workspace`): switcher selection | S1 | `workspaces:write` |
