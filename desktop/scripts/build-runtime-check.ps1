# Build a release Tauri binary that embeds the shared Review Studio build
# directly from review-studio/dist, WITHOUT syncing it into the committed
# desktop/src/ shell. Used by `npm run check:runtime` to prove the real
# desktop runtime; release installers still go through build-windows.ps1.
$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$reviewStudio = Join-Path (Split-Path -Parent $desktop) 'review-studio'

Push-Location $reviewStudio
try {
    $env:VITE_DOCS_API_BASE_URL = 'http://127.0.0.1:8765/v1'
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Review Studio build failed (exit code $LASTEXITCODE)." }
} finally {
    Pop-Location
}

if (-not (Test-Path (Join-Path $desktop 'sidecar/docs-sidecar.exe') -PathType Leaf)) {
    powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-sidecar.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Sidecar build failed (exit code $LASTEXITCODE)." }
}

Push-Location $desktop
try {
    # A relative frontendDist is required: an absolute `C:/...` value is parsed
    # as a URL and the webview loads file:// instead of the embedded assets.
    npx tauri build --no-bundle --config src-tauri/tauri.runtime-check.conf.json
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed (exit code $LASTEXITCODE)." }
} finally {
    Pop-Location
}
