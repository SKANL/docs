# Shared helpers for the desktop scripts. Dot-source it:
#   . (Join-Path $PSScriptRoot 'common.ps1')
$ErrorActionPreference = 'Stop'

$desktop = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $desktop
# The single API base every script points the Review Studio client at.
$ApiBaseUrl = 'http://127.0.0.1:8765/v2'

# A prior smoke test or desktop session may still hold a PyInstaller DLL.
# Stop only the named Doc Harness processes before replacing or reinstalling.
function Stop-Sidecar {
    param([string[]]$Name = @('docs-sidecar'))
    Get-Process -Name $Name -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 250
}

# Run npm with an argument array (so a literal `--` survives) and throw on a non-zero exit code.
function Invoke-Npm {
    param([Parameter(Mandatory)][string[]]$Arguments)
    & npm @Arguments
    if ($LASTEXITCODE -ne 0) { throw "npm $($Arguments -join ' ') failed (exit code $LASTEXITCODE)." }
}
