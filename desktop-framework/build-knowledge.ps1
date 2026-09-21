param(
  [Parameter(Mandatory=$true)][string]$Python,
  [Parameter(Mandatory=$true)][string]$DistPath
)
$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$destination = Join-Path $DistPath 'knowledge-worker'
if (Test-Path (Join-Path $DistPath 'data/knowledge.sqlite3')) { throw 'Refusing a business-data directory' }
New-Item -ItemType Directory -Force "$PSScriptRoot/evidence" | Out-Null
# Use a dedicated virtual environment. Never install into the desktop or BGE environment.
& $Python -m pip install -r "$PSScriptRoot/requirements-knowledge-worker.txt" pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; original programs are unchanged' }
& $Python -m pip freeze | Set-Content "$PSScriptRoot/evidence/knowledge-worker-resolved.txt" -Encoding utf8
& $Python -m PyInstaller --noconfirm --onedir --console --name knowledge-worker `
  --distpath $DistPath --workpath "$PSScriptRoot/build/knowledge" --specpath "$PSScriptRoot/build" `
  --paths "$PSScriptRoot/src" --collect-submodules semantica --collect-data semantica `
  --copy-metadata semantica --hidden-import ollama "$PSScriptRoot/src/knowledge_worker.py"
if ($LASTEXITCODE -ne 0) { throw 'Knowledge worker build failed' }
Write-Output "Built $destination. Run the live probe before copying to a candidate desktop build."
