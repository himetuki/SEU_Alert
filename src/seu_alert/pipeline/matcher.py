"""订阅匹配：群 × cat/cat2 × 关键词 × 免打扰 → instant | digest | 不匹配。

语义（docs/config.md）：
- 群：`*all` 或 ClassifiedEvent.groups 与订阅群有交集（fan-in 后多群命中即中）
- 类别：cat 或 cat2 命中即中（OR）；cats 为空 = 不收任何类别
- 关键词：exc 命中即拒；inc 非空且无一命中即拒
- 路由：免打扰时段 → digest（digest=false 则不投）；否则 urg ≥ instant_min_urg → instant
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from ..config import Subscription
from ..contracts import ClassifiedEvent


@dataclass(frozen=True)
class Match:
    user_qq: str
    kind: str                # instant | digest
    reason: str = ""


def _parse_hm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


def _in_quiet(now: datetime, quiet: tuple[str, ...]) -> bool:
    t = now.time()
    for rng in quiet:
        try:
            start_s, end_s = rng.split("-")
            start, end = _parse_hm(start_s), _parse_hm(end_s)
        except (ValueError, AttributeError):
            continue
        if start <= end:
            if start <= t < end:
                return True
        elif t >= start or t < end:      # 跨午夜，如 23:00-07:00
            return True
    return False


def match(sub: Subscription, item: ClassifiedEvent, now: datetime) -> Match | None:
    # 群维度
    if "*all" not in sub.groups and not (set(item.groups) & set(sub.groups)):
        return None
    # 类别维度（OR 语义；空 cats = 不收）
    if item.cat not in sub.cats and item.cat2 not in sub.cats:
        return None
    # 关键词维度
    if any(w in item.raw_text for w in sub.exc):
        return None
    if sub.inc and not any(w in item.raw_text for w in sub.inc):
        return None
    # 路由
    if _in_quiet(now, sub.quiet):
        return Match(sub.user_qq, "digest", "免打扰时段") if sub.digest else None
    if item.urg >= sub.instant_min_urg:
        return Match(sub.user_qq, "instant", f"urg {item.urg}≥{sub.instant_min_urg}")
    return Match(sub.user_qq, "digest", "低紧急度") if sub.digest else None


def match_all(subs, item: ClassifiedEvent, now: datetime) -> list[Match]:
    return [m for s in subs if (m := match(s, item, now)) is not None]
