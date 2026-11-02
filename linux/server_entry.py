# -*- coding: utf-8 -*-
"""Linux 服务器版入口：无头运行后台管理（不自动开浏览器，绑 0.0.0.0）。

PyInstaller one-dir 打包本文件；运行期数据/配置目录 = 二进制同级目录。
主机/端口可用环境变量覆盖：ADMIN_HOST / ADMIN_PORT（默认 0.0.0.0 / 8000）。
"""
import os

from qq_relay.admin import main

if __name__ == "__main__":
    main(
        host=os.environ.get("ADMIN_HOST", "0.0.0.0"),
        port=int(os.environ.get("ADMIN_PORT", "8000")),
        open_browser=False,
    )
