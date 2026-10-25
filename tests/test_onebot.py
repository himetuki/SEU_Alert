"""OneBot 事件解析 + 反向 WS 服务端集成测试（P0）。

服务端测试不起 NapCat：用 websockets 客户端伪装 NapCat 连入、发合成事件，
验证"反向 WS → RawEvent 队列"这条根基石通路（ NapCat 接入前就能自检）。
"""

from __future__ import annotations

import asyncio
import json

from qq_relay.adapters.onebot import OneBotServer, parse_group_message
from qq_relay.contracts import RawEvent

GROUP_MSG = {
    "post_type": "message",
    "message_type": "group",
    "time": 1761360000,
    "self_id": 100000,
    "group_id": 123456789,
    "group_name": "马原群",
    "message_id": 778899,
    "sender": {"user_id": 10001, "nickname": "小王", "card": "王老师"},
    "message": [
        {"type": "at", "data": {"qq": "all"}},
        {"type": "text", "data": {"text": "第五章习题册作业已发布，11月15日23:59前交学习通"}},
    ],
    "raw_message": "@全体成员 第五章习题册作业已发布，11月15日23:59前交学习通",
}

PRIVATE_MSG = {**GROUP_MSG, "message_type": "private", "group_id": None, "group_name": None}
NOTICE = {"post_type": "notice", "notice_type": "group_increase", "group_id": 123456789}
EMPTY_MSG = {**GROUP_MSG, "message": [{"type": "image", "data": {"file": "x.jpg"}}]}


class TestParseGroupMessage:
    def test_group_message(self):
        ev = parse_group_message(GROUP_MSG)
        assert isinstance(ev, RawEvent)
        assert ev.group_id == "123456789"
        assert ev.sender_card == "王老师"
        assert ev.at_all is True
        assert "习题册" in ev.text
        assert ev.source == "qq_group"

    def test_private_ignored(self):
        assert parse_group_message(PRIVATE_MSG) is None

    def test_notice_ignored(self):
        assert parse_group_message(NOTICE) is None

    def test_empty_text_ignored(self):
        assert parse_group_message(EMPTY_MSG) is None

    def test_string_message_format(self):
        payload = {**GROUP_MSG, "message": "@全体成员  plain text 格式"}
        ev = parse_group_message(payload)
        assert ev is not None and ev.at_all is True and "plain text" in ev.text

    def test_string_message_without_at_all(self):
        payload = {**GROUP_MSG, "message": "普通消息"}
        assert parse_group_message(payload).at_all is False


def _run(coro):
    return asyncio.run(coro)


class TestOneBotServer:
    def test_reverse_ws_delivers_raw_event(self):
        async def scenario():
            srv = OneBotServer("127.0.0.1", 0)
            await srv.start()
            port = srv._server.sockets[0].getsockname()[1]
            try:
                import websockets

                async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                    await ws.send(json.dumps(GROUP_MSG, ensure_ascii=False))
                    ev = await asyncio.wait_for(srv._queue.get(), timeout=3)
                    assert ev.group_id == "123456789"
                    assert srv.stats["group_msgs"] == 1
            finally:
                await srv.stop()

        _run(scenario())

    def test_bad_token_rejected(self):
        async def scenario():
            srv = OneBotServer("127.0.0.1", 0, token="secret")
            await srv.start()
            port = srv._server.sockets[0].getsockname()[1]
            try:
                import websockets

                # 无 token → 服务端关闭连接
                try:
                    async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
                        await ws.send(json.dumps(GROUP_MSG))
                        await asyncio.wait_for(ws.recv(), timeout=3)
                    raise AssertionError("应当被拒绝")
                except Exception:
                    pass
                assert srv.stats["group_msgs"] == 0

                # 带正确 token → 放行
                async with websockets.connect(
                    f"ws://127.0.0.1:{port}", additional_headers={"Authorization": "Bearer secret"}
                ) as ws:
                    await ws.send(json.dumps(GROUP_MSG, ensure_ascii=False))
                    ev = await asyncio.wait_for(srv._queue.get(), timeout=3)
                    assert ev.sender_card == "王老师"
            finally:
                await srv.stop()

        _run(scenario())

    def test_action_without_connection_raises(self):
        async def scenario():
            srv = OneBotServer("127.0.0.1", 0)
            await srv.start()
            try:
                try:
                    await srv.call_action("get_status")
                    raise AssertionError("应当抛 RuntimeError")
                except RuntimeError:
                    pass
            finally:
                await srv.stop()

        _run(scenario())
