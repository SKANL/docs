$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bundle = Join-Path $root 'src-tauri/target/release/bundle'
$msi = Get-ChildItem (Join-Path $bundle 'msi') -Filter '*.msi' -File | Select-Object -First 1
$nsis = Get-ChildItem (Join-Path $bundle 'nsis') -Filter '*-setup.exe' -File | Select-Object -First 1

if (-not $msi -or -not $nsis) {
    throw 'Installer artifacts were not found in the Tauri bundle directories.'
}
$msi = $msi.FullName
$nsis = $nsis.FullName

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

# Exercise a clean NSIS installation and verify that the bundled one-file
# sidecar really starts without Python or repository-relative resources.
Get-Process docs-desktop,docs-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force
$install = Join-Path $env:TEMP ('docs-install-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $install | Out-Null
Start-Process -FilePath $nsis -ArgumentList @('/S',('/D=' + $install)) -Wait
$app = Join-Path $install 'docs-desktop.exe'
if (!(Test-Path -LiteralPath $app -PathType Leaf)) {
    throw "Clean install is missing the desktop executable: $app"
}
$desktop = Start-Process -FilePath $app -PassThru
$healthy = $false
try {
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 1
            if ($health.protocol -eq 'docs-sidecar/v1' -and $health.ready -eq $true) {
                $healthy = $true
                break
            }
        } catch {}
    }
    if (!$healthy) { throw 'Clean-installed desktop sidecar did not become healthy.' }
    $sidecars = @(Get-Process docs-sidecar -ErrorAction SilentlyContinue)
    if (!$sidecars) { throw 'Clean-installed desktop did not start docs-sidecar.exe.' }
    $installedSidecar = $sidecars | Where-Object { $_.Path -like "$install\*" }
    if (!$installedSidecar) { throw 'Healthy sidecar is not running from the clean installation.' }
} finally {
    Get-Process docs-desktop,docs-sidecar -ErrorAction SilentlyContinue | Stop-Process -Force
}

Write-Output 'installer artifacts and packaged sidecar resource passed'
