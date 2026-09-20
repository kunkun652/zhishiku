$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$collectionPython = Join-Path $PSScriptRoot 'collection\.venv\Scripts\python.exe'
foreach ($collectionScript in @('crawl.py','crawl_basics.py','ingest.py','build_cards.py','link_cards.py','organize.py')) {
  & $collectionPython (Join-Path $PSScriptRoot ('collection\'+$collectionScript))
  if ($LASTEXITCODE -ne 0) { throw "处理失败：$collectionScript，请查看 collection 中的日志。" }
}
Write-Host '本批处理完成。请在知识库中查看导入与质量；候选资料不代表工程复核或训练许可通过。'
