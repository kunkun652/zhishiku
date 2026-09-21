param([string]$Python = '')
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
if (-not $Python) {
    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) {
        throw 'Install Python 3.11 x64, or pass -Python C:\path\to\python.exe. See DEVELOPING.md.'
    }
    $Python = (& py.exe -3.11 -c 'import sys; print(sys.executable)')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 x64 is required. See DEVELOPING.md.' }
}
& $Python -c 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32'
if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python. Use Python 3.11 x64.' }
if (-not (Get-Command node.exe -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw 'Install Node.js 22 or 24 (including npm), then reopen PowerShell.'
}
& node.exe -e 'if(parseInt(process.versions.node) < 20) process.exit(1)'
if ($LASTEXITCODE -ne 0) { throw 'Node.js 20 or newer is required.' }
$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (Test-Path -LiteralPath $venv) { throw 'Incomplete .venv exists. Inspect it before choosing a new checkout.' }
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& $venvPython -c 'import sys; assert sys.version_info[:2] == (3,11) and sys.maxsize > 2**32'
if ($LASTEXITCODE -ne 0) { throw 'Existing .venv is not Python 3.11 x64; it was not replaced.' }
& $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-desktop-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed. Fix network/index access and rerun.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Python dependency conflicts detected.' }
Push-Location (Join-Path $PSScriptRoot 'tools/frontend')
try {
    & npm.cmd ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
} finally { Pop-Location }
& node.exe (Join-Path $PSScriptRoot 'scripts/prepare-assets.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Static asset preparation failed.' }
& $venvPython (Join-Path $PSScriptRoot 'scripts/check-dev.py')
if ($LASTEXITCODE -ne 0) { throw 'Developer environment checks failed.' }
Write-Host 'Setup complete. Run: powershell -ExecutionPolicy Bypass -File .\desktop-framework\start-dev.ps1'
