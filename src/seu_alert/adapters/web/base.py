"""Web 采集源：把本机已在运行的爬虫项目输出库转成 RawEvent 流。

接入原则（ADR-022）：**消费现有项目的输出库，不重写爬虫**。
- SEU-Monitor（Go）：`<root>/web/教务处/<栏目>/<标题--ID>/{meta.json,text.md}`
- SEUdaily（TS/Python）：`<root>/metadata/<sha>.json` + `files/<host>/<section>/<notice>/<sha>.md`

每个源首次扫描全量入库（backfill），之后只出新内容；已见 key 落 `web_seen` 表，
与 QQ 消息共用同一条分类树和订阅匹配（群 = 站点，如 web-jwc / web-cse）。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ...contracts import RawEvent
from .errors import friendly_error

TEXT_MAX = 1500


@dataclass(frozen=True)
class WebNotice:
    """从输出库解析出的一条网页通知（转 RawEvent 前的中间态）。"""

    key: str                 # 稳定去重键（源内唯一）
    group_id: str            # 合成群 id（web-<站点>）
    group_name: str
    title: str
    text: str                # 已含【栏目】前缀与正文
    url: str
    ts: int
    sender: str = ""
    column: str = ""         # 栏目中文名（jwc 等直采用；归档生成需要）
    notice_id: str = ""      # 站点内通知 ID（归档目录命名用）

    def to_raw_event(self, msg_id: str) -> RawEvent:
        return RawEvent(
            source="web_crawl",
            group_id=self.group_id,
            group_name=self.group_name,
            sender_id=f"web:{self.group_id}",
            sender_card=self.sender or self.group_name,
            msg_id=msg_id,
            text=self.text,
            ts=self.ts,
            at_all=False,
        )


@dataclass(frozen=True)
class WebSource:
    id: str
    kind: str                # seu_monitor | seudaily
    name: str
    root: Path
    interval: int = 900


Scanner = Callable[[Path], Iterable[WebNotice]]


class WebPoller:
    """轮询一个 web 源：首次全量 backfill，之后增量。

    seen 集合由调用方从 DB 恢复；mark_seen 由调用方持久化（重启不重复入队）。
    """

    def __init__(self, source: WebSource, scanner: Scanner, seen: set[str],
                 on_notice: Callable[[RawEvent], "object"],
                 mark_seen: Callable[[str], "object"]) -> None:
        self.source = source
        self.scanner = scanner
        self.seen = seen
        self.on_notice = on_notice
        self.mark_seen = mark_seen
        self.stats = {"scans": 0, "new": 0, "errors": 0}

    async def poll_once(self) -> int:
        """扫描一轮，把新通知交给 on_notice 并标记 seen。返回新增条数。

        scanner / on_notice / mark_seen 均兼容同步函数与协程函数
        （文件扫描器同步，学院/劳动教育扫描器异步）。
        """
        notices = self.scanner(self.source.root)
        if inspect.isawaitable(notices):
            notices = await notices
        notices = list(notices)
        new = 0
        for n in notices:
            if n.key in self.seen:
                continue
            self.seen.add(n.key)
            marked = self.mark_seen(n.key)
            if inspect.isawaitable(marked):
                await marked
            delivered = self.on_notice(n.to_raw_event(f"{self.source.id}:{n.key}"))
            if inspect.isawaitable(delivered):
                await delivered
            new += 1
        self.stats["scans"] += 1
        self.stats["new"] += new
        self.stats["last_scan_at"] = int(time.time())
        return new

    async def run_forever(self) -> None:
        first = True
        while True:
            try:
                new = await self.poll_once()
                if first:
                    print(f"[web:{self.source.id}] 首次扫描 {self.stats['new']} 条新增"
                          f"（root={self.source.root}）")
                    first = False
            except Exception as e:               # 扫描失败不拖垮主管道
                self.stats["errors"] += 1
                self.stats["last_error"] = friendly_error(e)
                print(f"[web:{self.source.id}] 扫描失败: {e!r}")
            await asyncio.sleep(self.source.interval)


def _truncate(text: str) -> str:
    text = text.strip()
    return text[:TEXT_MAX] + ("…" if len(text) > TEXT_MAX else "")
