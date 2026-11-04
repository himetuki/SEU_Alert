"""多出口分发（ADR-023）：按 DELIVER_MODE 组合（如 file,pushplus）。

file 是测试期留档（总是可见），pushplus 是真实微信触达。任一出口失败不影响
其余，全部失败才抛错；返回首个成功落点写 deliveries.path。
"""

from __future__ import annotations

from ..contracts import ClassifiedEvent
from .base import Deliverer


class MultiDeliverer:
    def __init__(self, deliverers: dict[str, Deliverer]) -> None:
        if not deliverers:
            raise ValueError("MultiDeliverer 至少需要一个出口")
        self.deliverers = dict(deliverers)

    async def deliver(self, user_qq: str, item: ClassifiedEvent, kind: str) -> str:
        errors: list[str] = []
        first_ok: str | None = None
        for mode, d in self.deliverers.items():
            try:
                path = await d.deliver(user_qq, item, kind)
                if first_ok is None:
                    first_ok = f"{mode}:{path}"
            except Exception as e:                     # 单出口失败不拖垮整体
                errors.append(f"{mode}: {e!r}")
        if first_ok is None:
            raise RuntimeError(f"全部分发失败: {errors}")
        return first_ok
