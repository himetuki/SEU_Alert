"""Web 采集适配器包：SEU-Monitor / SEUdaily 输出库 → RawEvent（ADR-022）。

ADR-024 起新增：seu_colleges（全院系直采）与 labor（劳动教育，移植
SEU-Labor-Course-Pusher 源码逻辑）。
"""

from .base import WebNotice, WebPoller, WebSource
from .labor import scan as scan_labor
from .seu_colleges import scan as scan_seu_colleges
from .seu_monitor import scan as scan_seu_monitor
from .seudaily import scan as scan_seudaily

SCANNERS = {
    "seu_monitor": scan_seu_monitor,
    "seudaily": scan_seudaily,
    "seu_colleges": scan_seu_colleges,
    "labor": scan_labor,
}

__all__ = ["WebNotice", "WebPoller", "WebSource", "SCANNERS",
           "scan_seu_monitor", "scan_seudaily", "scan_seu_colleges",
           "scan_labor"]
