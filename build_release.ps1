param(
  [string]$Python64 = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Get-AppVersion {
  $versionFile = Join-Path $root "app\version.py"
  $match = Select-String -Path $versionFile -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' | Select-Object -First 1
  if (-not $match) {
    throw "Could not read APP_VERSION from $versionFile"
  }
  return $match.Matches[0].Groups[1].Value
}

function Test-PythonBitness {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
  )

  if (-not (Test-Path $PythonPath)) {
    return $null
  }

  try {
    return (& $PythonPath -c "import struct; print(struct.calcsize('P') * 8)" 2>$null).Trim()
  } catch {
    return $null
  }
}

function Resolve-Python64 {
  param(
    [string]$PreferredPython = ""
  )

  $candidates = @()
  if ($PreferredPython) {
    $candidates += $PreferredPython
  }

  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) {
    $pyList = & py -0p 2>$null
    foreach ($line in $pyList) {
      if ($line -match '([A-Z]:\\.*python\.exe)') {
        $candidates += $matches[1]
      }
    }
  }

  $candidates += @(
    "$env:LocalAppData\Python\pythoncore-3.14-64\python.exe",
    "$env:LocalAppData\Programs\Python\Python314\python.exe",
    "$env:LocalAppData\Programs\Python\Python313\python.exe",
    "$env:LocalAppData\Programs\Python\Python312\python.exe",
    "$env:LocalAppData\Programs\Python\Python311\python.exe"
  )

  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if ((Test-PythonBitness -PythonPath $candidate) -eq "64") {
      return $candidate
    }
  }

  throw "No 64-bit Python interpreter was found. Install a 64-bit Python or pass one in with -Python64."
}

$Version = Get-AppVersion
$ReleaseTag = "v$Version"
$BuildName = "JAVNFOCreator-$ReleaseTag"
$Python64 = Resolve-Python64 -PreferredPython $Python64
$SpecPath = Join-Path $root "build\spec"
$IconPath = Join-Path $root "assets\jav_nfo_creator.ico"
$EntryPoint = Join-Path $root "app\main.py"
New-Item -ItemType Directory -Force -Path $SpecPath | Out-Null

& $Python64 -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --noupx `
  --specpath $SpecPath `
  --icon $IconPath `
  --name $BuildName `
  $EntryPoint
