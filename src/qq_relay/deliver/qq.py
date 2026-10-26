"""QQ 私聊分发（内部测试通道，ADR-023：不专门维护或专门适配）。

仅用于内部测试期把推送发到自己的 QQ；正式触达走 PushPlus（计划书方案）。
"""

from __future__ import annotations

from typing import Optional

from ..contracts import ClassifiedEvent
from .base import Deliverer, render_push


class DeliverError(Exception):
    pass


class QqDeliverer:
    def __init__(self, server, group_names: Optional[dict[str, str]] = None) -> None:
        self.server = server
        self.group_names = dict(group_names or {})

    async def deliver(self, user_qq: str, item: ClassifiedEvent, kind: str) -> str:
        if self.server is None or self.server._conn is None:
            raise DeliverError("NapCat 未连接（QQ 内部通道不可用）")
        await self.server.call_action(
            "send_private_msg",
            {"user_id": int(user_qq), "message": render_push(item, self.group_names)})
        return f"qq:{user_qq}"


__all__ = ["QqDeliverer", "DeliverError"]
