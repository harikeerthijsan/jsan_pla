param(
  [Parameter(Mandatory=$true)][string]$ApiBase,
  [string]$WebRoot = "$(Split-Path $PSScriptRoot -Parent)\web"
)
$api=$ApiBase.TrimEnd('/')
@"
window.PLA_CONFIG = {
  API_BASE: "$api",
  PROJECT_ID: "sample1"
};
"@ | Set-Content (Join-Path $WebRoot 'config.js') -Encoding UTF8
Write-Host "Configured web API: $api" -ForegroundColor Green
