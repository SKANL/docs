$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$sidecarDir = Join-Path $desktop 'sidecar'
$configuredSidecar = $env:DOCS_SIDECAR_EXECUTABLE
$tauriConfigOverride = $null

# Tauri expects the signing key contents, not only a path. Accept the path
# form for local/CI ergonomics while keeping the private key outside Git.
if (-not $env:TAURI_SIGNING_PRIVATE_KEY -and $env:TAURI_SIGNING_PRIVATE_KEY_PATH) {
    if (-not (Test-Path $env:TAURI_SIGNING_PRIVATE_KEY_PATH -PathType Leaf)) {
        throw "TAURI_SIGNING_PRIVATE_KEY_PATH does not point to a file: $env:TAURI_SIGNING_PRIVATE_KEY_PATH"
    }
    $env:TAURI_SIGNING_PRIVATE_KEY = Get-Content $env:TAURI_SIGNING_PRIVATE_KEY_PATH -Raw
}

Push-Location $desktop
try {
    npm run sync:review-studio

    if ($configuredSidecar) {
        if (-not (Test-Path $configuredSidecar -PathType Leaf)) {
            throw "DOCS_SIDECAR_EXECUTABLE does not point to a file: $configuredSidecar"
        }
        New-Item -ItemType Directory -Path $sidecarDir -Force | Out-Null
        Copy-Item -LiteralPath $configuredSidecar -Destination (Join-Path $sidecarDir 'docs-sidecar.exe') -Force
    } else {
        powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-sidecar.ps1')
    }

    npm run check:sidecar
    $packaged = @(
        (Join-Path $sidecarDir 'docs-sidecar.exe'),
        (Join-Path $sidecarDir 'sidecar.exe')
    ) | Where-Object { Test-Path $_ -PathType Leaf }
    if (-not $packaged) {
        throw 'No Windows sidecar was staged. Build-sidecar.ps1 must produce sidecar/docs-sidecar.exe.'
    }
    python scripts/check-sidecar-runtime.py
    if ($LASTEXITCODE -ne 0) { throw "Packaged sidecar runtime check failed (exit code $LASTEXITCODE)." }
    python scripts/check-sidecar-e2e.py
    if ($LASTEXITCODE -ne 0) { throw "Packaged sidecar end-to-end check failed (exit code $LASTEXITCODE)." }

    if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
        # Local installer builds must remain usable without release credentials.
        # Release/CI builds still require the private key and produce updater artifacts.
        $tauriConfigOverride = Join-Path $desktop 'src-tauri\build-local.json'
        Set-Content -LiteralPath $tauriConfigOverride -Value '{"bundle":{"createUpdaterArtifacts":false}}' -Encoding utf8
        npm run tauri -- build --config src-tauri/build-local.json
    } else {
        npm run tauri build
    }
} finally {
    if ($tauriConfigOverride -and (Test-Path $tauriConfigOverride -PathType Leaf)) {
        Remove-Item -LiteralPath $tauriConfigOverride -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
