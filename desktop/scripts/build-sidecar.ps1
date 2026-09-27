$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $desktop
$sidecarDir = Join-Path $desktop 'sidecar'
$distDir = Join-Path $sidecarDir 'pyinstaller-dist'

# A prior smoke test or desktop session may still hold a PyInstaller DLL.
# Stop only the named Doc Harness sidecar before replacing the staged bundle.
Get-Process -Name 'docs-sidecar' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 250

Push-Location $root
try {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
    # The sidecar is supervised by Tauri and must never create a visible
    # console window for desktop users. Keep stdout/stderr available to the
    # supervisor when launched from a terminal, but use a windowless Windows
    # subsystem in packaged builds.
    # One-file packaging avoids relying on relative DLL/data paths after the
    # NSIS installer stages resources under `_up_`.
    uv run pyinstaller --noconfirm --clean --onefile --noconsole --name docs-sidecar `
        --paths src --distpath $distDir --workpath (Join-Path $sidecarDir 'pyinstaller-build') `
        --hidden-import docs.infrastructure.provenance.ledger `
        --hidden-import docs.infrastructure.transform.system_transform `
        --hidden-import docs.templates.builtin `
        --collect-data docs.templates.builtin `
        --collect-submodules docs.infrastructure.transform `
        tools/docs_sidecar.py
    Get-ChildItem $sidecarDir -Force | Where-Object { $_.Name -notin @('.gitkeep', 'pyinstaller-build', 'pyinstaller-dist') } | Remove-Item -Recurse -Force
    Copy-Item (Join-Path $distDir 'docs-sidecar.exe') -Destination $sidecarDir -Force
    $sidecarExecutable = Join-Path $sidecarDir 'docs-sidecar.exe'
    if (-not (Test-Path $sidecarExecutable -PathType Leaf)) { throw 'PyInstaller did not produce docs-sidecar.exe.' }
    # Import-time smoke test: a successful PyInstaller build is not enough;
    # lazy imports must also resolve in the frozen runtime.
    & $sidecarExecutable --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Frozen sidecar failed its --help smoke test (exit code $LASTEXITCODE)." }
} finally {
    Pop-Location
}
