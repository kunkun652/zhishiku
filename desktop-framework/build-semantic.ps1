$ErrorActionPreference='Stop'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONIOENCODING='utf-8'
$taskRoot=$PSScriptRoot
$env:PYTHONPATH="$taskRoot\build-tools;D:\zhishiku\runtime\semantica-packages"
$buildPython='C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Push-Location "$taskRoot\src"
try {
  & $buildPython -m PyInstaller --noconfirm --onedir --console --name semantic-worker --collect-submodules scipy._external.array_api_compat --distpath "$taskRoot\semantic-dist" --workpath "$taskRoot\build\semantic" --specpath "$taskRoot\build" --exclude-module torch --exclude-module transformers --exclude-module sentence_transformers --exclude-module matplotlib --exclude-module spacy --exclude-module tensorflow --exclude-module streamlit --exclude-module cv2 --exclude-module sklearn --exclude-module pandas --exclude-module jax --exclude-module gradio --exclude-module pytest semantic_worker.py *> "$taskRoot\evidence\build-semantic.log"
  if ($LASTEXITCODE -ne 0) { throw 'Semantica build failed; see evidence/build-semantic.log' }
} finally { Pop-Location }


