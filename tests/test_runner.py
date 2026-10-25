"""Runner 端到端测试：A3（outbox 出文件）/ A5（灌水零文件）/ fan-in / 免打扰 /
ADR-008 顺序回归 / 重启后去重恢复。不起 NapCat——直接喂合成 RawEvent。"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from qq_relay.config import Subscription, SubscriptionsConfig
from qq_relay.contracts import RawEvent
from qq_relay.deliver.file import FileDeliverer
from qq_relay.pipeline.runner import Runner
from qq_relay.store import db as store_db

NOTICE = "高等数学第五章习题册作业已发布，请于11月15日23:59前提交至学习通，逾期不计分。"
CHATTER = "哈哈今天天气真不错啊大家歇歇"


def _ev(group: str, text: str, sender: str = "10001", mid: str = "m1") -> RawEvent:
    return RawEvent("qq_group", group, f"群{group}", sender, "某人", mid,
                    text, int(time.time()))


def _files(outbox, qq: str) -> list[str]:
    d = outbox / qq
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.name != "_说明.txt")


async def _mk(settings, groups_cfg, subs, now_fn=None):
    conn = await store_db.connect(settings)
    await store_db.init_schema(conn)
    runner = Runner(settings, groups_cfg, subs, FileDeliverer(settings.outbox_dir),
                    conn, now_fn=now_fn or datetime.now)
    await runner.restore_dedup()
    return runner, conn


def test_a3_delivery_and_a5_silence(tmp_path, settings, groups_cfg):
    """A3：作业通知 → outbox/<用户>/ 出文件；A5：灌水 → 零新增。"""

    async def scenario():
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("111",), ("homework", "exam"),
                                   quiet=(), instant_min_urg=2, digest=True)})
        runner, conn = await _mk(settings, groups_cfg, subs)
        try:
            await runner.handle_event(_ev("111", NOTICE))          # A3
            await runner.handle_event(_ev("111", CHATTER))         # A5
        finally:
            await conn.close()

        files = _files(settings.outbox_dir, "100001")
        assert len(files) == 1, files
        content = (settings.outbox_dir / "100001" / files[0]).read_text(encoding="utf-8")
        assert "【作业】" in content and "马原" in content and "11月15日" in content
        assert runner.stats == {"events": 2, "passed": 1, "dropped": 1,
                                "fan_in": 0, "delivered": 1}

    asyncio.run(scenario())


def test_fan_in_dedup_multi_group(tmp_path, settings, groups_cfg):
    """同通知两群出现：只分类一次；第二群订阅者补收，第一群不重发。"""

    async def scenario():
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("111",), ("homework",),
                                   quiet=(), instant_min_urg=2, digest=True),
            "100002": Subscription("100002", ("222",), ("homework",),
                                   quiet=(), instant_min_urg=2, digest=True)})
        runner, conn = await _mk(settings, groups_cfg, subs)
        try:
            await runner.handle_event(_ev("111", NOTICE, mid="m1"))
            await runner.handle_event(_ev("222", NOTICE, sender="20002", mid="m2"))
        finally:
            await conn.close()

        assert runner.stats["passed"] == 1
        assert runner.stats["fan_in"] == 1
        assert len(_files(settings.outbox_dir, "100001")) == 1   # 不重发
        assert len(_files(settings.outbox_dir, "100002")) == 1   # 新群命中补收

    asyncio.run(scenario())


def test_quiet_hours_goes_digest(tmp_path, settings, groups_cfg):
    """免打扰时段内：写 digest 文件而非即时文件。"""

    async def scenario():
        night = datetime(2026, 10, 25, 23, 30)
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("111",), ("homework",),
                                   quiet=("23:00-07:00",), instant_min_urg=2, digest=True)})
        runner, conn = await _mk(settings, groups_cfg, subs, now_fn=lambda: night)
        try:
            await runner.handle_event(_ev("111", NOTICE))
        finally:
            await conn.close()

        names = _files(settings.outbox_dir, "100001")
        assert len(names) == 1 and names[0].startswith("digest-"), names

    asyncio.run(scenario())


def test_adr008_sender_filter_no_dedup_poison(tmp_path, settings, groups_cfg):
    """ADR-008：黑名单群被滤拷贝不登记 hash，同内容在正常群仍可通过。"""

    async def scenario():
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("222",), ("homework",),
                                   quiet=(), instant_min_urg=2, digest=True)})
        runner, conn = await _mk(settings, groups_cfg, subs)
        try:
            await runner.handle_event(_ev("333", NOTICE, sender="999", mid="m1"))    # 被滤
            await runner.handle_event(_ev("222", NOTICE, sender="20002", mid="m2"))  # 应通过
        finally:
            await conn.close()

        assert runner.stats == {"events": 2, "passed": 1, "dropped": 1,
                                "fan_in": 0, "delivered": 1}
        assert len(_files(settings.outbox_dir, "100001")) == 1

    asyncio.run(scenario())


def test_dedup_survives_restart(tmp_path, settings, groups_cfg):
    """重启后从 events 表恢复去重状态：同内容不再重复分类。"""

    async def scenario():
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("111",), ("homework",),
                                   quiet=(), instant_min_urg=2, digest=True)})
        r1, c1 = await _mk(settings, groups_cfg, subs)
        await r1.handle_event(_ev("111", NOTICE, mid="m1"))
        await c1.close()

        r2, c2 = await _mk(settings, groups_cfg, subs)
        try:
            await r2.handle_event(_ev("111", NOTICE, mid="m2"))   # 同内容 → 判重
        finally:
            await c2.close()

        assert r2.stats["passed"] == 0 and r2.stats["fan_in"] == 1
        assert len(_files(settings.outbox_dir, "100001")) == 1    # 仍不重发

    asyncio.run(scenario())
