$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$runDir = Join-Path $root 'runtime\run'
foreach ($name in @('api','dsh','cae-client')) {
  $pidFile = Join-Path $runDir "$name.pid"
  if (-not (Test-Path -LiteralPath $pidFile)) { continue }
  $targetPid = [int](Get-Content -LiteralPath $pidFile -Raw)
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$targetPid" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -like "*$root*") {
    Stop-Process -Id $targetPid -Force
    Write-Host "已停止 $name，PID=$targetPid"
  } elseif ($proc) {
    Write-Warning "PID=$targetPid 不属于本项目，未停止"
  }
  Remove-Item -LiteralPath $pidFile -Force
}
