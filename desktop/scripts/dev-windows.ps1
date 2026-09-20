$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $sidecar = Join-Path $root 'sidecar/docs-sidecar.exe'
    if (-not (Test-Path $sidecar -PathType Leaf)) {
        npm run build:sidecar
    }
    $env:DOCS_SIDECAR_EXECUTABLE = (Resolve-Path $sidecar).Path
    npm run tauri dev
} finally {
    Remove-Item Env:DOCS_SIDECAR_EXECUTABLE -ErrorAction SilentlyContinue
    Pop-Location
}
