# Deployment

The production topology is deliberately small:

```text
reverse proxy (TLS, auth, rate limits)
        ├── docs-api  ── run/passport/artifact/graph reads
        └── docs-worker ── queued document work
                 └── shared workspace + durable stores
```

## API process

`docs-api` wraps an application factory and exposes `/healthz`, `/readyz`, and
the authenticated `/v1/*` API. Keep the process on loopback unless the
deployment explicitly needs a public bind:

```bash
docs-api --config api.json --host 127.0.0.1 --port 8000
```

Use `--allow-public-bind` only with a reviewed network policy. TLS termination,
authentication, rate limiting, and request-size policy belong at the reverse
proxy as well as in the application. Forward `Host`, `X-Forwarded-Proto`,
`X-Request-ID`, and the request body. Do not buffer
`/v1/runs/{run_id}/progress`; use a long read timeout for SSE.

The API owns transport liveness (`/healthz`) and readiness (`/readyz`). The
application owns business routes and authentication scopes. The main run flow
is:

```text
POST /v1/runs
GET  /v1/runs/{run_id}
GET  /v1/runs/{run_id}/progress
GET  /v1/runs/{run_id}/passport
GET  /v1/runs/{run_id}/artifacts
GET  /v1/runs/{run_id}/graph
```

Authenticated production principals must carry tenant and organization
identity. Run, document, finding, passport, artifact, and graph access is
filtered or denied at the application boundary; do not rely on the proxy for
tenant isolation.

## Worker process and persistence

Run `docs-worker` with the same workspace and configuration as the API. SQLite
stores are suitable for a single-host deployment. Use the Redis queue and the
blob backend when API and workers are split across hosts. The worker lease and
cancellation stores must be durable and shared by all worker instances.

Back up the workspace's source inputs, `runs/`, passport storage, and durable
queue state together. Rendered artifacts are replaceable; provenance and
passport records are not. Publish only artifacts that have a matching v2
manifest and verifiable attestation (`docs/provenance.md`).

## Release checks

Before release, run the strict path and inspect the evidence:

```bash
uv run docs document build --format docx --format html --policy release --json
uv run docs document verify --format docx --format html --policy release --json
uv run docs document publish output/current/report.docx output/published/report.docx --policy release --json
uv run docs doctor --strict
```

Missing optional tools may be visible degradations in draft mode, but strict
and release policies must not publish an unsupported required stage.
