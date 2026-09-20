$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$reviewStudio = Join-Path $repoRoot 'review-studio'
$desktopSrc = Join-Path $repoRoot 'desktop/src'
$dist = Join-Path $reviewStudio 'dist'

if (-not (Test-Path (Join-Path $reviewStudio 'package.json') -PathType Leaf)) {
    throw "Review Studio package.json was not found at $reviewStudio."
}

Push-Location $reviewStudio
try {
    $env:VITE_DOCS_API_BASE_URL = 'http://127.0.0.1:8765/v1'
    if (Test-Path 'package-lock.json' -PathType Leaf) {
        npm ci
    } else {
        Write-Warning 'review-studio/package-lock.json is absent; using npm install.'
        npm install
    }
    npm run build
} finally {
    Pop-Location
}

if (-not (Test-Path $dist -PathType Container)) {
    throw "Review Studio build output is missing: $dist"
}
if (-not (Test-Path (Join-Path $dist 'index.html') -PathType Leaf)) {
    throw "Review Studio build output does not contain index.html: $dist"
}

if (-not (Test-Path $desktopSrc -PathType Container)) {
    New-Item -ItemType Directory -Path $desktopSrc | Out-Null
}
Get-ChildItem $desktopSrc -Force | Remove-Item -Recurse -Force
Get-ChildItem $dist -Force | Copy-Item -Destination $desktopSrc -Recurse -Force

Write-Output "Copied Review Studio dist to $desktopSrc"
