$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bundle = Join-Path $root 'src-tauri/target/release/bundle'
$msi = Join-Path $bundle 'msi/Review Studio_0.1.0_x64_en-US.msi'
$nsis = Join-Path $bundle 'nsis/Review Studio_0.1.0_x64-setup.exe'

foreach ($path in @($msi, $nsis)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Installer artifact is missing: $path"
    }
    if ((Get-Item -LiteralPath $path).Length -lt 100KB) {
        throw "Installer artifact is unexpectedly small: $path"
    }
}

# Inspect the NSIS archive when 7-Zip is available. The installer is a
# self-extracting archive, so searching raw compressed bytes is unreliable.
$sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
if ($sevenZip) {
    $listing = & $sevenZip.Source l $nsis 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $listing -notmatch 'docs-sidecar\.exe') {
        throw 'NSIS installer does not contain the packaged sidecar resource.'
    }
} else {
    Write-Warning '7z is unavailable; skipped inspection of compressed NSIS contents.'
}

Write-Output 'installer artifacts and packaged sidecar resource passed'
