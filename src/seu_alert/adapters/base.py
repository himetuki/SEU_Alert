"""采集适配器协议：后续爬虫 / 用户转发上报都实现同一接口，输出 RawEvent。"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from ..contracts import RawEvent


class Adapter(Protocol):
    """采集源协议。events() 产出归一后的 RawEvent 流。"""

    name: str

    async def events(self) -> AsyncIterator[RawEvent]: ...
