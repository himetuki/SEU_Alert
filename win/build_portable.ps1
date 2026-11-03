# QQ消息集散 · Windows 便携版构建脚本
# 用法：
#   本地：powershell -NoProfile -ExecutionPolicy Bypass -File win\build_portable.ps1
#   CI：  powershell -NoProfile -ExecutionPolicy Bypass -File win\build_portable.ps1 -Python python
# 产物：dist\seu_alert-portable-win\（整个文件夹拷给使用者即可，无需 Python）
#      dist\seu_alert-portable-win.zip（用于 GitHub Release 分发）
# 说明：入口 win\portable_entry.py；schema.sql 用绝对路径（PyInstaller 把相对路径解析到 spec 目录）。

param(
    [string]$Python = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Python) {
    $Venv = Join-Path $Root ".venv\Scripts\python.exe"
    if (Test-Path $Venv) { $Python = $Venv } else { $Python = "python" }
}
if (-not $OutDir) { $OutDir = Join-Path $Root "dist\seu_alert-portable-win" }

# 让 PyInstaller 能找到 src 下的 qq_relay（本地 venv 已装时亦无害）
$env:PYTHONPATH = "$Root\src" + $(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" })

Write-Host "[1/5] 使用 Python: $Python"
& $Python -c "import qq_relay" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Error "qq_relay 不可导入（先 pip install -e . 或设 PYTHONPATH=src）" }

Write-Host "[2/5] 安装构建依赖 pyinstaller ..."
& $Python -m pip install -q pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Error "pyinstaller 安装失败" }

Write-Host "[3/5] PyInstaller one-dir 打包 ..."
$Schema = Join-Path $Root "src\qq_relay\store\schema.sql"
if (Test-Path "build\qq-relay") { Remove-Item -Recurse -Force "build\qq-relay" }
if (Test-Path "dist\qq-relay") { Remove-Item -Recurse -Force "dist\qq-relay" }
& $Python -m PyInstaller --noconfirm --clean --onedir --windowed --name qq-relay `
  --distpath dist --workpath build --specpath build `
  --add-data "$Schema;qq_relay/store" `
  --paths "$Root\src" `
  --hidden-import flask --hidden-import jinja2 --hidden-import yaml `
  --hidden-import httpx --hidden-import aiosqlite --hidden-import cryptography `
  --hidden-import dateparser --hidden-import apscheduler --hidden-import websockets `
  --collect-submodules qq_relay `
  win\portable_entry.py
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller 打包失败" }

Write-Host "[4/5] 组装便携目录 dist\seu_alert-portable-win ..."
if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
New-Item -ItemType Directory -Path $OutDir | Out-Null
Copy-Item -Recurse "dist\qq-relay\*" $OutDir
New-Item -ItemType Directory -Path (Join-Path $OutDir "config") -Force | Out-Null
Copy-Item "config\*.yml" $OutDir\config\
Copy-Item "config\subscriptions.yml.example" $OutDir\config\   # 订阅模板（真实 subscriptions.yml 首次运行自动生成）
Copy-Item ".env.example" $OutDir\.env.example
Copy-Item "docs\portable-readme.md" $OutDir\使用说明.md
Copy-Item "win\README.md" $OutDir\WIN-README.md
# 给使用者一份可直接编辑的 .env（预设 file,pushplus 双出口）
Copy-Item "$OutDir\.env.example" "$OutDir\.env"
(Get-Content "$OutDir\.env") -replace '^DELIVER_MODE=file$', 'DELIVER_MODE=file,pushplus' |
  Set-Content "$OutDir\.env" -Encoding UTF8

Write-Host "[5/5] 打包 zip ..."
$Zip = Join-Path $Root "dist\seu_alert-portable-win.zip"
if (Test-Path $Zip) { Remove-Item -Force $Zip }
Compress-Archive -Path (Join-Path $OutDir "*") -DestinationPath $Zip

Write-Host "完成：$OutDir（含 $Zip）"
Get-ChildItem $OutDir | Select-Object Mode, Length, Name | Format-Table -AutoSize
Write-Host "把整个 seu_alert-portable-win 文件夹（或 zip）发给使用者；使用者双击 qq-relay.exe 即可。"
