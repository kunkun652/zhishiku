param([string]$DataRoot = '', [switch]$Check)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run desktop-framework/setup-dev.ps1 first. See desktop-framework/DEVELOPING.md.'
}
& $python (Join-Path $PSScriptRoot 'scripts/check-dev.py')
if ($LASTEXITCODE -ne 0) { throw 'Preflight failed. Rerun setup-dev.ps1; see DEVELOPING.md.' }
if ($Check) { exit 0 }
if ($DataRoot) { $env:ZH_DATA_ROOT = [IO.Path]::GetFullPath($DataRoot) }
elseif (-not $env:ZH_DATA_ROOT) { $env:ZH_DATA_ROOT = Join-Path $PSScriptRoot 'data' }
Write-Host "Data directory: $env:ZH_DATA_ROOT"
Write-Host 'Opening source desktop. Close its window to stop. Errors: data directory/desktop.log'
& $python (Join-Path $PSScriptRoot 'src/desktop.py')
if ($LASTEXITCODE -ne 0) { throw "Desktop exited with an error. Check $env:ZH_DATA_ROOT/desktop.log" }
