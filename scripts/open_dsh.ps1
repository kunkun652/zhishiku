$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
& (Join-Path $PSScriptRoot 'start.ps1')
Start-Process 'http://127.0.0.1:8765/#assistant'
