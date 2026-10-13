# Build a release Tauri binary that embeds the shared Review Studio build
# directly from review-studio/dist, WITHOUT syncing it into the committed
# desktop/src/ shell. Used by `npm run check:runtime` to prove the real
# desktop runtime; release installers still go through build-windows.ps1.
. (Join-Path $PSScriptRoot 'common.ps1')

Push-Location (Join-Path $root 'review-studio')
try {
    $env:VITE_DOCS_API_BASE_URL = $ApiBaseUrl
    Invoke-Npm @('run', 'build')
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
    Invoke-Npm @('run', 'tauri', '--', 'build', '--no-bundle', '--config', 'src-tauri/tauri.runtime-check.conf.json')
} finally {
    Pop-Location
}
