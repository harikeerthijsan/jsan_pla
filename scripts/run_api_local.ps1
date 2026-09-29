$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root "api"
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "sqlite:///./pla_qc.db" }
if (-not $env:STORAGE_MODE) { $env:STORAGE_MODE = "local" }
if (-not $env:LOCAL_STORAGE_ROOT) { $env:LOCAL_STORAGE_ROOT = (Join-Path $Api "storage") }
if (-not $env:CORS_ORIGINS) { $env:CORS_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500" }
if (-not $env:JWT_SECRET) { $env:JWT_SECRET = "local-development-change-me" }
if (-not $env:ADMIN_EMAIL) { $env:ADMIN_EMAIL = "admin@jsan.local" }
if (-not $env:ADMIN_PASSWORD) { $env:ADMIN_PASSWORD = "ChangeMe123!" }
$Python = "C:\Users\admin\miniforge3\envs\pla-qc\python.exe"
if (-not (Test-Path $Python)) { $Python = (Get-Command python -ErrorAction Stop).Source }
Set-Location $Api
& $Python -m uvicorn app.main:app --reload --port 8000
