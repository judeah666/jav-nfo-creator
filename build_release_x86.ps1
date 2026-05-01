param(
  [string]$Python32 = ""
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

function Resolve-Python32 {
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
    "$env:LocalAppData\Programs\Python\Python313-32\python.exe",
    "$env:LocalAppData\Programs\Python\Python312-32\python.exe",
    "$env:LocalAppData\Programs\Python\Python311-32\python.exe"
  )

  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if ((Test-PythonBitness -PythonPath $candidate) -eq "32") {
      return $candidate
    }
  }

  throw "No 32-bit Python interpreter was found. Install a 32-bit Python or pass one in with -Python32."
}

$Version = Get-AppVersion
$ReleaseTag = "v$Version"
$BuildName = "JAVNFOCreator-$ReleaseTag-32bit"

$Python32 = Resolve-Python32 -PreferredPython $Python32
$SpecPath = Join-Path $root "build\spec"
$IconPath = Join-Path $root "assets\jav_nfo_creator.ico"
$EntryPoint = Join-Path $root "app\main.py"
New-Item -ItemType Directory -Force -Path $SpecPath | Out-Null

& $Python32 -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --noupx `
  --specpath $SpecPath `
  --icon $IconPath `
  --name $BuildName `
  $EntryPoint
