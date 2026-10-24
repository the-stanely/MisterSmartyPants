$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Python venv missing. Run install.ps1 first.'
}
Push-Location $repoRoot
try {
    # dotenv is loaded by MSP; the port must agree with the recursion check.
    & $pythonExe -c "from dotenv import load_dotenv; load_dotenv(override=True); import os, uvicorn; uvicorn.run('studio_bridge:app', host='127.0.0.1', port=int(os.getenv('MSP_BRIDGE_PORT', '8081')), workers=1, proxy_headers=False)"
} finally {
    Pop-Location
}
