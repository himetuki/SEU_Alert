"""OneBot 11 反向 WebSocket 服务端。

方向说明（与旧稿"客户端"说法的修正）：**NapCat 作为客户端连入我们**，
我们只负责（1）接收事件、（2）在连接存活时提供 action 调用（真实推送期才用）。
断线重连由 NapCat 侧负责；我方 action 调用失败即抛错，由调用方处理。

协议参考：https://github.com/botuniverse/onebot-11
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Callable, Optional
from uuid import uuid4

import websockets

from ..contracts import RawEvent

# OneBot 11 消息段 → 纯文本
def _segment_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    parts: list[str] = []
    for seg in message or []:
        if isinstance(seg, dict) and seg.get("type") == "text":
            parts.append(str((seg.get("data") or {}).get("text", "")))
    return "".join(parts)


def _is_at_all(message: Any) -> bool:
    if isinstance(message, list):
        return any(
            isinstance(s, dict) and s.get("type") == "at" and str((s.get("data") or {}).get("qq")) == "all"
            for s in message
        )
    if isinstance(message, str):
        return "@全体成员" in message or "@everyone" in message
    return False


def parse_group_message(payload: dict) -> Optional[RawEvent]:
    """OneBot 11 群消息事件 → RawEvent；非群消息 / 空文本返回 None。"""
    if payload.get("post_type") != "message":
        return None
    if payload.get("message_type") != "group":
        return None
    sender = payload.get("sender") or {}
    text = _segment_text(payload.get("message"))
    if not text.strip():
        return None
    return RawEvent(
        source="qq_group",
        group_id=str(payload.get("group_id", "")),
        group_name=str(payload.get("group_name") or ""),
        sender_id=str(sender.get("user_id", "")),
        sender_card=str(sender.get("card") or sender.get("nickname") or ""),
        msg_id=str(payload.get("message_id", "")),
        text=text,
        ts=int(payload.get("time") or time.time()),
        at_all=_is_at_all(payload.get("message")),
    )


def _auth_header(ws: Any) -> Optional[str]:
    """兼容 websockets 新旧实现的请求头读取。"""
    req = getattr(ws, "request", None)
    headers = getattr(req, "headers", None)
    if headers is not None:
        return headers.get("Authorization")
    legacy = getattr(ws, "request_headers", None)
    return legacy.get("Authorization") if legacy else None


class OneBotServer:
    """反向 WS 服务端：NapCat 连入 → 事件进队列；action 经同一连接调用。"""

    def __init__(
        self,
        host: str,
        port: int,
        token: str = "",
        on_event: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._token = token
        self._on_event = on_event
        self._queue: asyncio.Queue[RawEvent] = asyncio.Queue()
        self._conn: Any = None                # 当前反向连接（action 出口）
        self._pending: dict[str, asyncio.Future] = {}
        self._server: Any = None
        self.stats = {"connected": 0, "events": 0, "group_msgs": 0}

    async def start(self) -> None:
        self._server = await websockets.serve(self._handler, self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> "OneBotServer":
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    async def _handler(self, ws: Any) -> None:
        if self._token:
            auth = _auth_header(ws)
            if auth != f"Bearer {self._token}":
                await ws.close(code=4001, reason="bad token")
                return
        self.stats["connected"] += 1
        self._conn = ws
        try:
            async for raw in ws:
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(payload, dict):
                    continue
                await self._dispatch(payload)
        except websockets.ConnectionClosed:
            pass
        finally:
            if self._conn is ws:
                self._conn = None

    async def _dispatch(self, payload: dict) -> None:
        echo = payload.get("echo")
        if isinstance(echo, str) and echo in self._pending:
            fut = self._pending.pop(echo)
            if not fut.done():
                fut.set_result(payload)
            return
        self.stats["events"] += 1
        if self._on_event:
            self._on_event(payload)
        ev = parse_group_message(payload)
        if ev is not None:
            self.stats["group_msgs"] += 1
            await self._queue.put(ev)

    async def events(self) -> AsyncIterator[RawEvent]:
        while True:
            yield await self._queue.get()

    async def call_action(self, action: str, params: Optional[dict] = None, timeout: float = 10.0) -> dict:
        """通过当前反向连接调用 OneBot action（真实推送期使用；测试期用不到）。"""
        if self._conn is None:
            raise RuntimeError("OneBot 未连接（NapCat 未连入或已断线）")
        echo = f"act-{uuid4().hex[:12]}"
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        try:
            await self._conn.send(json.dumps(
                {"action": action, "params": params or {}, "echo": echo}, ensure_ascii=False
            ))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(echo, None)
