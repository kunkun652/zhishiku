param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$formal = Join-Path $PSScriptRoot 'release\知衡仿真知识库'
$candidate = Join-Path $PSScriptRoot 'release-ux-final-20260920\知衡仿真知识库'
$evidence = Join-Path $PSScriptRoot 'evidence\ux-20260920'
$expectedOld = (Get-Content -LiteralPath (Join-Path $evidence 'baseline-exe.json') -Raw | ConvertFrom-Json).Hash
$oldExe = Join-Path $formal '知衡仿真知识库.exe'
$newExe = Join-Path $candidate '知衡仿真知识库.exe'
if ((Get-FileHash -LiteralPath $oldExe).Hash -ne $expectedOld) { throw '正式 EXE 已变化，请重新核对，不覆盖未知版本。' }
$manifest = Get-Content -LiteralPath (Join-Path $evidence 'release-manifest.json') -Raw | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $newExe).Hash -ne $manifest.candidate_exe_sha256) { throw '候选 EXE 与验收版本不符。' }
Write-Output "正式：$oldExe"
Write-Output "候选：$newExe"
Write-Output '只更新 EXE 和 _internal；保留 data、原件、两个索引及现有 embedding/semantic 运行时。'
if (-not $Apply) { Write-Output '当前为只读检查。确认采用此交付后，以 -Apply 执行。'; return }
$runtimeFile = Join-Path $formal 'data\runtime.json'
$runtime = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)"
if ($process.ExecutablePath -ne $oldExe) { throw '正式运行进程路径不符。' }
$state = Invoke-RestMethod "$($runtime.url)/api/embedding/v2/status"
$resume = $state.status -eq 'building'
if ($resume) {
    Invoke-RestMethod -Method Post "$($runtime.url)/api/embedding/v2/stop" -ContentType 'application/json' -Body '{}' | Out-Null
    $deadline = (Get-Date).AddMinutes(2)
    do {
        Start-Sleep -Seconds 2
        $state = Invoke-RestMethod "$($runtime.url)/api/embedding/v2/status"
        if ((Get-Date) -gt $deadline) { throw '当前编码批次尚未结束，取消程序更新。' }
    } while ($state.status -eq 'building')
}
$backup = Join-Path $PSScriptRoot ('backups\runtime-ux-apply-' + (Get-Date -Format yyyyMMdd-HHmmss))
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item -LiteralPath $oldExe -Destination $backup
robocopy (Join-Path $formal '_internal') (Join-Path $backup '_internal') /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw '回退资源复制失败，未停止正式程序。' }
$state | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backup 'index-before.json') -Encoding utf8
Stop-Process -Id $runtime.pid
Wait-Process -Id $runtime.pid -Timeout 15 -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $newExe -Destination $oldExe -Force
robocopy (Join-Path $candidate '_internal') (Join-Path $formal '_internal') /E /R:1 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "资源更新失败；回退包：$backup。保留 data，仅恢复回退 EXE 与 _internal。" }
$fresh = Start-Process -FilePath $oldExe -WindowStyle Hidden -PassThru
$deadline = (Get-Date).AddMinutes(1)
do {
    Start-Sleep -Seconds 1
    $current = Get-Content -LiteralPath $runtimeFile -Raw | ConvertFrom-Json
    if ((Get-Date) -gt $deadline) { throw "启动等待超时，请查看 data\desktop.log。回退包：$backup" }
} while ($current.pid -ne $fresh.Id)
$health = Invoke-RestMethod "$($current.url)/api/health"
if ($health.build -ne '1.3.0-readable-workspaces') { throw '启动版本不符。' }
if ($resume) { Invoke-RestMethod -Method Post "$($current.url)/api/embedding/v2/build" -ContentType 'application/json' -Body '{}' | Out-Null }
$after = Invoke-RestMethod "$($current.url)/api/embedding/v2/status"
if ($after.indexed -lt $state.indexed) { throw '已编码单元数下降，停止验收并保留现场。' }
@{runtime=$current;health=$health;index_before=$state;index_after=$after;rollback=$backup} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence 'formal-update-receipt.json') -Encoding utf8
Write-Output "已更新，索引 $($state.indexed) → $($after.indexed)。回退包：$backup"
