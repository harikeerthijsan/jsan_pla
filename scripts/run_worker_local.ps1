$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "api"

if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "sqlite:///./pla_qc.db" }
if (-not $env:STORAGE_MODE) { $env:STORAGE_MODE = "local" }
if (-not $env:LOCAL_STORAGE_ROOT) { $env:LOCAL_STORAGE_ROOT = (Join-Path $Api "storage") }
if (-not $env:PDAL_BIN) {
  $candidate = "C:\Users\admin\miniforge3\envs\pla-qc\Library\bin\pdal.exe"
  if (Test-Path $candidate) { $env:PDAL_BIN = $candidate } else { $env:PDAL_BIN = "pdal" }
}

$Python = "C:\Users\admin\miniforge3\envs\pla-qc\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
Set-Location $Api
& $Python worker.py
