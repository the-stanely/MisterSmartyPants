$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupDir = Join-Path $repoRoot 'vscode-backup'
$code = Get-Command code -ErrorAction SilentlyContinue

if (-not $code) {
  throw 'VS Code command-line tool "code" was not found. In VS Code, run "Shell Command: Install code command in PATH", then rerun this script.'
}

$userDir = Join-Path $env:APPDATA 'Code\User'
if (-not (Test-Path $userDir)) {
  throw "VS Code user settings folder not found at: $userDir"
}

New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

Write-Host '==> Exporting VS Code extensions...'
& $code.Source --list-extensions | Sort-Object | Set-Content -Path (Join-Path $backupDir 'extensions.txt') -Encoding UTF8

$files = @(
  'settings.json',
  'keybindings.json'
)

foreach ($file in $files) {
  $source = Join-Path $userDir $file
  if (Test-Path $source) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $backupDir $file) -Force
  }
}

$snippets = Join-Path $userDir 'snippets'
if (Test-Path $snippets) {
  Copy-Item -LiteralPath $snippets -Destination (Join-Path $backupDir 'snippets') -Recurse -Force
}

Write-Host ''
Write-Host "VS Code backup written to: $backupDir"
