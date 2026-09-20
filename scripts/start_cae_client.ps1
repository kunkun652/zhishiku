$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$bundle = Join-Path $root 'runtime\cae-dsh-app'
$exe = Join-Path $bundle 'cae-agent.exe'
$runDir = Join-Path $root 'runtime\run'
$userData = Join-Path $root 'runtime\cae-user-data'
$pidFile = Join-Path $runDir 'cae-client.pid'
$nativeDshHome = Join-Path $bundle 'dsh-data\dsh'
if (-not (Test-Path -LiteralPath $exe)) { throw "本地 CAE 客户端缺失: $exe" }
New-Item -ItemType Directory -Force -Path $runDir,$userData,$nativeDshHome | Out-Null
$nativeSettings = Join-Path $nativeDshHome 'settings.yaml'
if (-not (Test-Path -LiteralPath $nativeSettings)) {
  Set-Content -LiteralPath $nativeSettings -Value "agent-presets:`r`n  default: cae" -Encoding utf8
}
if (Test-Path -LiteralPath $pidFile) {
  $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
  $old = Get-CimInstance Win32_Process -Filter "ProcessId=$oldPid" -ErrorAction SilentlyContinue
  if ($old -and $old.ExecutablePath -eq $exe) { Write-Host "本地 CAE 客户端已运行，PID=$oldPid"; exit 0 }
  Remove-Item -LiteralPath $pidFile -Force
}
$environment = @{
  CAE_AGENT_USER_DATA = $userData
  CAE_KB_MCP_SCRIPT = (Join-Path $root 'integrations\dsh\kb_mcp_server.py')
  CAE_KB_ROOT = $root
  PYTHONUTF8 = '1'
  PYTHONDONTWRITEBYTECODE = '1'
}
$process = Start-Process -FilePath $exe -WorkingDirectory $bundle -WindowStyle Normal -Environment $environment -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ascii
Write-Host "本地复制版 CAE 客户端已启动，PID=$($process.Id)"
