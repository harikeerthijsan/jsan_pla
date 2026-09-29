param(
  [string]$Source = "C:\PLA_QC\potree",
  [string]$WebRoot = "$(Split-Path $PSScriptRoot -Parent)\web"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path "$Source\build\potree\potree.js")) { throw "Potree build not found at $Source. Run npm install in your working Potree folder first." }
$dest = Join-Path $WebRoot "potree"
New-Item -ItemType Directory -Force $dest | Out-Null
foreach($dir in @("build","libs","resources")) {
  Write-Host "Copying $dir ..."
  Copy-Item "$Source\$dir" "$dest\$dir" -Recurse -Force
}
Write-Host "Potree runtime copied into $dest" -ForegroundColor Green
