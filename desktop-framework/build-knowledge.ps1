param([string]$Python = 'python', [switch]$InstallDependencies)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$root = $PSScriptRoot
$venv = Join-Path $root 'knowledge-venv'
$workerPython = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $workerPython)) {
  & $Python -m venv $venv
  if ($LASTEXITCODE -ne 0) { throw 'Cannot create isolated knowledge worker environment' }
  $InstallDependencies = $true
}
if ($InstallDependencies) {
  & $workerPython -m pip install -r "$root\requirements-knowledge.txt"
  if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; existing runtimes were not modified' }
}
New-Item -ItemType Directory -Force "$root\build\knowledge", "$root\evidence" | Out-Null
Push-Location "$root\src"
try {
  & $workerPython -c 'from app.pipeline_extraction import health; import json; print(json.dumps(health()))'
  if ($LASTEXITCODE -ne 0) { throw 'Real Semantica extraction smoke test failed; refusing to package' }
  & $workerPython -m PyInstaller --noconfirm --onedir --name knowledge-worker --distpath "$root\knowledge-dist" --workpath "$root\build\knowledge" --specpath "$root\build\knowledge" --collect-all semantica --collect-all ollama --copy-metadata semantica knowledge_worker.py *> "$root\evidence\build-knowledge.log"
  if ($LASTEXITCODE -ne 0) { throw 'Knowledge worker build failed; see evidence/build-knowledge.log' }
} finally { Pop-Location }
Write-Output 'Worker built in knowledge-dist only. The running desktop EXE and business data were not replaced.'
