# -*- coding: utf-8 -*-
"""PyInstaller 便携版入口：启动后台管理（含全部监控）。

PyInstaller one-dir 打包本文件；运行期数据/配置目录 = exe 同级目录。
"""
from qq_relay.admin import main

if __name__ == "__main__":
    main(open_browser=True)
