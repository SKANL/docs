$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $sidecar = Join-Path $root 'sidecar/docs-sidecar.exe'
    if (-not (Test-Path $sidecar -PathType Leaf)) {
        npm run build:sidecar
    }
    $env:DOCS_SIDECAR_EXECUTABLE = (Resolve-Path $sidecar).Path
    $env:VITE_DOCS_API_BASE_URL = 'http://127.0.0.1:8765/v1'
    npm run tauri dev
} finally {
    Remove-Item Env:DOCS_SIDECAR_EXECUTABLE -ErrorAction SilentlyContinue
    Remove-Item Env:VITE_DOCS_API_BASE_URL -ErrorAction SilentlyContinue
    Pop-Location
}
