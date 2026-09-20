# X20 API transport

`docs-api` is a standard-library deployment wrapper around the existing
`X20Application` WSGI callable. It does not own business routes or replace
application authentication.

## Configuration and CLI

Create a JSON file containing an importable application factory. The factory
receives the same `TransportConfig` used by the transport and returns an
`X20Application` (or any compatible WSGI callable):

```json
{
  "application_factory": "my_service:build_application",
  "transport": {
    "host": "127.0.0.1",
    "port": 8080,
    "workspace": "/srv/docs-workspace",
    "base_url": "https://api.example.test/docs",
    "max_request_body": 1048576,
    "cors_origins": ["https://studio.example.test"],
    "graceful_shutdown_timeout": 10,
    "allow_public_bind": false
  }
}
```

Run locally/offline or self-hosted with the same app factory:

```bash
docs-api --config api.json
docs-api --config api.json --host 127.0.0.1 --port 0 --once
```

Non-loopback binding is refused unless `allow_public_bind` is true in the
configuration or `--allow-public-bind` is passed explicitly. Put TLS,
authentication policy, and rate limiting at the reverse proxy as appropriate;
the X20 application still enforces its own business-route authentication.

## Endpoints and proxying

`/healthz` is a transport liveness check and `/readyz` reports the configured
readiness callback. They are the only transport-owned paths; all other paths,
including `/v1/*`, go to `X20Application`. If `base_url` includes a path (for
example `/docs`), the endpoints and application are served below that prefix.

The adapter validates `Content-Length` before dispatch, rejects unsupported
chunked transfer encoding, reads exactly the declared bounded body, and
rejects truncated or oversized requests without an unbounded read. It
normalizes unexpected errors, generates or preserves one stable `X-Request-ID`,
emits low-cardinality structured access logs, and de-duplicates response
headers case-insensitively. SSE responses retain their
`text/event-stream` content type and `Cache-Control: no-cache`; finite WSGI
iterables use `Content-Length`, while streaming iterables use HTTP chunked
framing and are closed when exhausted, aborted, or disconnected. Graceful
shutdown waits for active requests up to `graceful_shutdown_timeout` and is
safe to call more than once. A reverse proxy should forward `Host`,
`X-Forwarded-Proto`, `X-Request-ID`, and the request body, and must not buffer
SSE responses (for example, disable proxy buffering and use a long read
timeout for `/v1/runs/*/progress`).
