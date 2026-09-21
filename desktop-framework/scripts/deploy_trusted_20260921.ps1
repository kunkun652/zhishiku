$ErrorActionPreference = 'Stop'
$formal = 'D:\zhishiku\desktop-framework\release\知衡仿真知识库'
$candidate = 'D:\zhishiku\desktop-framework\release-candidate-trusted-20260921\知衡仿真知识库'
$backup = 'D:\zhishiku\desktop-framework\backups\pre-trusted-20260921'
$shortcut = 'D:\zhishiku\新版知衡知识库.lnk'
$oldExe = Join-Path $formal '知衡仿真知识库.exe'
$newExe = Join-Path $candidate '知衡仿真知识库.exe'
if ((Get-FileHash -LiteralPath $oldExe).Hash -ne 'B54B53DF108E460834A293DC1EEE3FD9974E169A9540BCF6D9AF7C71A6FF4DD7') { throw 'Formal EXE changed; refusing overwrite.' }
if ((Get-FileHash -LiteralPath $newExe).Hash -ne 'CB3BB18A8F47D90E9633C1D2EF0E6937A49E0780F01318236FAA537DC4F82633') { throw 'Candidate hash mismatch.' }
if (-not (Test-Path -LiteralPath "$backup\knowledge.sqlite3") -or -not (Test-Path -LiteralPath "$backup\preservation.json")) { throw 'Missing rollback database or inventory.' }
$shell = New-Object -ComObject WScript.Shell
if ($shell.CreateShortcut($shortcut).TargetPath -ne $oldExe) { throw 'Unexpected shortcut target.' }
$runtime = Get-Content -LiteralPath "$formal\data\runtime.json" -Raw | ConvertFrom-Json
$process = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)"
if ($process.ExecutablePath -ne $oldExe) { throw 'Running process path mismatch.' }
$pipeline = Invoke-RestMethod -NoProxy "$($runtime.url)/api/pipeline/status"
if ($pipeline.jobs.running -or $pipeline.jobs.queued -or $pipeline.index_requests.Count) { throw 'Pending processing exists; defer upgrade.' }
$index = Invoke-RestMethod -NoProxy "$($runtime.url)/api/embedding/v2/status"
if ($index.status -eq 'building') { throw 'Index is still building; defer upgrade.' }
foreach ($name in @('_internal','embedding-runtime')) {
    $source = (Resolve-Path -LiteralPath "$formal\$name").Path
    $target = [IO.Path]::GetFullPath("$backup\$name")
    if ($source -ne "$formal\$name" -or $target -ne "$backup\$name" -or (Test-Path -LiteralPath $target)) { throw 'Unsafe or existing rollback target.' }
    if (-not (Test-Path -LiteralPath "$candidate\$name")) { throw 'Candidate component missing.' }
}
if ((Get-FileHash -LiteralPath "$candidate\embedding-runtime\embedding-worker.exe").Hash -ne (Get-FileHash -LiteralPath 'D:\zhishiku\desktop-framework\embedding-dist\embedding-worker\embedding-worker.exe').Hash) { throw 'Embedding worker copy mismatch.' }
Copy-Item -LiteralPath $oldExe -Destination $backup
Copy-Item -LiteralPath $shortcut -Destination $backup
# Stop only the validated, idle release. Business data stays in place.
Stop-Process -Id $runtime.pid
Wait-Process -Id $runtime.pid -Timeout 10 -ErrorAction SilentlyContinue
foreach ($worker in (Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq "$formal\embedding-runtime\embedding-worker.exe"})) {
    Stop-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue
}
foreach ($name in @('_internal','embedding-runtime')) {
    Move-Item -LiteralPath "$formal\$name" -Destination "$backup\$name"
    Copy-Item -LiteralPath "$candidate\$name" -Destination $formal -Recurse
}
Copy-Item -LiteralPath $newExe -Destination $oldExe -Force
if ((Get-FileHash -LiteralPath $oldExe).Hash -ne (Get-FileHash -LiteralPath $newExe).Hash) { throw 'Installed EXE mismatch.' }
# The user explicitly wants this desktop application visible.
Start-Process -FilePath $shortcut -WindowStyle Normal
$deadline = (Get-Date).AddSeconds(50)
do {
    Start-Sleep -Seconds 1
    $fresh = Get-Content -LiteralPath "$formal\data\runtime.json" -Raw | ConvertFrom-Json
} while ($fresh.pid -eq $runtime.pid -and (Get-Date) -lt $deadline)
if ($fresh.pid -eq $runtime.pid) { throw 'Fresh application did not report readiness.' }
$active = Get-CimInstance Win32_Process -Filter "ProcessId=$($fresh.pid)"
if ($active.ExecutablePath -ne $oldExe) { throw 'Unexpected active program.' }
$ping = Invoke-RestMethod -NoProxy "$($fresh.url)/api/ping" -TimeoutSec 15
if ($ping.build -ne '1.6.0-trusted-workbench') { throw 'Unexpected build.' }
$denied = Invoke-WebRequest -NoProxy "$($fresh.url)/api/library/files" -SkipHttpErrorCheck
if ($denied.StatusCode -ne 401) { throw 'Anonymous data access was not denied.' }
$receipt = @{runtime=$fresh;build=$ping.build;anonymous_library_status=$denied.StatusCode;exe_sha256=(Get-FileHash -LiteralPath $oldExe).Hash;embedding_sha256=(Get-FileHash -LiteralPath "$formal\embedding-runtime\embedding-worker.exe").Hash;index_before=$index;backup=$backup;shortcut=$shortcut}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$backup\deployment.json" -Encoding utf8
$receipt | ConvertTo-Json -Depth 5
