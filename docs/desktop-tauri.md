# Tauri desktop shell

The desktop project is a Windows-first Tauri 2 shell around Review Studio.
The frontend is built by `review-studio` and copied into `desktop/src/`; the
shell does not maintain a second frontend implementation.

## Sidecar contract

The Tauri bundle declares `../sidecar/*` as resources (the path is relative to
`desktop/src-tauri/tauri.conf.json`). At runtime the Rust
supervisor resolves a configured `DOCS_SIDECAR_EXECUTABLE` first, then checks
the packaged resource directory in this order:

```text
<resource-dir>/sidecar/docs-sidecar.exe
<resource-dir>/sidecar/sidecar.exe
<resource-dir>/docs-sidecar.exe
<resource-dir>/sidecar.exe
```

The sidecar must answer `GET http://127.0.0.1:8765/health` with HTTP 200 JSON
containing `{"ready":true,"protocol":"docs-sidecar/v1"}`. The health URL may
be overridden with `DOCS_SIDECAR_HEALTH_URL`. The desktop commands expose only
the in-process handshake and health state; no remote IPC or broad shell
permission is enabled.

## Verification and build

Linux CI does not build a Windows installer. It runs the portable contract
check instead:

```bash
python desktop/scripts/check-sidecar-packaging.py
```

That check validates the Tauri resource declaration, Rust resource lookup,
health path, and handshake protocol. It does not require a Windows binary.

On Windows, stage a sidecar and build the installer with:

```powershell
$env:DOCS_SIDECAR_EXECUTABLE = 'C:\path\to\docs-sidecar.exe'
npm run build:windows
```

`build-windows.ps1` synchronizes the frontend, stages the executable under
`desktop/sidecar/`, reruns the sidecar contract check, and only then invokes
`tauri build`. A missing staged executable fails closed before MSI/NSIS
packaging.
