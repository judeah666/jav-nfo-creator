$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$Version = "1.0.0"
$ReleaseTag = "v$Version"
$BuildName = "JAVNFOCreator-$ReleaseTag"

python -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --icon assets\jav_nfo_creator.ico `
  --name $BuildName `
  app\main.py
