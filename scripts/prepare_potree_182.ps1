param(
  [string]$TargetRoot = "$(Split-Path $PSScriptRoot -Parent)\web"
)
$ErrorActionPreference='Stop'
$tmp=Join-Path $env:TEMP 'potree-1.8.2-jsan'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
Write-Host 'Cloning Potree 1.8.2 (COPC-capable release)...' -ForegroundColor Cyan
git clone --depth 1 --branch 1.8.2 https://github.com/potree/potree.git $tmp
Push-Location $tmp
npm install
Pop-Location
$dest=Join-Path $TargetRoot 'potree'
New-Item -ItemType Directory -Force $dest | Out-Null
foreach($dir in @('build','libs','resources')){Copy-Item "$tmp\$dir" "$dest\$dir" -Recurse -Force}
Remove-Item $tmp -Recurse -Force
Write-Host "Potree 1.8.2 runtime prepared at $dest" -ForegroundColor Green
