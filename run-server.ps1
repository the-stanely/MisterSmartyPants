$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $pythonExe)) {
  throw "Python venv not found at: $pythonExe. Run install.ps1 first."
}

Push-Location $repoRoot
try {
  & $pythonExe -m uvicorn server:app --host 127.0.0.1 --port 8080
} finally {
  Pop-Location
}
