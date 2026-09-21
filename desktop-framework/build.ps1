param(
  [string]$DistPath = "$PSScriptRoot/release-candidate",
  [string]$BuildPython = 'D:/知识库/work/rag-platform/venv/Scripts/python.exe',
  [string]$KnowledgeRuntimePath = "$PSScriptRoot/knowledge-dist/knowledge-worker",
  [switch]$SkipRuntimeCopy
)
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$taskRoot = $PSScriptRoot
$target = Join-Path $DistPath '知衡仿真知识库'
if ((Test-Path "$target/data/knowledge.sqlite3") -or (Test-Path "$DistPath/data/knowledge.sqlite3")) {
  throw 'Refusing to build over a directory containing business data. Use a fresh candidate directory.'
}
New-Item -ItemType Directory -Force "$taskRoot/evidence" | Out-Null
& $BuildPython -c "import pypdf"
if ($LASTEXITCODE -ne 0) { throw 'Install requirements-pipeline.txt in the desktop environment first.' }
Push-Location "$taskRoot/src"
try {
  & $BuildPython -m PyInstaller --noconfirm --onedir --windowed --name '知衡仿真知识库' --distpath $DistPath --workpath "$taskRoot/build/desktop" --specpath "$taskRoot/build" --add-data "$taskRoot/src/static;static" --hidden-import pypdf --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-data webview --exclude-module torch --exclude-module transformers --exclude-module sentence_transformers --exclude-module matplotlib --exclude-module pandas --exclude-module sklearn --exclude-module tkinter desktop.py *> "$taskRoot/evidence/build-desktop.log"
  if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed; see evidence/build-desktop.log' }
} finally { Pop-Location }
if ($SkipRuntimeCopy) {
  Write-Output "Desktop-only candidate: $target. Existing runtime components must be retained."
  exit 0
}
if (Test-Path "$taskRoot/semantic-dist/semantic-worker/semantic-worker.exe") {
  if (-not (Test-Path "$target/semantic-runtime")) { Copy-Item "$taskRoot/semantic-dist/semantic-worker" "$target/semantic-runtime" -Recurse }
}
if (Test-Path "$taskRoot/embedding-dist/embedding-worker/embedding-worker.exe") {
  robocopy "$taskRoot/embedding-dist/embedding-worker" "$target/embedding-runtime" /E /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Embedding runtime copy failed' }
  robocopy "$taskRoot/../runtime/embedding-model" "$target/embedding-model" /E /XD .cache /XF *.download /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Embedding model copy failed' }
}
if (Test-Path "$KnowledgeRuntimePath/knowledge-worker.exe") {
  robocopy $KnowledgeRuntimePath "$target/knowledge-runtime" /E /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Knowledge runtime copy failed' }
} else { Write-Warning 'Knowledge runtime not copied. Supply -KnowledgeRuntimePath for a complete distribution.' }
Write-Output "Candidate build: $target. Original EXE and business database were not replaced."
