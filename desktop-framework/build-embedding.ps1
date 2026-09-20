$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$buildPython='D:\zhishiku\runtime\embedding-venv\Scripts\python.exe'
$env:PYTHONPATH=''
$env:PYTHONIOENCODING='utf-8'
Push-Location "$taskRoot\src"
try {
 & $buildPython -m PyInstaller --noconfirm --onedir --console --name embedding-worker --distpath "$taskRoot\embedding-dist" --workpath "$taskRoot\build\embedding" --specpath "$taskRoot\build" --collect-data transformers --collect-data torch --copy-metadata transformers --copy-metadata torch --copy-metadata tokenizers --copy-metadata huggingface-hub --copy-metadata safetensors --copy-metadata numpy --copy-metadata regex --copy-metadata requests --copy-metadata packaging --copy-metadata filelock --copy-metadata pyyaml --copy-metadata tqdm --hidden-import transformers.models.xlm_roberta.modeling_xlm_roberta --hidden-import transformers.models.xlm_roberta.tokenization_xlm_roberta_fast --hidden-import transformers.models.bert.tokenization_bert --exclude-module torchvision --exclude-module torchaudio --exclude-module matplotlib --exclude-module tensorflow --exclude-module sentence_transformers --exclude-module sklearn --exclude-module pandas --exclude-module scipy --exclude-module cv2 --exclude-module IPython --exclude-module pytest embedding_worker.py *> "$taskRoot\evidence\build-embedding.log"
 if ($LASTEXITCODE -ne 0) {throw 'Embedding build failed; see evidence/build-embedding.log'}
} finally {Pop-Location}
