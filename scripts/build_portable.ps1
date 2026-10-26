# QQ消息集散 · 便携版构建脚本（Windows）
# 用法：在项目根目录执行  powershell -ExecutionPolicy Bypass -File scripts\build_portable.ps1
# 产物：dist\qq-relay-portable\（整个文件夹拷给使用者即可，无需 Python）

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Venv)) { Write-Error "找不到 .venv，请先按 docs/runbook.md 第 0 节建环境" }

Write-Host "[1/5] 安装构建依赖 pyinstaller ..."
& $Venv -m pip install -q pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Error "pyinstaller 安装失败" }

Write-Host "[2/5] PyInstaller one-dir 打包 ..."
if (Test-Path "build\qq-relay") { Remove-Item -Recurse -Force "build\qq-relay" }
if (Test-Path "dist\qq-relay") { Remove-Item -Recurse -Force "dist\qq-relay" }
$Schema = Join-Path $Root "src\qq_relay\store\schema.sql"
& $Venv -m PyInstaller --noconfirm --clean --onedir --windowed --name qq-relay `
  --distpath dist --workpath build --specpath build `
  --add-data "$Schema;qq_relay/store" `
  --hidden-import flask --hidden-import jinja2 --hidden-import yaml `
  --hidden-import httpx --hidden-import aiosqlite --hidden-import cryptography `
  --hidden-import dateparser --hidden-import apscheduler --hidden-import websockets `
  --collect-submodules qq_relay `
  portable_entry.py
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller 打包失败" }

Write-Host "[3/5] 组装便携目录 dist\qq-relay-portable ..."
$Out = Join-Path $Root "dist\qq-relay-portable"
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out }
New-Item -ItemType Directory -Path $Out | Out-Null
Copy-Item -Recurse "dist\qq-relay\*" $Out
New-Item -ItemType Directory -Path (Join-Path $Out "config") -Force | Out-Null
Copy-Item "config\*.yml" $Out\config\
Copy-Item ".env.example" $Out\.env.example

Write-Host "[4/5] 写入使用者使用说明 ..."
Copy-Item "docs\portable-readme.md" $Out\使用说明.md
# 给使用者一份可直接编辑的 .env（预设 file,pushplus 双出口）
Copy-Item "$Out\.env.example" "$Out\.env"
(Get-Content "$Out\.env") -replace '^DELIVER_MODE=file$', 'DELIVER_MODE=file,pushplus' |
  Set-Content "$Out\.env" -Encoding UTF8

Write-Host "[5/5] 完成：$Out"
Get-ChildItem $Out | Select-Object Mode, Length, Name | Format-Table -AutoSize
Write-Host "把整个 qq-relay-portable 文件夹发给使用者；使用者双击 qq-relay.exe 即可。"
