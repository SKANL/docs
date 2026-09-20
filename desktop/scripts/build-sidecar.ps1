$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $desktop
$sidecarDir = Join-Path $desktop 'sidecar'
$distDir = Join-Path $sidecarDir 'pyinstaller-dist'

Push-Location $root
try {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    uv run pyinstaller --noconfirm --clean --onedir --name docs-sidecar `
        --paths src --distpath $distDir --workpath (Join-Path $sidecarDir 'pyinstaller-build') `
        tools/docs_sidecar.py
    Get-ChildItem $sidecarDir -Force | Where-Object { $_.Name -notin @('.gitkeep', 'pyinstaller-build', 'pyinstaller-dist') } | Remove-Item -Recurse -Force
    Get-ChildItem (Join-Path $distDir 'docs-sidecar') -Force | Copy-Item -Destination $sidecarDir -Recurse -Force
    $sidecarExecutable = Join-Path $sidecarDir 'docs-sidecar.exe'
    if (-not (Test-Path $sidecarExecutable -PathType Leaf)) { throw 'PyInstaller did not produce docs-sidecar.exe.' }
} finally {
    Pop-Location
}
