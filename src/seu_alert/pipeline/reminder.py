"""临期提醒调度（ADR-023）：deadline 前多轮提醒（默认 24h/3h）。

流程：L5 匹配分发时，带 deadline 的 item 为每个匹配用户写入 reminders 行；
调度器每分钟扫描到期行 → deliver(kind="reminder") → 标记已发。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Optional

from ..contracts import ClassifiedEvent
from ..deliver.base import Deliverer
from ..store import queries


def parse_iso(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


class ReminderScheduler:
    def __init__(self, db, deliverer: Deliverer,
                 offsets: tuple[int, ...] = (24, 3), interval: int = 60,
                 now_fn: Callable[[], datetime] = datetime.now) -> None:
        self.db = db
        self.deliverer = deliverer
        self.offsets = tuple(offsets)
        self.interval = interval
        self.now_fn = now_fn
        self.stats = {"scheduled": 0, "sent": 0, "errors": 0}

    async def schedule_for(self, item: ClassifiedEvent, user_qq: str) -> int:
        """为一条 item 的一个用户生成提醒行（去重）。返回新建条数。"""
        if not item.deadline:
            return 0
        dt = parse_iso(item.deadline)
        if dt is None:
            return 0
        created = 0
        for h in self.offsets:
            fire = int(dt.timestamp()) - h * 3600
            if await queries.insert_reminder(self.db, item.event_id, user_qq,
                                             fire, f"reminder-{h}h"):
                created += 1
        self.stats["scheduled"] += created
        return created

    async def tick(self) -> int:
        now = int(self.now_fn().timestamp())
        rows = await queries.due_reminders(self.db, now)
        sent = 0
        for r in rows:
            row = await queries.get_item(self.db, r["event_id"])
            if row is None:                      # item 被删 → 直接标记，不卡队列
                await queries.mark_reminder_sent(self.db, r["reminder_id"], "")
                continue
            item = await queries.row_to_item(row)
            try:
                path = await self.deliverer.deliver(r["user_qq"], item, "reminder")
                await queries.mark_reminder_sent(self.db, r["reminder_id"], path)
                sent += 1
            except Exception as e:
                self.stats["errors"] += 1
                print(f"[reminder] 分发失败 event={r['event_id']} "
                      f"user={r['user_qq']}: {e!r}")
        self.stats["sent"] += sent
        return sent

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as e:
                self.stats["errors"] += 1
                print(f"[reminder] tick 失败: {e!r}")
            await asyncio.sleep(self.interval)
