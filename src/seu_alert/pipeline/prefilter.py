"""预筛链：发送者过滤 → 内容去重 → 关键词预筛。

**顺序不可反（ADR-008）**：发送者过滤必须排在去重之前。若先去重，被发送者
过滤丢掉的拷贝会先把内容 hash 登记进去重库，同一条通知在其他群的拷贝到达时
会被误判"已见过"直接跳过——过滤造成的丢弃污染去重状态，静默漏报。

去重只登记**通过全链**的消息（由 Runner 在 PASS 后注册），因此：
- A 群拷贝被发送者过滤丢掉 → 不登记 → B 群同内容拷贝仍可正常通过；
- A 群拷贝通过并登记 → B 群同内容拷贝判重（fan-in 挂到同一条 item）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..contracts import RawEvent
from ..config import DEFAULT_GENERIC_WORDS, GroupProfile


class Stage(str, Enum):
    PASS = "pass"
    SENDER_FILTER = "sender_filter"
    DEDUP = "dedup"
    KEYWORD = "keyword"


@dataclass(frozen=True)
class Decision:
    stage: Stage
    passed: bool
    reason: str = ""
    matched: tuple[str, ...] = ()
    content_hash: str = ""
    duplicate_of: Optional[str] = None       # stage=DEDUP 时的首个 event_id
    dry_run_would_drop: bool = False         # dry_run 模式下"本会滤掉"但放行


class Deduper:
    """内容去重：hash → 首次 event_id。重启后从 events 表恢复。"""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def check(self, content_hash: str) -> Optional[str]:
        return self._seen.get(content_hash)

    def register(self, content_hash: str, event_id: str) -> None:
        self._seen.setdefault(content_hash, event_id)

    def load_pairs(self, pairs) -> None:
        for h, eid in pairs:
            self.register(h, eid)


class Prefilter:
    """无状态预筛器（去重状态在 Deduper 里，由 Runner 持有）。"""

    def __init__(self, generic_words: tuple[str, ...] = DEFAULT_GENERIC_WORDS,
                 pass_if_at_all: bool = True) -> None:
        self.generic = tuple(generic_words)
        self.pass_if_at_all = pass_if_at_all
        self.pass_if_at_all = pass_if_at_all

    # ---- 发送者过滤（可选有损，默认 off；四原则见 ADR-007）----

    @staticmethod
    def _sender_ok(ev: RawEvent, profile: GroupProfile) -> tuple[bool, str]:
        sf = profile.sender_filter
        if sf.mode == "off":
            return True, ""
        role = profile.role_of(ev.sender_id)
        if sf.mode == "blacklist":
            if ev.sender_id in sf.blacklist:
                return False, f"黑名单命中 sender={ev.sender_id}"
            if role in sf.roles_deny:
                return False, f"角色黑名单 role={role}"
            return True, ""
        # whitelist
        if ev.sender_id in sf.whitelist:
            return True, f"白名单命中 sender={ev.sender_id}"
        if role in sf.roles_allow:
            return True, f"角色白名单命中 role={role}"
        return False, "不在白名单"

    def process(self, ev: RawEvent, profile: Optional[GroupProfile],
                deduper: Deduper) -> Decision:
        h = ev.content_key()

        # 1) 发送者过滤（不登记 hash——见模块 docstring）
        if profile is not None:
            ok, reason = self._sender_ok(ev, profile)
            if not ok:
                if profile.sender_filter.dry_run:
                    return Decision(Stage.SENDER_FILTER, True,
                                    reason=f"dry_run:{reason}",
                                    content_hash=h, dry_run_would_drop=True)
                return Decision(Stage.SENDER_FILTER, False, reason, content_hash=h)

        # 2) 内容去重（fan-in：判重即挂到已有 item，不重复分类）
        first = deduper.check(h)
        if first is not None:
            return Decision(Stage.DEDUP, False, f"重复于 {first}",
                            content_hash=h, duplicate_of=first)

        # 3) 关键词预筛（通用词 ∪ 画像词）
        words = self.generic + (profile.prefilter if profile else ())
        hit = tuple(w for w in words if w in ev.text)
        if not hit and not (self.pass_if_at_all and ev.at_all):
            return Decision(Stage.KEYWORD, False, "无关键词命中", content_hash=h)

        return Decision(Stage.PASS, True, matched=hit, content_hash=h)
