# Canonical API v2 contract inventory

**Status: approved Task 1 contract basis; DTO schemas remain to be defined in Task 2.** The user authorized breaking changes, migrations, and resolving blockers by choosing solutions. This record applies that authority conservatively to freeze route scope and key transport semantics before route implementation.

## Task 1 contract scope

Decision: replace supported operations with `/v2`, publish no `/v1` aliases, and make one strict transport schema the source for OpenAPI and generated TypeScript clients. DTO field schemas and exact response mappings remain Task 2 work; the operation scope and semantic rulings below are the Task 1 contract baseline.

## Current operation inventory

The current OpenAPI builder advertises OpenAPI 3.1.0, `info.version: 1.0.0`, and these `/v1` operations. The operation registry is hand-authored in `src/docs/api/openapi.py`; the implementation independently registers routes in `src/docs/api/application.py`. Route presence is therefore not proof that every response/request is fully described by OpenAPI.

| Resource | Current operations |
|---|---|
| Workspaces | `GET, POST /v1/workspaces`; `GET, PATCH, DELETE /v1/workspaces/{workspace_id}`; `POST /v1/workspaces/{workspace_id}/select` |
| Documents | `GET, POST /v1/documents`; `POST /v1/documents/import`; `POST /v1/documents/import/raw`; `GET /v1/documents/{document_id}`; `GET /v1/documents/{document_id}/status`; `GET /v1/documents/{document_id}/sections`; `GET, PUT /v1/documents/{document_id}/sections/{section_id}`; `GET, POST /v1/documents/{document_id}/context`; `GET, POST /v1/documents/{document_id}/classification`; `GET /v1/documents/{document_id}/runs`; `POST /v1/documents/{document_id}/{prepare,build,verify,publish}`; `POST /v1/documents/{document_id}/revisions` |
| Graph and collections | `GET /v1/graph`; `GET /v1/findings`; `GET /v1/artifacts`; `GET /v1/templates`; `GET /v1/revisions`; `GET /v1/publications` |
| Runs | `GET, POST /v1/runs`; `GET /v1/runs/{run_id}`; `POST /v1/runs/{run_id}/{cancel,retry}`; `GET /v1/runs/{run_id}/passport`; `GET /v1/runs/{run_id}/artifacts`; `GET /v1/runs/{run_id}/progress` (SSE); `GET /v1/runs/{run_id}/graph`; runtime-only `GET /v1/runs/{run_id}/findings` and `GET /v1/runs/{run_id}/previews/{name}` (retain and add to v2 OpenAPI). |
| Artifacts, revisions, baselines, plugins | `GET /v1/artifacts/{artifact_id}`; `GET /v1/artifacts/{artifact_id}/previews`; `GET /v1/revisions/{revision_id}`; `GET, POST /v1/baselines`; `GET /v1/baselines/{baseline_id}`; `POST /v1/baselines/{baseline_id}/promote`; `POST /v1/baselines/promotions`; `GET /v1/plugins`; `GET /v1/plugins/{plugin_id}` |
| Contract endpoint | `GET /v1/openapi.json` |

`{prepare,build,verify,publish}` above denotes four literal paths, not a route wildcard. Detail, status, and mutation routes are installed dynamically; the route table also has static entries. The two runtime-only run routes are implemented in `application.py` but absent from OpenAPI. Reconcile all registrations with the contract before implementation.

## Current wire-contract facts

### Operation-to-handler crosswalk

This compact operation-level supplement maps each OpenAPI method/path to the implementation dispatch. `Declared` shapes are not proven typed runtime DTOs: the OpenAPI builder is literal dictionaries and several handlers return arbitrary domain/use-case payloads. Unless stated, OpenAPI `_operation` declares common 400/401/404 `error` responses; runtime can add other codes. Scope is `_required_scope` when an auth validator is configured; a missing validator disables auth in the application.

| Method + path | Handler; request → declared success | Scope | Workspace/authorization behavior / gaps |
|---|---|---|---|
| GET `/v1/openapi.json` | `_openapi`; none → 200 OpenAPI | none | Static public route; emits canonical JSON. |
| GET `/v1/workspaces` | `_workspaces`; none → 200 page<workspace> declared | workspaces:read | Runtime response is `{items,active}`, not declared page. |
| POST `/v1/workspaces` | `_create_workspace`; workspace body → declared 200 workspace (runtime 201) | workspaces:write | Creates registry entry/layout, seeds templates. |
| GET `/v1/workspaces/{workspace_id}` | `_workspace`; none → 200 workspace | workspaces:read | Registry lookup; missing => 404. |
| PATCH `/v1/workspaces/{workspace_id}` | `_rename_workspace`; `{name}` → 200 workspace | workspaces:write | Conflict => 409; missing => 404. |
| DELETE `/v1/workspaces/{workspace_id}` | `_delete_workspace`; none → 200 generic object | workspaces:write | Deletes registry entry, runtime `{deleted}`. |
| POST `/v1/workspaces/{workspace_id}/select` | `_select_workspace`; none → 200 workspace | workspaces:write | Makes workspace active. |
| GET `/v1/documents` | `_documents`; query/page → 200 page<document> | documents:read | Optional workspace query, sometimes active/global fallback; authenticated ownership filter. |
| POST `/v1/documents` | `_create_document`; request undocumented → declared 200 document (runtime 201) | documents:write | Runtime reads workspace_id/document_id/template/title; explicit workspace. |
| POST `/v1/documents/import` | `_import_document`; `{workspace_id,filename,content_base64}` required, optional document_id/template/title → 201 import_job | documents:write | Explicit workspace; persists import metadata; ImportError => 400. |
| POST `/v1/documents/import/raw` | `_import_raw_document`; raw bytes + query workspace_id/document_id/template/title + `x-docs-filename` → 201 import_job | documents:write | Explicit workspace; binary body differs OpenAPI's JSON request declaration. |
| GET `/v1/documents/{document_id}` | `_document`; optional workspace_id query → 200 document | documents:read | Explicit or active selection; underlying store/shape depends composition. |
| GET `/v1/documents/{document_id}/status` | `_document_status`; optional workspace_id → 200 generic object | documents:read | Explicit/active; requires document.json; missing workspace/document => 503/404. |
| GET `/v1/documents/{document_id}/sections` | `_document_sections`; optional workspace_id → 200 generic object | documents:read | Reads section files from selected workspace. |
| GET `/v1/documents/{document_id}/sections/{section_id}` | `_document_section`; optional workspace_id → 200 section | documents:read | Safe section ID; missing => 404. |
| PUT `/v1/documents/{document_id}/sections/{section_id}` | `_update_document_section`; `{body:string,request?:string}` → 200 revision | documents:write | Uses revision service, not direct file write; unavailable => 501. |
| GET `/v1/documents/{document_id}/context` | `_document_context`; query → 200 generic object | documents:read | Exact workspace/data selection not fully verified. |
| POST `/v1/documents/{document_id}/context` | `_document_context`; `{topic,value,field?}` → 200 generic object | documents:write | Runtime writer/error conditions need characterization. |
| GET `/v1/documents/{document_id}/classification` | `_document_classification`; query → 200 generic object | documents:read | Exact response mapping requires handler/tests review. |
| POST `/v1/documents/{document_id}/classification` | `_document_classification`; `{relative_path,confirmed_role}` → 200 generic object | documents:write | Role enum evidence/example/normative. |
| GET `/v1/documents/{document_id}/runs` | `_document_runs`; query/page → 200 page<run> | documents:read | Document association; ownership details not fully verified. |
| POST `/v1/documents/{document_id}/prepare` | `_document_action(prepare)`; workspace_id required, optional run_id/format/policy → 200 document | documents:write | Explicit workspace; may execute synchronously/use configured action. |
| POST `/v1/documents/{document_id}/build` | `_document_action(build)`; same → 202 run | documents:write | Explicit workspace, requires manifest, enqueues run. |
| POST `/v1/documents/{document_id}/verify` | `_document_action(verify)`; same → 202 run | documents:write | Explicit workspace, enqueues run. |
| POST `/v1/documents/{document_id}/publish` | `_document_action(publish)`; same → 202 run | documents:write | Explicit workspace, release policy default. |
| POST `/v1/documents/{document_id}/revisions` | `_revision`; request undocumented → 200 revision | documents:write | Exact request/workspace semantics to verify. |
| GET `/v1/graph` | `_graph`; graph query parameters → 200 graph declared | graph:read | Query supports additional source/target/node/relation/kind/label/direction beyond documented query/mode forms; authenticated graph with no registry => concealed 404. |
| GET `/v1/findings` | `_findings`; page/filter/workspace query → page<finding> | findings:read | Workspace defaults active; associated run scope and principal ownership filter. |
| GET `/v1/artifacts` | `_artifacts_collection`; page/filter/workspace query → page<artifact> | artifacts:read | Workspace defaults active, filters by owning run. |
| GET `/v1/templates` | `_templates`; page/filter/workspace query → page<document> declared | documents:read | Workspace-scoped helper; item schema `document` likely inaccurate/unverified. |
| GET `/v1/revisions` | `_revisions`; page/filter/workspace query → page<revision> | documents:read | Workspace-scoped helper. |
| GET `/v1/publications` | `_publications`; page/filter/workspace query → page<baseline> | documents:read | Workspace-scoped helper; response mapping needs confirmation. |
| GET `/v1/runs` | `_runs`; page/filter/workspace query → page<run> | runs:read | Filters workspace payload, then tenant/organization owner if authenticated. |
| POST `/v1/runs` | `_create_run`; declared run schema body, implementation JSON object → declared 200 run (runtime 201) | runs:write | Registry mode requires explicit workspace; authenticated requires tenant+organization and ownership metadata. |
| GET `/v1/runs/{run_id}` | `_run`; none → run | runs:read | Non-owner hidden as 404. |
| POST `/v1/runs/{run_id}/cancel` | `_cancel`; none → run | runs:write | Ownership required; state/idempotency details need tests. |
| POST `/v1/runs/{run_id}/retry` | `_retry`; none → run | runs:write | Ownership required; queue failure semantics need tests. |
| GET `/v1/runs/{run_id}/passport` | `_passport`; none → passport | passport:read | Run owner checked first. |
| GET `/v1/runs/{run_id}/artifacts` | `_artifacts`; page → page<artifact> | artifacts:read | Run owner checked. |
| GET `/v1/runs/{run_id}/progress` | `_progress`; none → text/event-stream | runs:read | SSE payload/reconnect contract not described. |
| GET `/v1/runs/{run_id}/findings` | `_run_findings`; no request body → response mapping not declared in OpenAPI | findings:read | Runtime-only path omitted from OpenAPI; run ownership checked, result paginated. **V2 ruling: retain and document.** |
| GET `/v1/runs/{run_id}/graph` | `_run_graph`; graph query → graph | graph:read | Run owner checked; binds workspace from run and hides mismatched workspace as 404. |
| GET `/v1/runs/{run_id}/previews/{name}` | `_preview`; no request body → binary/preview response not declared in OpenAPI | artifacts:read | Runtime-only path omitted from OpenAPI; resolves artifact under configured workspace boundary when available and checks run ownership. **V2 ruling: retain and document.** |
| GET `/v1/artifacts/{artifact_id}` | `_artifact`; none → artifact | artifacts:read | Associated run ownership checked. |
| GET `/v1/artifacts/{artifact_id}/previews` | `_artifact_previews`; page → page<preview> | artifacts:read | Parent artifact ownership checked. |
| GET `/v1/revisions/{revision_id}` | `_revision_detail`; optional workspace query → revision | documents:read | Searches selected workspace; missing => 404. |
| GET `/v1/baselines` | `_baselines`; page/workspace query → page<baseline> | baselines:read | Workspace-scoped helper. |
| POST `/v1/baselines` | **No matching owned registration/handler identified**; declared baseline body → baseline | OpenAPI declares baselines:write; runtime scope table does not cover it | No runtime implementation located in inspected `X20Application`. **V2 ruling: omit until implemented and added through an explicit later contract change.** |
| GET `/v1/baselines/{baseline_id}` | `_baseline`; none → baseline | baselines:read | Dynamic handler/store lookup. |
| POST `/v1/baselines/{baseline_id}/promote` | **No matching dynamic handler identified**; no request body → baseline declared | OpenAPI declares baselines:write; runtime scope table has no branch | No runtime implementation located in inspected `X20Application`. **V2 ruling: omit until implemented and added through an explicit later contract change.** |
| POST `/v1/baselines/promotions` | `_promote_baseline`; workspace_id plus baseline_id or id → baseline | baselines:write | Requires workspace in registry mode; delegates workspace-aware store method when available. |
| GET `/v1/plugins` | `_plugins`; page/filter/workspace query → page<plugin> | plugins:read | Exact workspace-registry choice needs handler-specific verification. |
| GET `/v1/plugins/{plugin_id}` | `_plugin`; none → plugin | plugins:read | Dynamic lookup; exact tenant/workspace fallback requires verification. |

Every route above is either a literal OpenAPI path or its matching `application.py` static/dynamic registration. OpenAPI declares a few payload/status shapes that differ from handlers; no claim of validated DTOs is made. The contract rulings below settle the v2 prefix and operation scope; Task 2 must still implement and verify exact DTO shapes.

### Cross-cutting transport behavior requiring canonicalization

- **Errors:** `src/docs/api/http.py:error_response` emits `{"error":{"code":...,"message":...,"details":...}}`; AuthError adds a 401 Bearer challenge; API 5xx and unknown exceptions mask details as `internal_error`. APIError details are passed through `enterprise.normalize_error` for non-5xx. Router emits `not_found` for unregistered routes. The OpenAPI operation helper generally advertises only 400/401/404 and can omit real 403/409/413/500/501/503 cases.
- **Auth:** Operation scopes appear both in OpenAPI and `_required_scope`, but security is conditional on the app's configured validator. `bearer_auth` parses Bearer credentials only; no runtime API-key parser was found. Workspace-scoped auth is a separate optional behavior; authenticated resources with missing/mismatched owner are hidden as 404. Generic `http.Router` OIDC policy and `X20Application` auth wrapping are distinct paths.
- **Workspace:** there is no single universal rule today: read collections often accept query `workspace_id` and may fall back to active workspace; document actions/imports and run creation use body/query scope; workspace selector mutates active selection; artifacts/findings infer scope by associated run. `/v2` should define scope for every operation and forbid accidental global fallback for a scoped credential.
- **Idempotency:** `Router` can receive `idempotency_persistence` and has key/replay behavior, but reviewed OpenAPI has no idempotency header/response contract. Determine methods covered, key syntax, mismatch/conflict response, and persistence lifetime from `http.py` and tests before carrying it into `/v2`.
- **SSE/binary:** event names/data/retry semantics at run progress and bytes/content-disposition/range semantics at runtime-only run preview have no complete OpenAPI schema. Freeze their content types, event schema, cancellation/ownership behavior, and cache rules or retire them.
- **Not an approved final route contract:** any operation missing a matching handler (notably baseline collection create and item promote in the inspected `X20Application`) must be called out; don't preserve a dead OpenAPI-only route merely for compatibility.

| Concern | Evidence-backed current behavior | V2 decision |
|---|---|---|
| DTO / schema source | `openapi.py` builds schemas and operations with dictionaries and hand-written refs; `application.py` serializes domain/store values via `_dict` and handler-specific maps. | Canonical explicit transport DTOs at API boundary; generated OpenAPI and TS types from one source. Keep domain models internal. |
| Success responses | Common collections use `{items, next_cursor}` pagination and cursor query; page limit schema is 1..100. Several operation schemas reference component names (`document`, `run`, etc.); implementation payloads include endpoint-specific shapes. Build/verify/publish are documented 202. SSE is text/event-stream. | Per-operation typed response; explicit optional/null semantics and status codes; no generic shape guessing. Confirm all actual handler shapes before finalizing DTOs. |
| Auth | OpenAPI advertises Bearer and `X-API-Key`, but inspected API runtime parses Bearer only; auth is optional when the app validator is absent. Operations declare scopes including `documents:read/write`, `runs:read/write`, `findings:read`, `artifacts:read`, `graph:read`, `baselines:read/write`, `plugins:read`, `passport:read`. | Correct OpenAPI to match runtime or intentionally add/test API-key support; choose explicit policy per deployment and operation. |
| Workspace | Selection is persisted as an `active` workspace in registry. Many collection/read handlers accept query `workspace_id`, often falling back to active workspace; create/action bodies may require workspace ID; raw import uses query parameters. Workspace-scoped auth is optional composition behavior. Some run resources infer ownership from run payload. | Define one explicit workspace-selection rule and transport location; require/derive scope consistently, authorize every resource against it, never silently fall back where scope is security-relevant. Unknown/unauthorized workspace behavior must not leak existence/data. |
| Errors | Standard JSON envelope is `{error:{code,message,details}}`; `AuthError` returns envelope, 401 defaults `WWW-Authenticate: Bearer realm="api"`; server errors conceal details using `internal_error`. `APIError` details may be normalized by enterprise helper; 404 is `not_found`. | One strict typed problem envelope with documented codes/details/statuses and stable auth headers; no legacy shape normalization. Decide whether HTTP problem-details compatibility is desired (not assumed). |
| Idempotency | Router supports idempotency persistence and request-level idempotency behavior; the detailed operation coverage is not fully expressed in route schemas. | Keep only where operations need safe retry; document key/header semantics per operation and characterize replay/conflict behavior before contract freeze. |

Historical frontend response normalization branches remain to be fully mapped endpoint-by-endpoint in `review-studio/src/api/client.ts`, `factory.ts`, and `models.ts`; canonical DTO work must remove permissive aliases unless the selected v2 operation schema explicitly retains them.

### Fresh audit corrections and consumer migration impact

This addendum supersedes any earlier statement implying that current API runtime accepts API keys. **V2 auth ruling: bearer-only when configured; local unauthenticated mode only when no validator is configured.**

#### Authentication and error/status behavior

| Concern | Read-only evidence | Consequence for `/v2` |
|---|---|---|
| Runtime auth mechanism | `src/docs/api/auth.py:bearer_auth` reads only `Authorization`, requires Bearer, then calls a configured validator. `X20Application._authenticated` bypasses auth when its validator is absent. No API-runtime `X-API-Key` parser was found in inspected source. | Current OpenAPI's bearer + `X-API-Key` security declaration overstates observed runtime support. Remove the key alternative or intentionally implement and test it; do not describe it as currently working. |
| OIDC and scopes | `src/docs/api/oidc.py` contains `BearerTokenValidator`, `OIDCValidator`, `require_policy`; generic `src/docs/api/http.py:Router` can apply validator and OIDC route policy. `X20Application._authenticated` separately invokes `bearer_auth` and `_required_scope`. | These are distinct mechanisms/wiring paths; exact production composition remains to be confirmed. Do not assume all deployments enforce OIDC, or merge OIDC claims validation with application scope registration in the contract. |
| OpenAPI error claims | `src/docs/api/openapi.py:_operation` lists only 400/401/404. | That is incomplete: source/tests show runtime statuses 403, 405, 409, 413, 422, 429, 500, 503 as well as the documented statuses. These are conditional per runtime/endpoint, not universally applicable. |
| Statuses and headers | 403: insufficient scope / CORS deny. 405: wrong method and `Allow`. 409: workspace-name/run-id conflicts and non-retryable run. 413: body exceeds configured limit. 422: generic APIError path exercised by `tests/unit/api/test_http.py`, not evidence that a particular business endpoint normally returns 422. 429: configured rate limiter, normalized details and `Retry-After`. 500: generic/masked `internal_error`. 503: workspace/context/service unavailable. 401: Bearer `WWW-Authenticate`; insufficient-scope challenge can name required scope. | Specify response schemas, headers and status per operation in `/v2`; distinguish generic transport capability from endpoint business behavior. Existing CORS denial has a minimal error object, and error normalization is not uniform enough to assume a single exact payload without tests. |

#### Review Studio consumer migrations

Current code accepts multiple historical/approximate wire shapes. These behaviors must be explicitly retired, formalized, or proved necessary; don't preserve them accidentally as aliases in `/v2`.

| Existing behavior | Evidence in source/tests | Canonical v2 rule |
|---|---|---|
| Page parser accepts raw arrays, `{items}`, `{data}`, `nextCursor` or `next_cursor`, optional total; absent/invalid arrays collapse to empty. | `review-studio/src/api/client.ts:page`, `ReviewApiClient.list`; client tests. | Select one page DTO; reject invalid shapes rather than display a false empty result. |
| Run normalizer passes already-normalized UI records or `{id,schema}` through; otherwise maps `payload.document_id`, template, started_at, duration_ms, progress/report, `created_at`, status; fabricates placeholders/default counts; accepts `succeeded` alongside UI states. | `review-studio/src/api/client.ts:normalizeRun`; `review-studio/src/test/client.test.ts` | Define strict run wire DTO and one UI mapping; decide whether `succeeded` is canonical. Do not retain default fabrication silently. |
| Graph normalizer maps kind aliases (`evidence/input/reference` to source), confidence from number or `{score}`, endpoint aliases `source/target` or `from/to`, default labels/positions/relation; graph query maps `graph_unavailable`, warnings and context to camelCase. | `client.ts:graphType`, `confidenceScore`, `normalizeGraph`, `normalizeGraphQuery`; graph client tests. | Define canonical graph + query DTO; remove aliases/defaults unless specifically approved semantics. |
| Artifact mapping guesses kind by substring; synthesizes missing id/name/size/status/checksum and accepts `digest` fallback; similar logic is duplicated for run artifacts. | `client.ts:normalizeArtifactKind`, `listArtifacts`, `listRunArtifacts`. | Define exact kind, bytes, status and digest fields once; strict response validation prevents placeholder metadata. |
| Passport accepts a shape already carrying coverage or synthesizes values from entries/pipeline report: client current timestamp as verifiedAt; coverage from stage pass ratio; attestations as entry count; sources and claims zero; unresolved as failure count. | `client.ts:getPassport`, `models.ts:EvidencePassport`, `review-studio/src/test/app.test.tsx` | Separate actual verified/server attestation data from UI-derived summary; never present client-derived timestamp/zeros as verified provenance. |
| Snake-case fields are aliased into camel-case findings; client request methods translate camel-case input into snake-case payloads. | `client.ts:listFindings`, `createDocument`, `createRun`, `documentAction`, `importDocument`; `models.ts`. | Adopt one wire naming convention and map only at a typed boundary; delete response shape probing. |
| App presentation falls back across names: plugin id/name, trust/trust_level, digest/hash/artifact_digest; baseline name/id and created/created_at; revision author/authored_by, date/created_at, files/diff_path; actions may read run_id/id. | `review-studio/src/App.tsx` plugin/baseline/revision renderers and action handlers. | Pick canonical properties and update displays/tests; do not require UI display aliases from server DTOs. |
| `ReviewApi` declares many methods optional, while production `factory.ts:remoteApi` supplies the complete `ReviewApiClient`; injected mocks use subsets and App branches into degraded capability states. | `review-studio/src/api/models.ts:ReviewApi`; `review-studio/src/api/factory.ts`; `App.tsx`; `review-studio/src/test/app.test.tsx`. | Make core canonical production operations required; migrate mocks/tests to typed full fixtures. Preserve optional methods only for explicitly extensible capabilities, not route availability. |
| Workspace precedence is localStorage selection if still present, else server `active`, else first item. Client puts selected item first; App sets first returned workspace active; manual select calls server selection then persists localStorage. | `client.ts:listWorkspaces/selectWorkspace`; `review-studio/src/App.tsx` startup and switcher; client/app tests. | Product/semantic decision required: local preference vs server-active authority, stale ID behavior, and whether selection is user-local or global server state. Do not accidentally preserve current precedence. |

API fixtures and UI tests contain `/v1` paths, legacy normalization examples, normalized DTOs and partial mocks; all consumers/tests must migrate with the deliberate breaking cutover. This inventory is source-backed but not exhaustive: exact enumeration of every fixture/display fallback and production composition remains a follow-up before contract freeze.

## Evidence reviewed

- `src/docs/api/openapi.py`: OpenAPI version/info, route operation declarations, components, auth declarations, pagination parameters, and response/request schema literals.
- `src/docs/api/application.py`: static registrations, dynamic handlers, workspace lookup/fallback, serialization and endpoint implementation. The file has substantially more behavior than the summary inventory above; implementation must trace handlers and tests.
- `src/docs/api/http.py`: `APIError`, request JSON parsing, error envelope, internal-error masking, router 404, pagination/idempotency/HTTP boundary.
- `src/docs/api/auth.py`: `AuthError` and bearer/scope behavior.
- `src/docs/api/enterprise.py`: error normalization and workspace path policy.
- `tests/unit/api/test_application.py` and API auth/enterprise tests are existing characterization evidence; no tests were run for this record.
- `docs/superpowers/plans/2026-09-21-api-client-desktop.md`, Task 1 and Task 2: requires this decision record and maintainer gate before route modification.

## Unknowns requiring verification before implementation

- Whether installed/remote consumers exist and which endpoint operations they use.
- Full endpoint-to-handler mapping, including dynamic/plugin-installed routes and route collision behavior.
- Exact per-operation success and error payloads/statuses, especially raw import, section/context writes, mutation replay, and SSE event payloads.
- Whether auth defaults differ among CLI-launched API, desktop sidecar, and self-hosted production composition; whether workspace-scoped auth is enabled.
- Complete frontend normalization branch inventory and exact test coverage for each historical response variant.
- Whether the full scope remains below the review plan's authored change threshold; do not use this record as a line forecast.

## Contract rulings

These rulings use the user's explicit authorization to make breaking changes and choose solutions; they are not inferred from legacy behavior.

| Decision | Ruling | Why / cost if wrong |
|---|---|---|
| API prefix | `/v2` only; no `/v1` aliases. | Prevents dual contracts; un-migrated external clients must move to v2. |
| Operation set | Keep implemented operations except server-mutating workspace selection; add live run findings and preview routes to canonical OpenAPI; omit OpenAPI-only baseline creation and item promotion until implemented. | Schema must describe callable runtime behavior; omitting a needed capability requires later explicit addition. |
| Workspace identity | Every workspace-owned request carries explicit workspace identity; v2 has no active-workspace fallback, server-global selection authority, or `active` workspace response field. Selection is a client-local preference, not a server mutation. | Removes cross-user state ambiguity; callers must supply `workspace_id` consistently. |
| Authentication | Bearer-only when auth is enabled. Remote/self-hosted composition must fail closed without a validator; unauthenticated mode is restricted to an explicitly selected local sidecar bound to loopback. Enforce route scopes and ownership; conceal foreign/missing owned resources as 404. | Clients relying on API keys or remote deployments without configured auth are unsupported. |
| Errors | Retain `{"error":{"code","message","details"}}`; specify actual statuses per operation, preserve safe 5xx masking and Bearer challenge behavior. | Existing clients may need updates for newly explicit statuses; envelope remains familiar. |
| Workspace creation | Do not accept caller-selected filesystem roots from remote clients. Server allocates/chooses roots within managed storage; API returns the canonical workspace identity. | Existing clients cannot provision arbitrary paths; prevents remote filesystem exposure. Exact managed-root layout is Task 2 implementation detail. |
| Binary/SSE transports | Keep live raw import, progress SSE, and run preview capabilities; document content type, payload/event and ownership semantics in Task 2. | Requires fuller OpenAPI support; removing them would break used capabilities without evidence. |

Task 1 is complete as a decision baseline, not as proof every response DTO is fully characterized. Before route implementation, Task 2 must reconcile exact operation schemas and status/error cases against handlers and focused tests. No further approval is required for the rulings above; newly discovered semantics that materially contradict them should be surfaced rather than silently widened.
