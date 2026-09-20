$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$index = Get-Content (Join-Path $desktop 'src/index.html') -Raw
$sync = Get-Content (Join-Path $desktop 'scripts/sync-review-studio.ps1') -Raw
$build = Get-Content (Join-Path $desktop 'scripts/build-windows.ps1') -Raw
$config = Get-Content (Join-Path $desktop 'src-tauri/tauri.conf.json') -Raw | ConvertFrom-Json

if ($index -match 'Desktop shell ready|intentionally minimal placeholder') {
    throw 'desktop/src/index.html still contains the placeholder shell.'
}
if ($index -notmatch 'Review Studio') {
    throw 'desktop/src/index.html does not identify Review Studio.'
}
if ($sync -notmatch 'review-studio' -or $sync -notmatch 'npm ci' -or $sync -notmatch 'dist') {
    throw 'sync-review-studio.ps1 is missing the deterministic build/copy contract.'
}
if ($build -notmatch 'sync-review-studio.ps1' -or $build -notmatch 'npm run build') {
    throw 'build-windows.ps1 does not run the frontend sync before Tauri.'
}
if ($config.build.frontendDist -ne '../src') {
    throw "Unexpected Tauri frontendDist: $($config.build.frontendDist)"
}

Write-Output 'desktop shell checks passed'
