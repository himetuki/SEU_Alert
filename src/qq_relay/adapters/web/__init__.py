"""Web 采集适配器包：SEU-Monitor / SEUdaily 输出库 → RawEvent（ADR-022）。

ADR-024 起：seu_colleges（全院系直采）与 labor（劳动教育，移植
SEU-Labor-Course-Pusher 源码）。ADR-025 起：wechat_mp（公众号监控，
免登录+模型代读）与 seu_lectures（人文讲座监控，移植 seu-lecture-cli
监控能力，不用预约）。
"""

from .base import WebNotice, WebPoller, WebSource
from .labor import scan as scan_labor
from .seu_colleges import scan as scan_seu_colleges
from .seu_lectures import scan as scan_seu_lectures
from .seu_monitor import scan as scan_seu_monitor
from .seudaily import scan as scan_seudaily
from .wechat_mp import scan as scan_wechat_mp

SCANNERS = {
    "seu_monitor": scan_seu_monitor,
    "seudaily": scan_seudaily,
    "seu_colleges": scan_seu_colleges,
    "labor": scan_labor,
    "wechat_mp": scan_wechat_mp,
    "seu_lectures": scan_seu_lectures,
}

__all__ = ["WebNotice", "WebPoller", "WebSource", "SCANNERS",
           "scan_seu_monitor", "scan_seudaily", "scan_seu_colleges",
           "scan_labor", "scan_wechat_mp", "scan_seu_lectures"]
