$ErrorActionPreference="Stop"
$Pdal = "C:\Users\admin\miniforge3\envs\pla-qc\Library\bin\pdal.exe"
if (-not (Test-Path $Pdal)) { $Pdal = (Get-Command pdal -ErrorAction Stop).Source }
Write-Host "PDAL: $Pdal" -ForegroundColor Cyan
& $Pdal --version
$drivers=& $Pdal --drivers | Out-String
foreach($d in @('readers.las','readers.copc','writers.copc','writers.text')){
  if($drivers -match [regex]::Escape($d)){Write-Host "$d OK" -ForegroundColor Green}else{throw "$d missing"}
}
Write-Host "Profile processing stack is available." -ForegroundColor Green
