$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = "C:\Users\admin\miniforge3\envs\pla-qc\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
Set-Location (Join-Path $Root "web")
& $Python -m http.server 5500
