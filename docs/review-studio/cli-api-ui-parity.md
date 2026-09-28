# Review Studio CLI → API → UI parity matrix

This S0.1 inventory is derived from registered Typer leaf-command metadata. A capability is `available` only when an equivalent X20 HTTP operation exists; `planned` commands have no route and must not be rendered as actions. `web+desktop` describes the intended shared frontend, not current UI delivery. UI proof is owned by later slices (especially S7).

| CLI command | API operation | API status | UI surface/action | Owning slice | Required scopes |
| --- | --- | --- | --- | --- | --- |
| `docs apply-corrections` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs build-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-ledger` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-rules` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs build-section` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs collect-code-evidence` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs collect-issues` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs collect-sources` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs doctor` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs explain` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs format-audit-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs guide` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs pack-context` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs qa-docx` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs review-document` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs review-rules` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs review-section` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs stamp` | — | planned | Planned shared web+desktop action; no S0.1 UI | S0 | — |
| `docs stamp-section` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs translate` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs asset add` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs asset list` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs asset rm` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs context elicit` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs context ingest` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs context rm` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs context set` | `POST /v2/documents/{document_id}/context` | available | Planned shared web+desktop action; no S0.1 UI | S2 | `documents:write` |
| `docs context show` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs context status` | `GET /v2/documents/{document_id}/context` | available | Planned shared web+desktop action; no S0.1 UI | S2 | `documents:read` |
| `docs doc current` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc delete` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc init` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc list` | `GET /v2/documents` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `documents:read` |
| `docs doc new` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc rename` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc revise` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs doc show` | `GET /v2/documents/{document_id}` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `documents:read` |
| `docs doc status` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs doc use` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs document baseline` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document build` | `POST /v2/documents/{document_id}/build` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document classify` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs document diff` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document evidence` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document import` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs document ingest` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs document inspect` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document package` | — | planned | Planned shared web+desktop action; no S0.1 UI | S5 | — |
| `docs document passport` | — | planned | Planned shared web+desktop action; no S0.1 UI | S4 | — |
| `docs document plan` | — | planned | Planned shared web+desktop action; no S0.1 UI | S3 | — |
| `docs document prepare` | `POST /v2/documents/{document_id}/prepare` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs document publish` | — | planned | Planned shared web+desktop action; no S0.1 UI | S5 | — |
| `docs document release` | — | planned | Planned shared web+desktop action; no S0.1 UI | S5 | — |
| `docs document run` | — | planned | Planned shared web+desktop action; no S0.1 UI | S3 | — |
| `docs document status` | `GET /v2/documents/{document_id}/status` | available | Planned shared web+desktop action; no S0.1 UI | S6 | `documents:read` |
| `docs document verify` | `POST /v2/documents/{document_id}/verify` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `documents:write` |
| `docs run cancel` | `POST /v2/runs/{run_id}/cancel` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:write` |
| `docs run list` | `GET /v2/runs` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:read` |
| `docs run retry` | `POST /v2/runs/{run_id}/retry` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:write` |
| `docs run show` | `GET /v2/runs/{run_id}` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:read` |
| `docs run watch` | `GET /v2/runs/{run_id}/progress` | available | Planned shared web+desktop action; no S0.1 UI | S3 | `runs:read` |
| `docs source ingest` | — | planned | Planned shared web+desktop action; no S0.1 UI | S2 | — |
| `docs template create` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template init` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template list` | `GET /v2/templates` | available | Planned shared web+desktop action; no S0.1 UI | S6 | `documents:read` |
| `docs template show` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template use` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs template validate` | — | planned | Planned shared web+desktop action; no S0.1 UI | S6 | — |
| `docs workspace create` | `POST /v2/workspaces` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `workspaces:write` |
| `docs workspace delete` | `DELETE /v2/workspaces/{workspace_id}` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `workspaces:write` |
| `docs workspace list` | `GET /v2/workspaces` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `workspaces:read` |
| `docs workspace migrate` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs workspace rename` | `PATCH /v2/workspaces/{workspace_id}` | available | Planned shared web+desktop action; no S0.1 UI | S1 | `workspaces:write` |
| `docs workspace status` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
| `docs workspace use` | — | planned | Planned shared web+desktop action; no S0.1 UI | S1 | — |
