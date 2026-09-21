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
