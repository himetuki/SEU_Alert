"""ADR-023 测试：提取栈（分层降级）/ OCR 签名 / PushPlus / 提醒调度 / 投稿端到端 / 核验投票。"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta

import httpx
import pytest

from qq_relay.adapters.user_report import SubmissionIntake
from qq_relay.config import Subscription, SubscriptionsConfig
from qq_relay.contracts import ClassifiedEvent
from qq_relay.deliver.file import FileDeliverer
from qq_relay.deliver.multi import MultiDeliverer
from qq_relay.deliver.pushplus import DeliverError, PushPlusDeliverer
from qq_relay.pipeline.extract_stack import SubmissionExtractor
from qq_relay.pipeline.llm import ChatClient, ChatError
from qq_relay.pipeline.ocr import HttpOcrProvider, XunfeiOcrProvider, xunfei_auth_header
from qq_relay.pipeline.reminder import ReminderScheduler
from qq_relay.pipeline.runner import Runner
from qq_relay.store import db as store_db
from qq_relay.store import queries


# ---------- 假 ChatClient（不发网络，按脚本返回） ----------

class FakeChat:
    def __init__(self, replies: list[str] | None = None, enabled: bool = True):
        self.replies = list(replies or [])
        self.enabled = enabled
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, image_b64=None):
        self.calls.append((system[:20], user[:40]))
        if not self.replies:
            raise ChatError("脚本已用完")
        text = self.replies.pop(0)
        if text.startswith("!"):
            raise ChatError(text[1:])
        from qq_relay.pipeline.llm import ChatResult
        return ChatResult(text=text, model="fake", latency_ms=1)


class TestExtractStack:
    async def _run(self, extractor, **kw):
        return await extractor.extract(**kw)

    def test_text_passthrough_without_models(self):
        ex = SubmissionExtractor()
        r = asyncio.run(self._run(ex, text="高等数学习题册 11月15日截止"))
        assert "11月15日" in r.text and r.low_conf is True
        assert r.chain_used == ()

    def test_big_normalizes(self):
        ex = SubmissionExtractor(big=FakeChat(["高数第五章习题册，11月15日23:59截止，交学习通"]))
        r = asyncio.run(self._run(ex, text="那个...高数作业记得交一下 15号截止哈"))
        assert "习题册" in r.text and "big" in r.chain_used and r.low_conf is False

    def test_small_fallback_when_big_fails(self):
        ex = SubmissionExtractor(big=FakeChat(["!boom"]), small=FakeChat(["整理后的文本"]))
        r = asyncio.run(self._run(ex, text="原始文本"))
        assert r.text == "整理后的文本" and "small" in r.chain_used
        assert "big" not in r.chain_used

    def test_ocr_before_vision(self):
        class FakeOcr:
            enabled = True
            async def image_to_text(self, b64):
                return "OCR 协议转录的文字"
        ex = SubmissionExtractor(vision=FakeChat(["视觉转录"]), ocr=FakeOcr(),
                                 chain=("ocr", "vision", "big", "small"))
        r = asyncio.run(self._run(ex, image_b64="ZmFrZQ=="))
        assert r.text == "OCR 协议转录的文字" and "ocr" in r.chain_used
        assert "vision" not in r.chain_used

    def test_vision_when_ocr_fails(self):
        class FakeOcr:
            enabled = True
            async def image_to_text(self, b64):
                from qq_relay.pipeline.ocr import OcrError
                raise OcrError("挂了")
        ex = SubmissionExtractor(vision=FakeChat(["视觉转录的文字"]), ocr=FakeOcr(),
                                 chain=("ocr", "vision"))
        r = asyncio.run(self._run(ex, image_b64="ZmFrZQ=="))
        assert r.text == "视觉转录的文字" and "vision" in r.chain_used

    def test_image_without_any_layer_low_conf(self):
        ex = SubmissionExtractor()
        r = asyncio.run(self._run(ex, image_b64="ZmFrZQ=="))
        assert r.text == "" and r.low_conf is True


class TestOcr:
    def test_xunfei_signature_deterministic(self):
        h1 = xunfei_auth_header("key", "secret", "api.xf-yun.com",
                                "/v1/private/sf8e6aca1", "Mon, 01 Jan 2026 00:00:00 GMT")
        h2 = xunfei_auth_header("key", "secret", "api.xf-yun.com",
                                "/v1/private/sf8e6aca1", "Mon, 01 Jan 2026 00:00:00 GMT")
        assert h1 == h2 and len(h1) > 40
        raw = base64.b64decode(h1).decode()
        assert 'api_key="key"' in raw and "hmac-sha256" in raw

    def test_http_ocr_parse(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert "image" in body
            return httpx.Response(200, json={"text": "识别文本"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ocr = HttpOcrProvider("https://ocr.example/api", client=client)
        assert asyncio.run(ocr.image_to_text("ZmFrZQ==")) == "识别文本"

    def test_http_ocr_words_result_compat(self):
        def handler(request):
            return httpx.Response(200, json={"words_result": [{"words": "第一行"}, {"words": "第二行"}]})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ocr = HttpOcrProvider("https://ocr.example/api", client=client)
        assert asyncio.run(ocr.image_to_text("x")) == "第一行\n第二行"


class TestPushPlus:
    def _item(self):
        return ClassifiedEvent(event_id="e1", groups=["111"], cat="homework",
                               cat2="homework", is_info=0.9, urg=2, action="submit",
                               has_ddl=True, raw_text="作业 11月15日截止")

    def test_success(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["token"] == "tk"
            return httpx.Response(200, json={"code": 200, "msg": "ok",
                                             "data": {"messageId": "mid-1"}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        d = PushPlusDeliverer(default_token="tk", client=client)
        out = asyncio.run(d.deliver("100001", self._item(), "instant"))
        assert out == "pushplus:mid-1"

    def test_no_token_raises(self):
        d = PushPlusDeliverer(default_token="")
        with pytest.raises(DeliverError):
            asyncio.run(d.deliver("100001", self._item(), "instant"))

    def test_business_error_raises(self):
        def handler(request):
            return httpx.Response(200, json={"code": 500, "msg": "token 错误"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        d = PushPlusDeliverer(default_token="tk", client=client)
        with pytest.raises(DeliverError, match="业务错误"):
            asyncio.run(d.deliver("100001", self._item(), "instant"))


class TestReminder:
    def test_schedule_and_fire(self, tmp_path, settings, groups_cfg):
        """注意：aiosqlite 连接绑死在创建它的事件循环上，全部操作必须在同一个
        asyncio.run 场景内完成（跨 loop 使用会挂起）。"""
        deadline = datetime(2026, 10, 27, 12, 0)
        subs = SubscriptionsConfig(subs={
            "100001": Subscription("100001", ("111",), ("homework",),
                                   quiet=(), instant_min_urg=2, digest=True)})

        async def scenario():
            from qq_relay.contracts import RawEvent

            conn = await store_db.connect(settings)
            await store_db.init_schema(conn)
            try:
                deliverer = FileDeliverer(settings.outbox_dir)
                sched = ReminderScheduler(conn, deliverer, offsets=(24, 3))
                item = ClassifiedEvent(
                    event_id="evt-r", groups=["111"], cat="homework",
                    cat2="homework", is_info=0.9, urg=2, action="submit",
                    has_ddl=True, raw_text="作业：第五章习题册，11月15日截止",
                    deadline=deadline.isoformat(), deadline_src="regex")
                await queries.insert_item(conn, item)

                n = await sched.schedule_for(item, "100001")
                assert n == 2                            # 24h + 3h 两档

                # 距截止 30h：两档都还没到点（fire_at = D-24h > now）
                sched.now_fn = lambda: deadline - timedelta(hours=30)
                assert await sched.tick() == 0
                # 距截止 2h：24h 档与 3h 档同时到期
                sched.now_fn = lambda: deadline - timedelta(hours=2)
                assert await sched.tick() == 2
                assert await sched.tick() == 0           # 不重发
                files = [p.name for p in (settings.outbox_dir / "100001").iterdir()
                         if p.name != "_说明.txt"]
                assert len(files) == 2
            finally:
                await conn.close()

        asyncio.run(scenario())


class TestSubmissionEndToEnd:
    def test_submit_flows_to_outbox(self, tmp_path, settings, groups_cfg):
        async def scenario():
            subs = SubscriptionsConfig(subs={
                "100001": Subscription("100001", ("*all",), ("homework", "notice"),
                                       quiet=(), instant_min_urg=1, digest=True)})
            conn = await store_db.connect(settings)
            await store_db.init_schema(conn)
            runner = Runner(settings, groups_cfg, subs,
                            FileDeliverer(settings.outbox_dir), conn)
            intake = SubmissionIntake(
                extractor=SubmissionExtractor(
                    big=FakeChat(["高等数学第五章习题册作业，11月15日23:59截止，交学习通"])),
                on_notice=lambda ev: runner.handle_event(ev), db=conn)
            sub = await intake.submit(user="100001", course="马原",
                                      text="那个高数作业 15号截止 记得交学习通")
            row = await (await conn.execute(
                "SELECT * FROM submissions WHERE submission_id=?",
                (sub.submission_id,))).fetchone()
            return sub, row
        sub, row = asyncio.run(scenario())
        assert "big" in sub.chain_used
        assert row is not None and row["extracted_text"].startswith("高等数学")
        files = [p.name for p in (settings.outbox_dir / "100001").iterdir()
                 if p.name != "_说明.txt"]
        assert len(files) == 1 and "homework" in files[0]


class TestVotes:
    def test_confirm_report_and_verified(self, tmp_path, settings, groups_cfg):
        from qq_relay.botcmd import handle_private

        async def scenario():
            subs = SubscriptionsConfig(subs={
                "100001": Subscription("100001", ("*all",), ("homework",),
                                       quiet=(), instant_min_urg=1, digest=True)})
            conn = await store_db.connect(settings)
            await store_db.init_schema(conn)
            runner = Runner(settings, groups_cfg, subs,
                            FileDeliverer(settings.outbox_dir), conn)
            item = ClassifiedEvent(event_id="evt-v", groups=["111"], cat="homework",
                                   cat2="homework", is_info=0.9, urg=2, action="submit",
                                   has_ddl=True, raw_text="作业 截止")
            await queries.insert_item(conn, item)
            await queries.insert_delivery(conn, "100001", "evt-v", "file", "p", "instant", 2)
            subs_path = tmp_path / "subscriptions.yml"
            subs_path.write_text("subscriptions: {}\n", encoding="utf-8")
            r1 = await handle_private("100001", "/confirm", groups_cfg, subs,
                                      subs_path, conn)
            r2 = await handle_private("100002", "/confirm evt-v", groups_cfg, subs,
                                      subs_path, conn)
            r3 = await handle_private("100003", "/confirm evt-v", groups_cfg, subs,
                                      subs_path, conn)
            r4 = await handle_private("100004", "/report evt-v 时间改成16号了",
                                      groups_cfg, subs, subs_path, conn)
            counts = await queries.vote_counts(conn, "evt-v")
            row = await queries.get_item(conn, "evt-v")
            return r1, r2, r3, r4, counts, row["verified"]
        r1, r2, r3, r4, counts, verified = asyncio.run(scenario())
        assert "已 +1 确认" in r1 and "已 +1 确认" in r2
        assert "已核验" in r3                       # 第 3 人确认 → 标已核验
        assert "报错" in r4
        assert counts == {"confirm": 3, "report": 1}
        assert verified == 1
