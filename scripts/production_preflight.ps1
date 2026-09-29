# Checks the SHAPE of a staging/production variable set before it is applied in Railway.
# It reads values from the current process environment (e.g. a shell populated from a password
# manager) and never prints them. It does not validate remote connectivity.
# Usage: .\scripts\production_preflight.ps1 -Environment production
param(
    [Parameter(Mandatory = $true)][ValidateSet('staging', 'production')][string]$Environment
)
$ErrorActionPreference = 'Stop'

function Get-First([string[]]$Names) {
    foreach ($n in $Names) {
        $v = [Environment]::GetEnvironmentVariable($n)
        if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }
    }
    return $null
}

$problems = @()
foreach ($k in 'APP_ENV', 'DATABASE_URL', 'JWT_SECRET', 'ADMIN_EMAIL', 'ADMIN_PASSWORD', 'STORAGE_MODE') {
    if (-not (Get-First @($k))) { $problems += "$k is missing" }
}
# Aliases match api/railway_entrypoint.py and api/app/storage.py.
$bucketGroups = [ordered]@{
    'bucket name'       = @('BUCKET', 'BUCKET_NAME', 'S3_BUCKET', 'AWS_S3_BUCKET_NAME')
    'bucket endpoint'   = @('BUCKET_ENDPOINT', 'S3_ENDPOINT_URL', 'AWS_ENDPOINT_URL', 'ENDPOINT')
    'bucket access key' = @('BUCKET_ACCESS_KEY_ID', 'AWS_ACCESS_KEY_ID', 'ACCESS_KEY_ID')
    'bucket secret key' = @('BUCKET_SECRET_ACCESS_KEY', 'AWS_SECRET_ACCESS_KEY', 'SECRET_ACCESS_KEY')
}
foreach ($label in $bucketGroups.Keys) {
    if (-not (Get-First $bucketGroups[$label])) { $problems += "$label is missing" }
}

if ($env:APP_ENV -and $env:APP_ENV.ToLower() -ne $Environment) { $problems += "APP_ENV must be '$Environment'" }
if ($env:STORAGE_MODE -and $env:STORAGE_MODE.ToLower() -ne 's3') { $problems += 'STORAGE_MODE must be s3' }
if ($env:DATABASE_URL -match '^sqlite') { $problems += 'DATABASE_URL must not be SQLite' }
if ($env:JWT_SECRET -and $env:JWT_SECRET.Length -lt 32) { $problems += 'JWT_SECRET must be at least 32 characters' }
if ($env:ADMIN_PASSWORD -and ($env:ADMIN_PASSWORD.Length -lt 12 -or $env:ADMIN_PASSWORD -eq 'ChangeMe123!')) { $problems += 'ADMIN_PASSWORD must be unique and at least 12 characters' }
# The Railway image serves UI + API same-origin, so CORS_ORIGINS may be unset; a wildcard never passes.
if ($env:CORS_ORIGINS -and ($env:CORS_ORIGINS -split ',' | ForEach-Object { $_.Trim() }) -contains '*') { $problems += 'CORS_ORIGINS must be an explicit allowlist, not *' }
if ($env:SEED_DEMO -and $env:SEED_DEMO.ToLower() -eq 'true') { $problems += 'SEED_DEMO must be false' }
if ($env:BUCKET_CORS_ORIGINS -eq '*') { Write-Warning 'BUCKET_CORS_ORIGINS=* allows any origin to use signed URLs; prefer an explicit allowlist.' }

if ($problems.Count) {
    throw ("$Environment preflight failed:`n - " + ($problems -join "`n - "))
}
Write-Host "$Environment variable shape passed local preflight. This does not validate remote connectivity or that staging and production differ." -ForegroundColor Green
