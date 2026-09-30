# Runs the same checks as .github/workflows/ci.yml (job "test" and "hygiene"), plus the
# image builds when Docker is available. Usage: .\scripts\run_ci_local.ps1 [-Python <path>] [-SkipImages]
param(
    [string]$Python = 'python',
    [switch]$SkipImages
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Invoke-Checked([string]$Label, [scriptblock]$Command) {
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed (exit $LASTEXITCODE)" }
}

try {
    Invoke-Checked 'Python compile' { & $Python -m compileall -q api/app api/worker.py api/railway_entrypoint.py api/migrations }

    Push-Location api
    try {
        # A private basetemp avoids Windows permission clashes on the shared pytest temp directory.
        $baseTemp = Join-Path ([IO.Path]::GetTempPath()) ('pla-pytest-' + [guid]::NewGuid().ToString('N'))
        Invoke-Checked 'API tests' { & $Python -m pytest -q --basetemp $baseTemp }
    }
    finally {
        Pop-Location
    }

    Invoke-Checked 'Browser JavaScript syntax' { node --check web/assets/app.js; if ($LASTEXITCODE -eq 0) { node --check web/config.js } }
    Invoke-Checked 'Repository hygiene' { & $Python scripts/ci/check_repo_hygiene.py }

    if ($SkipImages) {
        Write-Host 'Image builds skipped (-SkipImages). CI will build them.' -ForegroundColor Yellow
    }
    elseif (Get-Command docker -ErrorAction SilentlyContinue) {
        Invoke-Checked 'Railway app image (root Dockerfile)' { docker build -f Dockerfile -t jsan-pla-app:local . }
        Invoke-Checked 'Worker image' { docker build -f worker/Dockerfile -t jsan-pla-worker:local . }
    }
    else {
        Write-Host 'Docker not found: image builds skipped locally. CI will build them.' -ForegroundColor Yellow
    }

    Write-Host 'Local CI checks passed.' -ForegroundColor Green
}
finally {
    Pop-Location
}
