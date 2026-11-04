# linux/ · Linux 服务器版构建源码

Linux 服务器版：**无头二进制**（PyInstaller one-dir）+ **systemd unit**，产物仍输出到项目根 `dist/`。

| 文件 | 作用 |
|---|---|
| `server_entry.py` | 服务器入口：`seu_alert.admin.main(host=0.0.0.0, open_browser=False)`，可用 `ADMIN_HOST`/`ADMIN_PORT` 覆盖 |
| `build_server.sh` | PyInstaller one-dir 打包脚本：产出 `dist/seu_alert-portable-server/` 与 `dist/seu_alert-portable-server.tar.gz` |
| `seu_alert-server.service` | systemd unit（部署时按实际路径修改） |

## 与 Windows 便携版的区别

| | Windows 便携版（[win/](../win/)） | Linux 服务器版（本目录） |
|---|---|---|
| 入口 | `win/portable_entry.py` → admin + 自动开浏览器 | `linux/server_entry.py` → admin，不开浏览器，绑 `0.0.0.0:8000` |
| PyInstaller | `--windowed`（无控制台） | 默认 console（日志走 journald） |
| 打包形态 | `dist/seu_alert-portable-win/`（zip 分发） | `dist/seu_alert-portable-server/`（tar.gz 分发 + systemd） |
| 分发对象 | 校内用户本地电脑 | Linux 服务器（常驻服务） |

## 本地构建（WSL / Linux）

```bash
bash linux/build_server.sh
```

脚本优先用项目内 `.venv/bin/python`，找不到则回退到 `python3`（CI 走这条）。

## 服务器部署

```bash
sudo mkdir -p /opt/seu_alert-server
sudo cp -r dist/seu_alert-portable-server/* /opt/seu_alert-server/
sudo useradd -r -s /usr/sbin/nologin seu_alert
sudo chown -R seu_alert:seu_alert /opt/seu_alert-server
# 编辑 /opt/seu_alert-server/seu_alert-server.service 里的路径
sudo cp /opt/seu_alert-server/seu_alert-server.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now seu_alert-server
sudo journalctl -u seu_alert-server -f
```

后台管理入口 `http://<服务器IP>:8000`；`.env` 填 PushPlus token / 讲座·劳动教育 CAS 账号。

## CI 构建

GitHub Actions 工作流 `.github/workflows/build.yml` 的 `linux` job：
`ubuntu-latest` → `setup-python` → 装依赖 → 跑本脚本 → 上传 artifact / Release。
