$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$runDir = Join-Path $root 'runtime\run'
$logDir = Join-Path $root 'runtime\logs'
$dshHome = Join-Path $root 'runtime\dsh-home'
New-Item -ItemType Directory -Force -Path $runDir,$logDir,$dshHome | Out-Null
& (Join-Path $PSScriptRoot 'prepare_dsh_home.ps1')

# The embedded DSH Viewer MCP must bind to this project's copied CAE client.
# Discover the live loopback API owned by the recorded client PID; never reuse a
# machine-global or source-tree instance and never hard-code a previous port.
& (Join-Path $PSScriptRoot 'start_cae_client.ps1')
$caePidFile = Join-Path $runDir 'cae-client.pid'
if (-not (Test-Path -LiteralPath $caePidFile)) { throw '复制版 CAE 客户端 PID 文件缺失' }
$caePid = [int](Get-Content -LiteralPath $caePidFile -Raw)
$caeExe = Join-Path $root 'runtime\cae-dsh-app\cae-agent.exe'
$caeProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$caePid" -ErrorAction SilentlyContinue
if (-not $caeProcess -or $caeProcess.ExecutablePath -ne $caeExe) { throw 'CAE 客户端不属于本项目复制版' }
$caeApiUrl = $null
$caeDeadline = (Get-Date).AddSeconds(30)
do {
  $ports = @(Get-NetTCPConnection -State Listen -OwningProcess $caePid -ErrorAction SilentlyContinue | Where-Object LocalAddress -eq '127.0.0.1' | Select-Object -ExpandProperty LocalPort -Unique)
  foreach ($port in $ports) {
    try {
      $candidate = "http://127.0.0.1:$port"
      $probeBody = [Text.Encoding]::UTF8.GetBytes((@{ tool = 'model.summary'; args = @{} } | ConvertTo-Json -Compress))
      $caeHealth = Invoke-RestMethod -Uri "$candidate/api/v1/cae" -Method Post -ContentType 'application/json; charset=utf-8' -Body $probeBody -TimeoutSec 2
      if ($caeHealth.ok -eq $true) { $caeApiUrl = $candidate; break }
    } catch { }
  }
  if (-not $caeApiUrl) { Start-Sleep -Milliseconds 400 }
} while (-not $caeApiUrl -and (Get-Date) -lt $caeDeadline)
if (-not $caeApiUrl) { throw '无法发现本项目复制版 CAE API 动态端点' }

if (-not (Test-Path -LiteralPath (Join-Path $root 'data\knowledge.db'))) {
  & $python (Join-Path $root 'scripts\import_data.py')
  if ($LASTEXITCODE -ne 0) { throw '初次数据导入失败' }
}

$apiPidFile = Join-Path $runDir 'api.pid'
if (Test-Path -LiteralPath $apiPidFile) {
  $oldPid = [int](Get-Content -LiteralPath $apiPidFile -Raw)
  if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) { Write-Host "知识库服务已运行，PID=$oldPid" }
  else { Remove-Item -LiteralPath $apiPidFile -Force }
}
if (-not (Test-Path -LiteralPath $apiPidFile)) {
  $dshPidFile = Join-Path $runDir 'dsh.pid'
  if (Test-Path -LiteralPath $dshPidFile) {
    $oldDshPid = [int](Get-Content -LiteralPath $dshPidFile -Raw)
    $oldDsh = Get-CimInstance Win32_Process -Filter "ProcessId=$oldDshPid" -ErrorAction SilentlyContinue
    if ($oldDsh -and $oldDsh.ExecutablePath -eq (Join-Path $root 'runtime\cae-dsh-app\runtime\node\node.exe')) {
      Stop-Process -Id $oldDshPid -Force
      Wait-Process -Id $oldDshPid -Timeout 10 -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $dshPidFile -Force
  }
  $apiEnvironment = @{
    CAE_AGENT_API_URL = $caeApiUrl
    PYTHONUTF8 = '1'
    PYTHONDONTWRITEBYTECODE = '1'
  }
  $api = Start-Process -FilePath $python -ArgumentList @((Join-Path $root 'server\app.py')) -WorkingDirectory $root -WindowStyle Hidden -Environment $apiEnvironment -RedirectStandardOutput (Join-Path $logDir 'api.out.log') -RedirectStandardError (Join-Path $logDir 'api.err.log') -PassThru
  Set-Content -LiteralPath $apiPidFile -Value $api.Id -Encoding ascii
}

$deadline = (Get-Date).AddSeconds(30)
do {
  try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2; break } catch { Start-Sleep -Milliseconds 400 }
} while ((Get-Date) -lt $deadline)
if (-not $health) { throw '知识库服务 30 秒内未就绪，请查看 runtime\logs\api.err.log' }
$dshState = $null
$dshDeadline = (Get-Date).AddSeconds(30)
do {
  try { $dshState = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/dsh/status' -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 400 }
} while ($dshState.state -ne 'ready' -and (Get-Date) -lt $dshDeadline)
if ($dshState.state -ne 'ready') { throw 'DSH Web 30 秒内未就绪，请查看 runtime\logs\dsh.err.log' }
Write-Host "知识工作台  http://127.0.0.1:8765"
Write-Host "DSH Web    http://127.0.0.1:3088"
Write-Host "CAE API    $caeApiUrl"
Write-Host "知识对象    $($health.objects)"
Write-Host "DeepSeek    $($health.deepseek.label)"
Write-Host "集成入口    知识工作台 -> DSH 智能助手（原生界面嵌入）"
