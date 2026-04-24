param(
  [string]$Python64 = $env:JAV_NFO_CREATOR_PYTHON
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not $Python64) {
  $resolvedPython = Get-Command python -ErrorAction SilentlyContinue
  if ($resolvedPython) {
    $Python64 = $resolvedPython.Source
  }
}

if (-not $Python64) {
  throw @"
No 64-bit Python was provided.

Set the JAV_NFO_CREATOR_PYTHON environment variable or pass -Python64 with the
full path to a 64-bit python.exe.
"@
}

if (-not (Test-Path -LiteralPath $Python64)) {
  throw "64-bit Python not found: $Python64"
}

$pythonBits = & $Python64 -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0) {
  throw "Failed to query Python architecture from: $Python64"
}

if (($pythonBits | Out-String).Trim() -ne "64") {
  throw "The supplied Python is not 64-bit: $Python64"
}

& $Python64 -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --icon assets\jav_nfo_creator.ico `
  --name JAVNFOCreator `
  app\main.py

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed."
}

Write-Host ""
Write-Host "Release build ready:"
Write-Host "$root\dist\JAVNFOCreator\JAVNFOCreator.exe"
