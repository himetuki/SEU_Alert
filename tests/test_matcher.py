"""订阅匹配测试：群 × cat/cat2 × 关键词 × 免打扰 × 路由。"""

from __future__ import annotations

from datetime import datetime

from qq_relay.config import Subscription
from qq_relay.contracts import ClassifiedEvent
from qq_relay.pipeline.matcher import _in_quiet, match

NOW = datetime(2026, 10, 25, 14, 0)          # 下午两点，非免打扰
NIGHT = datetime(2026, 10, 25, 23, 30)       # 免打扰时段内


def _item(groups=("111",), cat="homework", cat2="homework", urg=2,
          text="高等数学作业 11月15日截止") -> ClassifiedEvent:
    return ClassifiedEvent(
        event_id="e1", groups=list(groups), cat=cat, cat2=cat2,
        is_info=0.9, urg=urg, action="submit", has_ddl=True, raw_text=text)


def _sub(groups=("111",), cats=("homework",), quiet=(), min_urg=2, digest=True) -> Subscription:
    return Subscription(user_qq="u", groups=tuple(groups), cats=tuple(cats),
                        quiet=tuple(quiet), instant_min_urg=min_urg, digest=digest)


class TestGroupAxis:
    def test_hit(self):
        assert match(_sub(groups=("111",)), _item(groups=("111",)), NOW) is not None

    def test_star_all(self):
        assert match(_sub(groups=("*all",)), _item(groups=("999",)), NOW) is not None

    def test_miss(self):
        assert match(_sub(groups=("222",)), _item(groups=("111",)), NOW) is None

    def test_fan_in_any_group_hits(self):
        """fan-in 后 item.groups 多群，订阅任一群即中。"""
        assert match(_sub(groups=("222",)), _item(groups=("111", "222")), NOW) is not None


class TestCatAxis:
    def test_cat_hit(self):
        assert match(_sub(cats=("homework",)), _item(cat="homework"), NOW) is not None

    def test_cat2_hit_or_semantics(self):
        """cat 不中但 cat2 中 → OR 语义命中。"""
        assert match(_sub(cats=("homework",)),
                     _item(cat="notice", cat2="homework"), NOW) is not None

    def test_miss(self):
        assert match(_sub(cats=("exam",)), _item(cat="homework"), NOW) is None

    def test_empty_cats_never_matches(self):
        assert match(_sub(cats=()), _item(), NOW) is None


class TestKeywords:
    def test_exc_blocks(self):
        s = _sub()
        s = Subscription(s.user_qq, s.groups, s.cats, exc=("推销",), quiet=s.quiet,
                         instant_min_urg=s.instant_min_urg, digest=s.digest)
        assert match(s, _item(text="作业通知 顺便推销一波"), NOW) is None

    def test_inc_requires_hit(self):
        s = Subscription("u", ("111",), ("homework",), inc=("大创",), quiet=(),
                         instant_min_urg=2, digest=True)
        assert match(s, _item(text="普通作业"), NOW) is None
        assert match(s, _item(text="大创项目作业"), NOW) is not None


class TestRouting:
    def test_instant_when_urg_high(self):
        m = match(_sub(min_urg=2), _item(urg=2), NOW)
        assert m is not None and m.kind == "instant"

    def test_digest_when_urg_low(self):
        m = match(_sub(min_urg=2), _item(urg=1), NOW)
        assert m is not None and m.kind == "digest"

    def test_quiet_forces_digest(self):
        m = match(_sub(quiet=("23:00-07:00",)), _item(urg=3), NIGHT)
        assert m is not None and m.kind == "digest"

    def test_quiet_with_digest_off_blocks(self):
        s = _sub(quiet=("23:00-07:00",), digest=False)
        assert match(s, _item(urg=3), NIGHT) is None

    def test_in_quiet_crosses_midnight(self):
        assert _in_quiet(NIGHT, ("23:00-07:00",)) is True
        assert _in_quiet(datetime(2026, 10, 25, 3, 0), ("23:00-07:00",)) is True
        assert _in_quiet(NOW, ("23:00-07:00",)) is False
