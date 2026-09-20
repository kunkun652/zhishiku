$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$dshHome = Join-Path $root 'runtime\dsh-home'
$source = Join-Path $root 'runtime\cae-dsh-app\presets\cae'
$targetRoot = Join-Path $root 'runtime\dsh-home\.agent-presets'
$target = Join-Path $targetRoot 'cae'
if (-not (Test-Path -LiteralPath (Join-Path $source 'preset.yml'))) { throw "本地 CAE preset 缺失: $source" }
New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
if (Test-Path -LiteralPath $target) {
  $marker = Join-Path $target '.cae-kb-managed'
  if (-not (Test-Path -LiteralPath $marker)) { throw "目标 CAE preset 不是本项目管理，拒绝覆盖: $target" }
}
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -LiteralPath (Join-Path $source 'preset.yml') -Destination (Join-Path $target 'preset.yml') -Force
Copy-Item -LiteralPath (Join-Path $source 'agent.cordis.yml') -Destination (Join-Path $target 'agent.cordis.yml') -Force
Set-Content -LiteralPath (Join-Path $target '.cae-kb-managed') -Value 'managed-by=D:\zhishiku' -Encoding ascii
$viewerPluginSource = Join-Path $root 'runtime\cae-dsh-app\runtime\dsh\node_modules\@cae-agent\dsh-cae-viewer-mcp'
$viewerPluginScope = Join-Path $dshHome 'profiles\node_modules\@cae-agent'
$viewerPluginTarget = Join-Path $viewerPluginScope 'dsh-cae-viewer-mcp'
if (-not (Test-Path -LiteralPath (Join-Path $viewerPluginSource 'package.json'))) { throw "复制版 Viewer MCP 插件缺失: $viewerPluginSource" }
New-Item -ItemType Directory -Force -Path $viewerPluginScope | Out-Null
Copy-Item -LiteralPath $viewerPluginSource -Destination $viewerPluginScope -Recurse -Force
Set-Content -LiteralPath (Join-Path $viewerPluginTarget '.cae-kb-managed') -Value 'managed-by=D:\zhishiku' -Encoding ascii
$settings = Join-Path $dshHome 'settings.yaml'
if (-not (Test-Path -LiteralPath $settings)) {
  Set-Content -LiteralPath $settings -Value "agent-presets:`r`n  default: cae" -Encoding utf8
}
