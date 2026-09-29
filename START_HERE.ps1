$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "JSAN PLA QC Workbench v3 - Profile" -ForegroundColor Cyan
Write-Host "Root: $Root"
& (Join-Path $Root "scripts\setup_local.ps1")
& (Join-Path $Root "scripts\start_local_dynamic.ps1")
