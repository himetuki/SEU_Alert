#!/usr/bin/env bash
# QQ消息集散 · Linux 服务器版构建脚本
# 用法：
#   本地：bash linux/build_server.sh
#   CI：  bash linux/build_server.sh
# 产物：dist/seu_alert-portable-server/（无头二进制 + config + .env.example + systemd unit + 说明）
#      dist/seu_alert-portable-server.tar.gz（用于 GitHub Release 分发）
# 说明：入口 linux/server_entry.py；schema.sql 用绝对路径（PyInstaller 把相对路径解析到 spec 目录）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -z "${PYTHON:-}" ]; then
  if [ -x "$ROOT/.venv/bin/python" ]; then PYTHON="$ROOT/.venv/bin/python"
  else PYTHON="python3"; fi
fi
if [ -z "${OUT:-}" ]; then OUT="$ROOT/dist/seu_alert-portable-server"; fi

PYI_DIST="$ROOT/build/linux-pyi"
PYI_WORK="$ROOT/build/linux-work"
PYI_SPEC="$ROOT/build/linux-spec"
SCHEMA="$ROOT/src/seu_alert/store/schema.sql"

# 让 PyInstaller 能找到 src 下的 seu_alert（本地 venv 已装时亦无害）
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

echo "[1/5] 使用 Python: $PYTHON"
"$PYTHON" -c "import seu_alert" 2>/dev/null || {
  echo "seu_alert 不可导入：先 pip install -e . 或设 PYTHONPATH=src" >&2; exit 1; }

echo "[2/5] 安装构建依赖 pyinstaller ..."
"$PYTHON" -m pip install -q pyinstaller

echo "[3/5] PyInstaller one-dir 打包（无头服务器版）..."
rm -rf "$PYI_DIST" "$PYI_WORK" "$PYI_SPEC"
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --name seu_alert-server \
  --distpath "$PYI_DIST" --workpath "$PYI_WORK" --specpath "$PYI_SPEC" \
  --add-data "$SCHEMA:seu_alert/store" \
  --paths "$ROOT/src" \
  --hidden-import flask --hidden-import jinja2 --hidden-import yaml \
  --hidden-import httpx --hidden-import aiosqlite --hidden-import cryptography \
  --hidden-import dateparser --hidden-import apscheduler --hidden-import websockets \
  --collect-submodules seu_alert \
  linux/server_entry.py

echo "[4/5] 组装目录 dist/seu_alert-portable-server ..."
rm -rf "$OUT"
mkdir -p "$OUT/config"
cp -r "$PYI_DIST"/* "$OUT/"
cp config/*.yml "$OUT/config/"
cp config/subscriptions.yml.example "$OUT/config/"   # 订阅模板（真实 subscriptions.yml 首次运行自动生成）
cp .env.example "$OUT/.env.example"
cp docs/portable-readme.md "$OUT/使用说明.md"
cp linux/seu_alert-server.service "$OUT/"
cp linux/README.md "$OUT/LINUX-README.md"

echo "[5/5] 打包 tar.gz ..."
tar -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"

echo "完成：$OUT（含 $OUT.tar.gz）"
