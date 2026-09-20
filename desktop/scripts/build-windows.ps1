$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$sidecarDir = Join-Path $desktop 'sidecar'
$configuredSidecar = $env:DOCS_SIDECAR_EXECUTABLE

Push-Location $desktop
try {
    npm run sync:review-studio

    if ($configuredSidecar) {
        if (-not (Test-Path $configuredSidecar -PathType Leaf)) {
            throw "DOCS_SIDECAR_EXECUTABLE does not point to a file: $configuredSidecar"
        }
        New-Item -ItemType Directory -Path $sidecarDir -Force | Out-Null
        Copy-Item -LiteralPath $configuredSidecar -Destination (Join-Path $sidecarDir 'docs-sidecar.exe') -Force
    }

    npm run check:sidecar
    $packaged = @(
        (Join-Path $sidecarDir 'docs-sidecar.exe'),
        (Join-Path $sidecarDir 'sidecar.exe')
    ) | Where-Object { Test-Path $_ -PathType Leaf }
    if (-not $packaged) {
        throw 'No Windows sidecar was staged. Set DOCS_SIDECAR_EXECUTABLE or place sidecar/docs-sidecar.exe before building.'
    }

    npm run tauri build
} finally {
    Pop-Location
}
