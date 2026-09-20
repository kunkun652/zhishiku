& (Join-Path $PSScriptRoot 'scripts\open_dsh.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
