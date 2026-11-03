# win/ · Windows 便携版构建源码

Windows 平台专用的构建源码集中在此目录，**产物仍输出到项目根 `dist/`**（`dist/` 已 gitignore）。

| 文件 | 作用 |
|---|---|
| `build_portable.ps1` | PyInstaller one-dir 打包脚本：产出 `dist/seu_alert-portable-win/` 与 `dist/seu_alert-portable-win.zip` |
| `portable_entry.py` | 便携版入口：启动后台管理（`qq_relay.admin.main(open_browser=True)`） |

## 本地构建

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File win\build_portable.ps1
# 或（推荐）用 PowerShell 7：
pwsh -NoProfile -ExecutionPolicy Bypass -File win\build_portable.ps1
```

脚本优先用项目内 `.venv\Scripts\python.exe`，找不到则回退到 `python`（CI 走这条）。
产物 `dist\seu_alert-portable-win\` 整个文件夹（或 zip）发给使用者，双击 `qq-relay.exe` 即可。

> ⚠️ **`build_portable.ps1` 必须保留 UTF-8 BOM**（文件头 `EF BB BF`）。脚本内含中文字符串，
> Windows PowerShell 5.1 会把**无 BOM 的 UTF-8** 按 ANSI 解析，导致语法错误、构建失败。
> 用编辑器改动该文件后请确认 BOM 未被去掉；CI 已固定用 `pwsh`（PowerShell 7）执行。

## CI 构建

GitHub Actions 工作流 `.github/workflows/build.yml` 的 `win` job：
`windows-latest` → `setup-python` → 装依赖 → 跑本脚本 → 上传 artifact / Release。

## 关联

- 使用者说明：[docs/portable-readme.md](../docs/portable-readme.md)
- 操作手册：[docs/runbook.md](../docs/runbook.md)（第 11 节便携版打包）
- Linux 服务器版：[linux/](../linux/)
