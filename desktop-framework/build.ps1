param([string]$DistPath = "$PSScriptRoot\release")
$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
$taskRoot = $PSScriptRoot
$buildPython = 'D:\知识库\work\rag-platform\venv\Scripts\python.exe'
Push-Location "$taskRoot\src"
try {
  & $buildPython -m PyInstaller --noconfirm --onedir --windowed --name '知衡仿真知识库' --distpath $DistPath --workpath "$taskRoot\build\desktop" --specpath "$taskRoot\build" --add-data "$taskRoot\src\static;static" --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --collect-data webview --exclude-module torch --exclude-module transformers --exclude-module sentence_transformers --exclude-module matplotlib --exclude-module pandas --exclude-module sklearn --exclude-module tkinter desktop.py *> "$taskRoot\evidence\build-desktop.log"
  if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed; see evidence/build-desktop.log' }
} finally { Pop-Location }
if (Test-Path "$taskRoot\semantic-dist\semantic-worker\semantic-worker.exe") {
  if (-not (Test-Path -LiteralPath "$DistPath\知衡仿真知识库\semantic-runtime")) { Copy-Item -LiteralPath "$taskRoot\semantic-dist\semantic-worker" -Destination "$DistPath\知衡仿真知识库\semantic-runtime" -Recurse }
}
if (Test-Path "$taskRoot\embedding-dist\embedding-worker\embedding-worker.exe") {
  robocopy "$taskRoot\embedding-dist\embedding-worker" "$DistPath\知衡仿真知识库\embedding-runtime" /E /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Embedding runtime copy failed' }
  robocopy "$taskRoot\..\runtime\embedding-model" "$DistPath\知衡仿真知识库\embedding-model" /E /XD .cache /XF *.download /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw 'Embedding model copy failed' }
}
