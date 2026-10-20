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

## Real desktop runtime check

`npm run build:runtime-check` builds `review-studio/dist` (API base
`http://127.0.0.1:8765/v2`), the frozen sidecar if it is missing, and a release
Tauri binary that embeds `review-studio/dist` directly through
`src-tauri/tauri.runtime-check.conf.json`. It never writes `desktop/src/`.

`npm run check:runtime` then launches that binary on a fresh install, attaches
to its WebView2 over CDP (`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS`), waits for the
supervised sidecar to become healthy, and drives the shared workspace/document
journey: create a document, cancel a deletion, confirm it. It refuses to run if
`%APPDATA%/com.docs.reviewstudio` already exists, so it cannot touch a real
user's data; set `DESKTOP_RUNTIME_ALLOW_EXISTING_APPDATA=1` to override on a
disposable machine. Pass `--fresh` (`npm run check:runtime -- --fresh`) to
re-run: it deletes that directory only if it holds the `.runtime-check-owned`
marker the script wrote when it created it; foreign data is never deleted.

`npm run check:runtime:failure` runs the same binary with `DOCS_SIDECAR_EXECUTABLE` pointing at an
executable that exits immediately, and checks the failure screen: it appears, View log shows the
service log, and Retry against a still-broken service keeps the screen. Same fresh-install rules.

## Real installer and PDF journeys

`npm run build:windows` produces the MSI and NSIS installers. Without
`TAURI_SIGNING_PRIVATE_KEY` (or `TAURI_SIGNING_PRIVATE_KEY_PATH`), it creates
an unsigned local installer without updater artifacts; release builds must
provide the private key for signed updates.

For the packaged real-document journey, set `DOCS_REAL_PDF_FIXTURES` to a
semicolon-separated list of PDF paths and run
`python scripts/check-real-pdf-e2e.py`. Increase
`DOCS_REAL_PDF_TIMEOUT_SECONDS` for large documents.

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

## Startup and failure screens

Inside the desktop shell the UI (`review-studio/src/app/shell/SidecarGate.tsx`)
polls `sidecar_health` and shows a startup screen while the sidecar boots. If
the shell reports `failed` on two consecutive polls it shows a failure screen
with **Retry** (`sidecar_restart`) and **View log** (`sidecar_log`, the last
16 KiB of `sidecar.log` in the app data directory). In a browser the gate is
transparent.
