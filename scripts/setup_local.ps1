$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\admin\miniforge3\envs\pla-qc\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
Write-Host "Using Python: $Python" -ForegroundColor Cyan
& $Python -m pip install -r (Join-Path $Root "api\requirements.txt")
& (Join-Path $PSScriptRoot "copy_potree_from_existing.ps1")
Write-Host "Local setup complete." -ForegroundColor Green

$Pdal = "C:\Users\admin\miniforge3\envs\pla-qc\Library\bin\pdal.exe"
if (-not (Test-Path $Pdal)) { $Pdal = (Get-Command pdal -ErrorAction SilentlyContinue).Source }
if ($Pdal) {
  Write-Host "Checking PDAL profile dependencies..." -ForegroundColor Cyan
  $drivers = & $Pdal --drivers | Out-String
  foreach($driver in @("readers.copc","writers.copc","writers.text")) {
    if ($drivers -notmatch [regex]::Escape($driver)) { throw "Required PDAL driver missing: $driver" }
  }
  Write-Host "PDAL COPC + text drivers OK." -ForegroundColor Green
} else {
  Write-Warning "PDAL was not found. Dataset conversion/profile jobs will fail until PDAL is available."
}
