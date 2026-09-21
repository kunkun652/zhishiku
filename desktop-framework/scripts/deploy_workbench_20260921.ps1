$ErrorActionPreference = 'Stop'
$formal = 'D:\zhishiku\desktop-framework\release\知衡仿真知识库'
$candidate = 'D:\zhishiku\desktop-framework\release-candidate-workbench-20260921\知衡仿真知识库'
$backup = 'D:\zhishiku\desktop-framework\backups\pre-workbench-20260921'
$shortcut = 'D:\zhishiku\新版知衡知识库.lnk'
$oldExe = Join-Path $formal '知衡仿真知识库.exe'
$newExe = Join-Path $candidate '知衡仿真知识库.exe'
if ((Get-FileHash -LiteralPath $oldExe).Hash -ne '26B72ADB04590CC8409EF43BF1DB880127B96EB7DF95B500A2BC01CB4CC76837') { throw 'Formal EXE changed; do not overwrite an unknown version.' }
if ((Get-FileHash -LiteralPath $newExe).Hash -ne 'B54B53DF108E460834A293DC1EEE3FD9974E169A9540BCF6D9AF7C71A6FF4DD7') { throw 'Candidate hash mismatch.' }
if (-not (Test-Path -LiteralPath "$backup\knowledge.sqlite3") -or -not (Test-Path -LiteralPath "$backup\preservation.json")) { throw 'Missing rollback database or inventory.' }
$shell = New-Object -ComObject WScript.Shell
if ($shell.CreateShortcut($shortcut).TargetPath -ne $oldExe) { throw 'Shortcut points to a different program.' }
$runtime = Get-Content -LiteralPath "$formal\data\runtime.json" -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)"
if ($process.ExecutablePath -ne $oldExe) { throw 'Running process path mismatch.' }
$pipeline = Invoke-RestMethod -NoProxy "$($runtime.url)/api/pipeline/status"
if ($pipeline.jobs.running -or $pipeline.jobs.queued -or $pipeline.index_requests.Count) { throw 'Pending processing exists; defer upgrade.' }
$index = Invoke-RestMethod -NoProxy "$($runtime.url)/api/embedding/v2/status"
if ($index.status -eq 'building') { throw 'Index is still building; defer upgrade.' }
$from = (Resolve-Path -LiteralPath "$formal\_internal").Path
$to = [IO.Path]::GetFullPath("$backup\_internal")
if ($from -ne 'D:\zhishiku\desktop-framework\release\知衡仿真知识库\_internal' -or $to -ne 'D:\zhishiku\desktop-framework\backups\pre-workbench-20260921\_internal' -or (Test-Path -LiteralPath $to)) { throw 'Invalid move target.' }
Copy-Item -LiteralPath $oldExe -Destination $backup
Copy-Item -LiteralPath $shortcut -Destination $backup
$ui = Get-Process -Id $runtime.pid
$null = $ui.CloseMainWindow()
try { Wait-Process -Id $runtime.pid -Timeout 12 -ErrorAction Stop } catch {
    $remaining = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)"
    if ($remaining -and $remaining.ExecutablePath -eq $oldExe) { Stop-Process -Id $runtime.pid; Wait-Process -Id $runtime.pid -Timeout 10 -ErrorAction SilentlyContinue }
}
Move-Item -LiteralPath $from -Destination $to
try {
    Copy-Item -LiteralPath "$candidate\_internal" -Destination $formal -Recurse
    Copy-Item -LiteralPath $newExe -Destination $oldExe -Force
} catch { throw "Program replacement failed. Rollback files are in $backup; data has not been replaced. $($_.Exception.Message)" }
if ((Get-FileHash -LiteralPath $oldExe).Hash -ne (Get-FileHash -LiteralPath $newExe).Hash) { throw 'Installed EXE mismatch.' }
Start-Process -FilePath $shortcut
$deadline = (Get-Date).AddSeconds(55)
do {
    Start-Sleep -Seconds 1
    $fresh = Get-Content -LiteralPath "$formal\data\runtime.json" -Raw | ConvertFrom-Json
} while ($fresh.pid -eq $runtime.pid -and (Get-Date) -lt $deadline)
if ($fresh.pid -eq $runtime.pid) { throw 'Fresh application did not report readiness.' }
$active = Get-CimInstance Win32_Process -Filter "ProcessId=$($fresh.pid)"
if ($active.ExecutablePath -ne $oldExe) { throw 'Started an unexpected application.' }
$health = Invoke-RestMethod -NoProxy "$($fresh.url)/api/health" -TimeoutSec 35
if ($health.build -ne '1.5.0-clear-workbench') { throw 'Unexpected application build.' }
$receipt = @{runtime=$fresh;build=$health.build;exe_sha256=(Get-FileHash -LiteralPath $oldExe).Hash;counts=$health.counts;index_before=$index;backup=$backup;shortcut=$shortcut}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$backup\deployment.json" -Encoding utf8
$receipt | ConvertTo-Json -Depth 5
