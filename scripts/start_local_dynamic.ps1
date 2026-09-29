$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Starting API, worker and web in separate PowerShell windows..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run_api_local.ps1')
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run_worker_local.ps1')
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run_web_local.ps1')
Start-Sleep -Seconds 2
Start-Process 'http://localhost:5500'
Write-Host "Workbench opening at http://localhost:5500" -ForegroundColor Green
