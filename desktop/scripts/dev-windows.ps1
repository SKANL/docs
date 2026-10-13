. (Join-Path $PSScriptRoot 'common.ps1')
Push-Location $desktop
try {
    $sidecar = Join-Path $desktop 'sidecar/docs-sidecar.exe'
    if (-not (Test-Path $sidecar -PathType Leaf)) {
        Invoke-Npm @('run', 'build:sidecar')
    }
    $env:DOCS_SIDECAR_EXECUTABLE = (Resolve-Path $sidecar).Path
    $env:VITE_DOCS_API_BASE_URL = $ApiBaseUrl
    npm run tauri dev
} finally {
    Remove-Item Env:DOCS_SIDECAR_EXECUTABLE -ErrorAction SilentlyContinue
    Remove-Item Env:VITE_DOCS_API_BASE_URL -ErrorAction SilentlyContinue
    Pop-Location
}
