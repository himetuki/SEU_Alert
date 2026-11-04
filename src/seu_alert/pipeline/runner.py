"""管道编排（P1）：RawEvent → 预筛 → 假分类器 → 匹配 → 文件分发。

fan-in 语义（ADR-009）：同内容通知在多个群出现只分类一次；重复拷贝把新群
追加进 item.groups，只给**新命中**的用户补分发（已收过的不重发）。
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime
from uuid import uuid4

import aiosqlite

from ..config import GroupsConfig, Settings, SubscriptionsConfig
from ..contracts import ClassifiedEvent, RawEvent
from ..deliver.base import Deliverer
from .prefilter import Deduper, Decision, Prefilter, Stage
from .classifier_stub import classify_stub
from . import matcher
from ..store import queries


class Runner:
    def __init__(
        self,
        settings: Settings,
        groups: GroupsConfig,
        subs: SubscriptionsConfig,
        deliverer: Deliverer,
        db: aiosqlite.Connection,
        classifier=classify_stub,
        prefilter: Prefilter | None = None,
        now_fn=datetime.now,
        reminder_hook=None,
    ) -> None:
        self.settings = settings
        self.groups = groups
        self.subs = subs
        self.deliverer = deliverer
        self.db = db
        self.classifier = classifier
        self.now_fn = now_fn
        self.reminder_hook = reminder_hook      # async (item, user_qq) -> None
        self.deduper = Deduper()
        self.prefilter = prefilter or Prefilter(generic_words=groups.generic_words)
        self.stats = {"events": 0, "passed": 0, "dropped": 0,
                      "fan_in": 0, "delivered": 0}

    async def restore_dedup(self) -> None:
        """重启后从 events 表恢复去重状态（不重分类存量）。"""
        self.deduper.load_pairs(await queries.load_dedup_pairs(self.db))

    async def handle_event(self, ev: RawEvent) -> None:
        self.stats["events"] += 1
        profile = self.groups.profile_of(ev.group_id)
        d: Decision = self.prefilter.process(ev, profile, self.deduper)

        if d.dry_run_would_drop:
            await queries.log_filtered(self.db, None, "sender_filter",
                                       d.reason, f"群{ev.group_id}")

        if not d.passed:
            await self._on_drop(ev, d)
            return

        event_id = uuid4().hex[:12]
        self.deduper.register(d.content_hash, event_id)
        item: ClassifiedEvent = self.classifier(
            ev, event_id, profile.course if profile else None)
        self._apply_hints(item, ev.hints)
        await queries.insert_event(self.db, ev, event_id, d.content_hash)
        await queries.insert_item(self.db, item)
        self.stats["passed"] += 1
        await self._deliver(item, already=set())

    @staticmethod
    def _apply_hints(item: ClassifiedEvent, hints: dict) -> None:
        """提取层预填字段合并进 item（不覆盖已有值；P2 tree.py 同样受益）。"""
        if not hints:
            return
        for key in ("course", "channel", "scope", "stage"):
            value = hints.get(key)
            if value and not getattr(item, key, None):
                setattr(item, key, str(value))
        deadline = hints.get("deadline")
        if deadline and not item.deadline:
            item.deadline = str(deadline)
            item.deadline_src = "hint"
            item.has_ddl = True

    async def _on_drop(self, ev: RawEvent, d: Decision) -> None:
        self.stats["dropped"] += 1
        if d.stage is Stage.DEDUP:
            await self._fan_in(ev, d.duplicate_of)
            return
        await queries.log_filtered(self.db, None, d.stage.value, d.reason,
                                   f"群{ev.group_id} {ev.text[:40]}")

    async def _fan_in(self, ev: RawEvent, orig_event_id: str | None) -> None:
        if not orig_event_id:
            return
        groups = await queries.add_item_group(self.db, orig_event_id, ev.group_id)
        if not groups:
            return
        row = await queries.get_item(self.db, orig_event_id)
        if row is None:
            return
        item = await queries.row_to_item(row)
        item.groups = groups
        self.stats["fan_in"] += 1
        already = await queries.delivered_event_users(self.db, orig_event_id)
        await self._deliver(item, already=already)

    async def _deliver(self, item: ClassifiedEvent, already: set[str]) -> None:
        now = self.now_fn()
        for m in matcher.match_all(self.subs.subs.values(), item, now):
            if m.user_qq in already:
                continue                      # fan-in 不重发
            path = await self.deliverer.deliver(m.user_qq, item, m.kind)
            await queries.insert_delivery(
                self.db, m.user_qq, item.event_id, self.settings.deliver_mode,
                path, m.kind, item.urg)
            self.stats["delivered"] += 1
            if self.reminder_hook is not None and item.deadline:
                res = self.reminder_hook(item, m.user_qq)
                if inspect.isawaitable(res):
                    await res
