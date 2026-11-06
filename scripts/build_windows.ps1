# 构建 Windows 单文件版 VBob.exe。
# 用法：在项目根目录运行  powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
# 产物：dist\VBob.exe（以及可选的 dist\VBob-windows-x64.zip）
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "==> 同步 Python 依赖"
uv sync --extra dev

Write-Host "==> 构建前端"
Push-Location web
try {
    if (-not (Test-Path node_modules)) {
        npm install
    }
    npm run build
} finally {
    Pop-Location
}

if (-not (Test-Path "web\dist\index.html")) {
    throw "前端构建失败：web\dist\index.html 不存在"
}

Write-Host "==> PyInstaller 打包"
# 删除旧产物，避免把上一次的 data/日志打进压缩包。
if (Test-Path "build") { Remove-Item "build" -Recurse -Force }
if (Test-Path "dist\VBob.exe") { Remove-Item "dist\VBob.exe" -Force }

uv run pyinstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name VBob `
    --icon "assets\vbob.ico" `
    --add-data "web/dist;web/dist" `
    --add-data "vbob/migrations;vbob/migrations" `
    --collect-submodules uvicorn `
    launcher.py

Write-Host "==> 生成 zip"
if (-not (Test-Path "dist")) { New-Item -ItemType Directory "dist" | Out-Null }
if (Test-Path "dist\VBob-windows-x64.zip") { Remove-Item "dist\VBob-windows-x64.zip" -Force }
Compress-Archive -Path "dist\VBob.exe" -DestinationPath "dist\VBob-windows-x64.zip" -Force

Write-Host ""
Write-Host "完成："
Write-Host "  dist\VBob.exe"
Write-Host "  dist\VBob-windows-x64.zip"
Write-Host "首次双击运行会在 exe 同目录创建 data\ 文件夹（数据库、封面、日志）。"
