$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
$orchestrator = Join-Path $repoRoot 'websearchMCP.py'

if (-not (Test-Path $pythonExe)) {
  throw "Python venv not found at: $pythonExe"
}
if (-not (Test-Path $orchestrator)) {
  throw "websearchMCP.py not found at: $orchestrator"
}

Write-Host '==> Running websearchMCP.py...'
Push-Location $repoRoot
try {
  & $pythonExe -u $orchestrator
} finally {
  Pop-Location
}
