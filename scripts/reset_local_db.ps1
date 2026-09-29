$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "api"
$db = Join-Path $Api "pla_qc.db"
$storage = Join-Path $Api "storage"
if (Test-Path $db) { Remove-Item $db -Force; Write-Host "Removed $db" -ForegroundColor Yellow }
if (Test-Path $storage) { Remove-Item $storage -Recurse -Force; Write-Host "Removed local storage" -ForegroundColor Yellow }
Write-Host "Local development state reset. Uploaded source files and processed COPCs in this v3 package were removed." -ForegroundColor Green
