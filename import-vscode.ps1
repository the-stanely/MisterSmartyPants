$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backupDir = Join-Path $repoRoot 'vscode-backup'
$code = Get-Command code -ErrorAction SilentlyContinue

if (-not $code) {
  throw 'VS Code command-line tool "code" was not found. Install VS Code and make sure "code" is available in PATH, then rerun this script.'
}

if (-not (Test-Path $backupDir)) {
  throw "VS Code backup folder not found at: $backupDir"
}

$extensionsFile = Join-Path $backupDir 'extensions.txt'
if (Test-Path $extensionsFile) {
  Write-Host '==> Installing VS Code extensions...'
  Get-Content -Path $extensionsFile | Where-Object { $_.Trim() } | ForEach-Object {
    & $code.Source --install-extension $_
  }
}

$userDir = Join-Path $env:APPDATA 'Code\User'
New-Item -ItemType Directory -Path $userDir -Force | Out-Null

$files = @(
  'settings.json',
  'keybindings.json'
)

foreach ($file in $files) {
  $source = Join-Path $backupDir $file
  if (Test-Path $source) {
    Copy-Item -LiteralPath $source -Destination (Join-Path $userDir $file) -Force
  }
}

$sourceSnippets = Join-Path $backupDir 'snippets'
if (Test-Path $sourceSnippets) {
  Copy-Item -LiteralPath $sourceSnippets -Destination (Join-Path $userDir 'snippets') -Recurse -Force
}

Write-Host ''
Write-Host 'VS Code settings restored.'
