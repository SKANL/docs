$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
  & (Join-Path $PSScriptRoot 'sync-review-studio.ps1')
  if (Test-Path 'package-lock.json' -PathType Leaf) { npm ci } else { npm install --no-package-lock }
  npm run build
} finally { Pop-Location }
