"""分发器协议 + 推送文案模板。

模板是 QQ 推送与文件分发共用的——测试期文件分发验证的就是将来真实推送的
同一套文案（ADR-021）。
"""

from __future__ import annotations

from typing import Protocol

from ..contracts import ClassifiedEvent

CAT_ZH = {
    "homework": "作业", "exam": "考试", "competition": "竞赛", "research": "科研",
    "exchange": "国际交流", "lecture": "讲座活动", "task": "事务任务",
    "notice": "通知", "chat": "闲聊",
}
ACTION_ZH = {"submit": "需要提交", "signup": "需要报名", "attend": "需要出席", "know": "仅需知晓"}

_RAW_MAX = 300


def render_push(item: ClassifiedEvent) -> str:
    cat_zh = CAT_ZH.get(item.cat, item.cat)
    title = f"{cat_zh}" if item.cat2 == item.cat else f"{cat_zh}+{CAT_ZH.get(item.cat2, item.cat2)}"
    lines = [
        f"【{title}】 紧急度 {item.urg}/3 · {ACTION_ZH.get(item.action, item.action)}",
        f"课程：{item.course or '—'}    截止：{item.deadline or '见原文'}    渠道：{item.channel or '—'}",
        f"来源群：{'、'.join(item.groups)}",
        "─" * 46,
        item.raw_text[:_RAW_MAX] + ("…" if len(item.raw_text) > _RAW_MAX else ""),
        "─" * 46,
        f"（测试期文件分发 · 非真实推送 · 事件 {item.event_id[:8]}"
        + (" · 低置信待复核" if item.low_conf else "") + "）",
    ]
    return "\n".join(lines)


class Deliverer(Protocol):
    async def deliver(self, user_qq: str, item: ClassifiedEvent, kind: str) -> str:
        """分发一条推送，返回落点（文件路径 / 消息 ID）。"""
        ...
