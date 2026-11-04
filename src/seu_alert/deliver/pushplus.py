"""PushPlus 微信强推送（ADR-023）。

每用户 token 由用户在看板绑定一次（存 users.pushplus_token）；无 token 时抛
DeliverError，由 MultiDeliverer 决定兜底（测试期 file 留档）。
"""

from __future__ import annotations

import inspect
from typing import Callable, Optional

import httpx

from ..contracts import ClassifiedEvent
from .base import Deliverer, render_push

PUSHPLUS_URL = "https://www.pushplus.plus/send"


class DeliverError(Exception):
    pass


class PushPlusDeliverer:
    def __init__(self, default_token: str = "", topic: str = "",
                 token_of: Optional[Callable[[str], str]] = None,
                 group_names: Optional[dict[str, str]] = None,
                 client: Optional[httpx.AsyncClient] = None) -> None:
        self.default_token = default_token
        self.topic = topic
        self.token_of = token_of or (lambda _qq: "")
        self.group_names = dict(group_names or {})
        self._client = client

    async def _ac(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    def _title(self, item: ClassifiedEvent, kind: str) -> str:
        from .base import CAT_ZH, ACTION_ZH

        tag = "【提醒】" if kind == "reminder" else ""
        return f"{tag}{CAT_ZH.get(item.cat, item.cat)}·{ACTION_ZH.get(item.action, item.action)}"

    async def deliver(self, user_qq: str, item: ClassifiedEvent, kind: str) -> str:
        token = self.token_of(user_qq)
        if inspect.isawaitable(token):        # 允许异步查 users 表
            token = await token
        token = token or self.default_token
        if not token:
            raise DeliverError(f"用户 {user_qq} 未绑定 PushPlus token")
        payload: dict[str, object] = {
            "token": token,
            "title": self._title(item, kind)[:95],
            "content": render_push(item, self.group_names),
            "template": "markdown",
        }
        if self.topic:
            payload["topic"] = self.topic
        client = await self._ac()
        try:
            resp = await client.post(PUSHPLUS_URL, json=payload)
        except httpx.HTTPError as e:
            raise DeliverError(f"PushPlus 网络错误: {e!r}") from e
        if resp.status_code != 200:
            raise DeliverError(f"PushPlus HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise DeliverError(f"PushPlus 响应非 JSON: {resp.text[:200]}") from e
        if int(data.get("code", -1)) != 200:
            raise DeliverError(f"PushPlus 业务错误: {data.get('msg')}")
        return f"pushplus:{(data.get('data') or {}).get('messageId', '')}"
