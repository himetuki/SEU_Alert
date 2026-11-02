"""Web 采集适配器包 → RawEvent。

采集源（ADR-029 后自包含，不再依赖外部程序先跑一遍）：
- jwc          教务处六栏目**直采**（WebPlus CMS，ADR-029，替代 SEU-Monitor）
- seu_monitor  旧通道：读 SEU-Monitor（Go）归档库（保留兼容，ADR-022）
- seudaily     读 SEUdaily 网页库（保留兼容，ADR-022）
- seu_colleges 全院系 33 学院官网直采（ADR-024）
- labor        劳动教育课程平台（移植 SEU-Labor-Course-Pusher，ADR-024）
- wechat_mp    公众号监控（免登录 + 模型代读，ADR-025）
- seu_lectures 人文讲座监控（移植 seu-lecture-cli 监控能力，ADR-025）
"""

from .base import WebNotice, WebPoller, WebSource
from .jwc import scan as scan_jwc
from .labor import scan as scan_labor
from .seu_colleges import scan as scan_seu_colleges
from .seu_lectures import scan as scan_seu_lectures
from .seu_monitor import scan as scan_seu_monitor
from .seudaily import scan as scan_seudaily
from .wechat_mp import scan as scan_wechat_mp

SCANNERS = {
    "jwc": scan_jwc,
    "seu_monitor": scan_seu_monitor,
    "seudaily": scan_seudaily,
    "seu_colleges": scan_seu_colleges,
    "labor": scan_labor,
    "wechat_mp": scan_wechat_mp,
    "seu_lectures": scan_seu_lectures,
}

__all__ = ["WebNotice", "WebPoller", "WebSource", "SCANNERS",
           "scan_jwc", "scan_seu_monitor", "scan_seudaily", "scan_seu_colleges",
           "scan_labor", "scan_wechat_mp", "scan_seu_lectures"]
