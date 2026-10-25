"""Web 采集适配器包：SEU-Monitor / SEUdaily 输出库 → RawEvent（ADR-022）。"""

from .base import WebNotice, WebPoller, WebSource
from .seu_monitor import scan as scan_seu_monitor
from .seudaily import scan as scan_seudaily

SCANNERS = {
    "seu_monitor": scan_seu_monitor,
    "seudaily": scan_seudaily,
}

__all__ = ["WebNotice", "WebPoller", "WebSource", "SCANNERS",
           "scan_seu_monitor", "scan_seudaily"]
