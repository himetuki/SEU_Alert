"""文件分发测试（ADR-021）：outbox/<用户QQ>/ 一个文件夹代表一个用户。"""

from __future__ import annotations

import asyncio

from qq_relay.contracts import ClassifiedEvent
from qq_relay.deliver.base import render_push
from qq_relay.deliver.file import FileDeliverer


def _item() -> ClassifiedEvent:
    return ClassifiedEvent(
        event_id="abcdef123456", groups=["111"], cat="homework", cat2="homework",
        is_info=0.9, urg=2, action="submit", has_ddl=True, course="马原",
        deadline="2026-11-15T23:59:00+08:00", deadline_src="regex",
        raw_text="高等数学第五章习题册作业已发布，请于11月15日23:59前提交至学习通")


def test_render_push_template():
    text = render_push(_item())
    assert "【作业】" in text
    assert "紧急度 2/3" in text
    assert "马原" in text
    assert "2026-11-15T23:59:00+08:00" in text
    assert "测试期文件分发" in text
    assert "高等数学" in text


def test_instant_file_created(tmp_path):
    async def scenario():
        d = FileDeliverer(tmp_path / "outbox")
        path = await d.deliver("100001", _item(), "instant")
        p = __import__("pathlib").Path(path)
        assert p.parent == tmp_path / "outbox" / "100001"
        assert p.suffix == ".txt" and "_homework_" in p.name
        assert (tmp_path / "outbox" / "100001" / "_说明.txt").exists()
        assert "【作业】" in p.read_text(encoding="utf-8")
        # 再发一条 → 第二个文件（不覆盖）
        await d.deliver("100001", _item(), "instant")
        files = [x for x in p.parent.iterdir() if x.name != "_说明.txt"]
        assert len(files) == 2

    asyncio.run(scenario())


def test_digest_appends(tmp_path):
    async def scenario():
        d = FileDeliverer(tmp_path / "outbox")
        await d.deliver("100001", _item(), "digest")
        await d.deliver("100001", _item(), "digest")
        digest = tmp_path / "outbox" / "100001" / "digest-20261025.txt"
        # 当天日期文件存在且含两条
        import datetime as _dt

        digest = tmp_path / "outbox" / "100001" / f"digest-{_dt.date.today():%Y%m%d}.txt"
        assert digest.exists()
        assert digest.read_text(encoding="utf-8").count("【作业】") == 2

    asyncio.run(scenario())


def test_users_are_isolated(tmp_path):
    async def scenario():
        d = FileDeliverer(tmp_path / "outbox")
        await d.deliver("100001", _item(), "instant")
        await d.deliver("100002", _item(), "instant")
        assert (tmp_path / "outbox" / "100001").is_dir()
        assert (tmp_path / "outbox" / "100002").is_dir()

    asyncio.run(scenario())
