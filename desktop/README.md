# Review Studio Desktop

Windows-first Tauri 2 shell. The Rust supervisor owns the local sidecar lifecycle and exposes only an in-process handshake/health abstraction; no remote IPC or broad shell permissions are enabled.

## Frontend packaging

The desktop project is a packaging shell; it does not duplicate Review Studio
source. `scripts/sync-review-studio.ps1` runs the existing
`review-studio` build, requires `dist/index.html`, and copies the resulting
`dist/` contents into `desktop/src/`. A committed minimal entry file remains
only as a safe pre-build shell and is replaced by the built UI.

The Windows build is deterministic when `review-studio/package-lock.json` is
present: it uses `npm ci` before `npm run build`. It fails closed when the
frontend build or its `dist/index.html` output is missing.

## Development

From this directory, install Node dependencies and run `npm run dev`. For a Windows release, run `scripts/build-windows.ps1` from PowerShell. Rust formatting/checking can be run with `cargo fmt --check` and `cargo check` in `src-tauri`.

Run `npm run sync:review-studio` to refresh the local frontend bundle, or run
`scripts/build-windows.ps1` to sync the frontend and produce the Tauri MSI/NSIS
artifacts. `npm run test:shell` checks that the placeholder is absent and that
the packaging configuration is wired to the Review Studio build.

## Sidecar placement and health handshake

The Rust supervisor behavior is unchanged. In an installed Windows bundle it
looks for `docs-sidecar.exe` (or `sidecar.exe`) under the Tauri resource
directory, first in `sidecar/` and then at the resource root. A development
override may set `DOCS_SIDECAR_EXECUTABLE` to an executable file.

The supervisor probes `http://127.0.0.1:8765/health` by default (override with
`DOCS_SIDECAR_HEALTH_URL`). The endpoint must return HTTP 200 JSON with
`{"ready":true,"protocol":"docs-sidecar/v1"}`. The desktop commands expose
the in-process handshake/health state only; no remote IPC or broad shell
permissions are enabled.
