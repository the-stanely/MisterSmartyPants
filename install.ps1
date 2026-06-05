$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$requirements = Join-Path $repoRoot 'requirements.txt'

function Get-WorkingPython {
  $candidates = @()

  if ($env:PYTHON) {
    $candidates += $env:PYTHON
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    $candidates += $pythonCmd.Source
  }

  $commonUserPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
  if (Test-Path $commonUserPython) {
    $candidates += $commonUserPython
  }

  foreach ($candidate in $candidates | Select-Object -Unique) {
    try {
      $version = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
      if ([version]$version -ge [version]'3.10') {
        return $candidate
      }
    } catch {
      continue
    }
  }

  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    try {
      $version = & $pyLauncher.Source -3.11 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
      if ([version]$version -ge [version]'3.10') {
        return @($pyLauncher.Source, '-3.11')
      }
    } catch {
      return $null
    }
  }

  return $null
}

function Invoke-Python {
  param(
    [Parameter(Mandatory = $true)] $PythonCommand,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]] $PythonArgs
  )

  if ($PythonCommand -is [array]) {
    & $PythonCommand[0] $PythonCommand[1] @PythonArgs
  } else {
    & $PythonCommand @PythonArgs
  }
}

if (-not (Test-Path $requirements)) {
  throw "requirements.txt not found at: $requirements"
}

Write-Host '==> Checking for Python 3.10+...'
$python = Get-WorkingPython

if (-not $python) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "Python 3.10+ was not found and winget is unavailable. Install Python 3.11 from https://www.python.org/downloads/windows/ and rerun this script."
  }

  Write-Host '==> Python not found. Installing Python 3.11 with winget...'
  & $winget.Source install --id Python.Python.3.11 --exact --scope user --accept-package-agreements --accept-source-agreements
  $python = Get-WorkingPython

  if (-not $python) {
    throw 'Python install completed, but python was not found in this PowerShell session. Open a new PowerShell window and rerun install.ps1.'
  }
}

  Write-Host '==> Creating virtual environment...'
  Push-Location $repoRoot
try {
  if (-not (Test-Path $venvPython)) {
    Invoke-Python -PythonCommand $python -PythonArgs @('-m', 'venv', '.venv')
  }

  Write-Host '==> Upgrading pip...'
  & $venvPython -m pip install --upgrade pip

  Write-Host '==> Installing Python dependencies...'
  & $venvPython -m pip install -r $requirements

  Write-Host ''
  Write-Host 'Install complete.'
  Write-Host 'Run the app with:'
  Write-Host '  powershell -ExecutionPolicy Bypass -File .\run.ps1'
} finally {
  Pop-Location
}
