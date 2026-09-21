$ErrorActionPreference='Stop'
$formal='D:\zhishiku\desktop-framework\release\知衡仿真知识库'
$candidate='D:\zhishiku\desktop-framework\release-candidate-reader-20260921\知衡仿真知识库'
$rollback='D:\zhishiku\desktop-framework\backups\trusted-before-reader-fix-20260921'
$exe=Join-Path $formal '知衡仿真知识库.exe'
$expected='56C227E4A18F2924B3CBAF81FAA84EAB2F3BC94EA882413EFDAC41145E539628'
if ((Get-FileHash -LiteralPath $exe).Hash -ne 'CB3BB18A8F47D90E9633C1D2EF0E6937A49E0780F01318236FAA537DC4F82633') {throw 'Unexpected installed version'}
if ((Get-FileHash -LiteralPath "$candidate\知衡仿真知识库.exe").Hash -ne $expected) {throw 'Candidate hash mismatch'}
$source=(Resolve-Path -LiteralPath "$formal\_internal").Path
$destination=[IO.Path]::GetFullPath("$rollback\_internal")
if ($source -ne 'D:\zhishiku\desktop-framework\release\知衡仿真知识库\_internal' -or $destination -ne 'D:\zhishiku\desktop-framework\backups\trusted-before-reader-fix-20260921\_internal' -or (Test-Path -LiteralPath $rollback)) {throw 'Unsafe or existing rollback target'}
$runtime=Get-Content -LiteralPath "$formal\data\runtime.json" -Raw|ConvertFrom-Json
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($runtime.pid)"
if ($process.ExecutablePath -ne $exe) {throw 'Unexpected running process'}
New-Item -ItemType Directory -Path $rollback | Out-Null
Copy-Item -LiteralPath $exe -Destination $rollback
Stop-Process -Id $runtime.pid
Wait-Process -Id $runtime.pid -Timeout 10 -ErrorAction SilentlyContinue
Move-Item -LiteralPath $source -Destination $destination
Copy-Item -LiteralPath "$candidate\_internal" -Destination $formal -Recurse
Copy-Item -LiteralPath "$candidate\知衡仿真知识库.exe" -Destination $exe -Force
if ((Get-FileHash -LiteralPath $exe).Hash -ne $expected) {throw 'Installed hash mismatch'}
Start-Process -FilePath 'D:\zhishiku\新版知衡知识库.lnk' -WindowStyle Normal
Write-Output "Reader fix installed; original 1.5 rollback remains in pre-trusted-20260921. SHA256 $expected"
