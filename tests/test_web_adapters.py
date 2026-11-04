"""Web 采集适配器测试：SEU-Monitor / SEUdaily 输出库扫描、增量去重、端到端入管道。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from seu_alert.adapters.web import SCANNERS, WebPoller, WebSource
from seu_alert.adapters.web.seu_monitor import scan as scan_monitor
from seu_alert.adapters.web.seudaily import scan as scan_seudaily

SHA = "a" * 64


def _mk_monitor_notice(root: Path, column: str, slug: str,
                       title: str = "关于2026年秋季学期选课的通知",
                       date: str = "2026-09-12 08:00:00") -> None:
    d = root / "web" / "教务处" / column / f"{title}--{slug}"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "site_id": "jwc", "column_id": "gjjl", "notice_id": slug,
        "title": title, "url": "https://jwc.seu.edu.cn/gjjl/list.htm",
        "date": date, "fetched_at": "2026-09-12T09:00:00+08:00",
        "html_sha256": "x", "text_sha256": "y", "content_version": 1,
        "attachments": [],
    }, ensure_ascii=False), encoding="utf-8")
    (d / "text.md").write_text(
        f"# {title}\n\n来源：https://jwc.seu.edu.cn/2026/0912/c{slug}/page.htm\n\n"
        "请同学们于9月20日前完成选课。\n", encoding="utf-8")


def _mk_seudaily_notice(root: Path, sha: str = SHA) -> None:
    (root / "metadata").mkdir(parents=True)
    (root / "files" / "cse.seu.edu.cn" / "undergraduate_notices"
     / "seu-cse-582946").mkdir(parents=True)
    md = (root / "files" / "cse.seu.edu.cn" / "undergraduate_notices"
          / "seu-cse-582946" / f"{sha}.md")
    md.write_text("# 关于学院拟推荐免试攻读研究生名单的公示\n\n"
                  "来源：https://cse.seu.edu.cn/2026/0912/c49469a582946/page.htm\n\n"
                  "现将拟推荐名单进行公示。\n", encoding="utf-8")
    (root / "metadata" / f"{sha}.json").write_text(json.dumps({
        "url": "https://cse.seu.edu.cn/2026/0912/c49469a582946/page.htm",
        "name": "关于学院拟推荐免试攻读研究生名单的公示.md",
        "sha256": sha, "sizeBytes": 269,
        "sourceUrl": "https://cse.seu.edu.cn/2026/0912/c49469a582946/page.htm",
        "source": {"id": "cse.seu.edu.cn", "name": "计软智学院"},
        "notice": {"id": "seu-cse-582946",
                   "title": "关于学院拟推荐免试攻读研究生名单的公示",
                   "url": "https://cse.seu.edu.cn/2026/0912/c49469a582946/page.htm"},
        "sectionId": "undergraduate_notices",
    }, ensure_ascii=False), encoding="utf-8")


class TestSeuMonitorScan:
    def test_scan_notice(self, tmp_path):
        _mk_monitor_notice(tmp_path, "国际交流", "12345")
        out = scan_monitor(tmp_path)
        assert len(out) == 1
        n = out[0]
        assert n.group_id == "web-jwc"
        assert n.group_name.startswith("教务处")
        assert "选课" in n.title
        assert "【国际交流】" in n.text and "9月20日" in n.text
        assert n.sender == "东南大学教务处"
        assert n.ts == int(time.mktime(time.strptime("2026-09-12 08:00:00", "%Y-%m-%d %H:%M:%S")))

    def test_missing_root_returns_empty(self, tmp_path):
        assert scan_monitor(tmp_path / "nonexistent") == []

    def test_bad_meta_skipped(self, tmp_path):
        d = tmp_path / "web" / "教务处" / "教务信息" / "坏通知--1"
        d.mkdir(parents=True)
        (d / "meta.json").write_text("not json", encoding="utf-8")
        assert scan_monitor(tmp_path) == []


class TestSeudailyScan:
    def test_scan_notice(self, tmp_path):
        _mk_seudaily_notice(tmp_path)
        out = scan_seudaily(tmp_path)
        assert len(out) == 1
        n = out[0]
        assert n.group_id == "web-cse"
        assert n.group_name == "计软智学院"
        assert "免试" in n.title
        assert "公示" in n.text
        assert n.url.endswith("page.htm")

    def test_missing_root_returns_empty(self, tmp_path):
        assert scan_seudaily(tmp_path / "nonexistent") == []


class TestWebPoller:
    def test_backfill_then_incremental(self, tmp_path):
        async def scenario():
            _mk_monitor_notice(tmp_path, "国际交流", "1")
            got: list = []
            poller = WebPoller(
                source=WebSource(id="t", kind="seu_monitor", name="t",
                                 root=tmp_path, interval=60),
                scanner=scan_monitor, seen=set(),
                on_notice=lambda ev: got.append(ev),
                mark_seen=lambda k: asyncio.sleep(0),
            )
            assert await poller.poll_once() == 1          # backfill
            assert await poller.poll_once() == 0          # 已见不重发
            _mk_monitor_notice(tmp_path, "教务信息", "2")
            assert await poller.poll_once() == 1          # 增量
            assert len(got) == 2
            assert got[0].source == "web_crawl"
            assert got[0].group_id == "web-jwc"

        asyncio.run(scenario())


class TestWebIntoPipeline:
    """端到端：web 通知 → 预筛 → 假分类器 → 匹配 → outbox 文件。"""

    def test_web_notice_reaches_outbox(self, tmp_path, settings, groups_cfg):
        from seu_alert.config import Subscription, SubscriptionsConfig
        from seu_alert.deliver.file import FileDeliverer
        from seu_alert.pipeline.runner import Runner
        from seu_alert.store import db as store_db

        async def scenario():
            web_root = tmp_path / "webroot"
            _mk_seudaily_notice(web_root)
            subs = SubscriptionsConfig(subs={
                "100001": Subscription("100001", ("web-cse",), ("notice", "task"),
                                       quiet=(), instant_min_urg=2, digest=True)})
            conn = await store_db.connect(settings)
            await store_db.init_schema(conn)
            deliverer = FileDeliverer(settings.outbox_dir,
                                      group_names={"web-cse": "计软智学院（cse.seu.edu.cn）"})
            runner = Runner(settings, groups_cfg, subs, deliverer, conn)
            await runner.restore_dedup()
            try:
                got: list = []
                poller = WebPoller(
                    source=WebSource(id="seudaily", kind="seudaily", name="d",
                                     root=web_root, interval=60),
                    scanner=scan_seudaily, seen=set(),
                    on_notice=lambda ev: runner.handle_event(ev),
                    mark_seen=lambda k: asyncio.sleep(0),
                )
                await poller.poll_once()
            finally:
                await conn.close()
            user_dir = settings.outbox_dir / "100001"
            files = [p for p in user_dir.iterdir() if p.name != "_说明.txt"]
            assert len(files) == 1
            content = files[0].read_text(encoding="utf-8")
            assert "【undergraduate_notices】" in content
            assert "计软智学院" in content
            assert "免试" in content

        asyncio.run(scenario())
