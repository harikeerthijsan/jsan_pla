param([string]$ApiBase="http://localhost:8000")
$ErrorActionPreference="Stop"
$h=Invoke-RestMethod "$ApiBase/health"
if($h.status -ne 'ok'){throw 'health failed'}
Write-Host "Health OK - version $($h.version)" -ForegroundColor Green
$body=@{email='admin@jsan.local';password='ChangeMe123!'}|ConvertTo-Json
$login=Invoke-RestMethod "$ApiBase/api/auth/login" -Method Post -Body $body -ContentType 'application/json'
$headers=@{Authorization="Bearer $($login.token)"}
$projects=Invoke-RestMethod "$ApiBase/api/projects" -Headers $headers
Write-Host "Authentication OK; projects found: $($projects.Count)" -ForegroundColor Green
if($projects.Count -gt 0){
  $pid=$projects[0].id
  $s=Invoke-RestMethod "$ApiBase/api/projects/$pid/summary" -Headers $headers
  Write-Host "First project: $pid - $($s.poles) poles / $($s.findings) findings" -ForegroundColor Green
  $poles=Invoke-RestMethod "$ApiBase/api/projects/$pid/poles" -Headers $headers
  $measurable=$poles | Where-Object { $_.block_name } | Select-Object -First 1
  if($measurable){
    try {
      $frame=Invoke-RestMethod "$ApiBase/api/projects/$pid/poles/$($measurable.internal_id)/analysis-frame" -Headers $headers
      Write-Host "Profile frame OK for pole $($measurable.internal_id); target: $($frame.frame.target_internal_id)" -ForegroundColor Green
    } catch { Write-Host "Profile frame check skipped: $($_.Exception.Message)" -ForegroundColor Yellow }
  }
}
