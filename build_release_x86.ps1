param(
  [string]$Python32 = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$Version = "1.0.0"
$ReleaseTag = "v$Version"
$BuildName = "JAVNFOCreator-$ReleaseTag-32bit"

if (-not $Python32) {
  $Python32 = "C:\Users\jestre\AppData\Local\Programs\Python\Python313-32\python.exe"
}

if (-not (Test-Path $Python32)) {
  throw "32-bit Python not found at: $Python32"
}

& $Python32 -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --icon assets\jav_nfo_creator.ico `
  --name $BuildName `
  app\main.py
