"""bot 私聊命令（P1）：/sub /unsub /sub list /mute /digest + 负反馈。

订阅权威源是 config/subscriptions.yml；P1 直接原子写（P3 收敛进单一
配置管理器，ADR-018）。中文类别别名见 docs/config.md。
"""

from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from .config import GroupsConfig, Subscription, SubscriptionsConfig
from .store import queries
from .yamlio import atomic_write_yaml

CAT_ALIASES: dict[str, tuple[str, ...]] = {
    "活动": ("lecture", "task"), "通知": ("notice", "task"), "考试": ("exam",),
    "作业": ("homework",), "科研": ("research", "competition"), "讲座": ("lecture",),
    "竞赛": ("competition",), "交流": ("exchange",), "访学": ("exchange",),
    "任务": ("task",),
}

_USAGE = (
    "用法：\n"
    "/sub 群 <群名|all> 类别 <活动 通知 …>   订阅（如 /sub 群 年级大群 类别 活动 通知）\n"
    "/sub list        查看当前订阅\n"
    "/unsub           清空订阅\n"
    "/mute 23:00-07:00  设免打扰\n"
    "/digest on|off   摘要开关"
)


def _resolve_group(groups: GroupsConfig, name_or_id: str) -> str | None:
    for gid, g in groups.groups.items():
        if gid == name_or_id or g.name == name_or_id:
            return gid
    return None


def _expand_cats(words: list[str]) -> list[str]:
    cats: list[str] = []
    for w in words:
        for c in CAT_ALIASES.get(w, ()):
            if c not in cats:
                cats.append(c)
    return cats


def _save(subs_cfg: SubscriptionsConfig, subs_path: Path) -> None:
    data = {"subscriptions": {
        qq: {
            "groups": list(s.groups),
            "cats": list(s.cats),
            **({"keywords": {"inc": list(s.inc), "exc": list(s.exc)}} if (s.inc or s.exc) else {}),
            **({"quiet": list(s.quiet)} if s.quiet else {}),
            "instant_min_urg": s.instant_min_urg,
            "digest": s.digest,
        } for qq, s in subs_cfg.subs.items()
    }}
    atomic_write_yaml(subs_path, data)


async def handle_private(user_qq: str, text: str, groups: GroupsConfig,
                         subs_cfg: SubscriptionsConfig, subs_path: Path,
                         db: aiosqlite.Connection) -> str:
    """处理一条私聊；返回回复文本（空字符串 = 不回复）。"""
    t = text.strip()

    if not t.startswith("/"):
        if any(k in t for k in ("不感兴趣", "别推", "太吵", "错了")):
            await queries.insert_label(db, None, "feedback", None, t)
            return "已记录负反馈，会进标注集用于调阈值（测试期感谢！）"
        return ""

    parts = t.split()
    cmd = parts[0].lower()

    if cmd == "/sub" and len(parts) >= 2 and parts[1] == "list":
        s = subs_cfg.subs.get(user_qq)
        if s is None:
            return "当前无订阅。发送 /sub 群 <群名|all> 类别 <类别…> 订阅。"
        return (f"当前订阅：\n群：{'、'.join(s.groups) or '（空）'}\n"
                f"类别：{'、'.join(s.cats) or '（空）'}\n"
                f"免打扰：{'、'.join(s.quiet) or '无'}\nDigest：{'开' if s.digest else '关'}")

    if cmd == "/unsub":
        subs_cfg.subs.pop(user_qq, None)
        _save(subs_cfg, subs_path)
        return "已清空订阅。"

    if cmd == "/sub":
        m = re.match(r"/sub\s+群\s+(\S+)\s+类别\s+(.+)", t)
        if not m:
            return _USAGE
        gname, cat_words = m.group(1), m.group(2).split()
        if gname in ("all", "全部"):
            gids = ["*all"]
        else:
            gid = _resolve_group(groups, gname)
            if gid is None:
                return f"没找到群「{gname}」。bot 可见的群：{'、'.join(g.name or g.group_id for g in groups.groups.values()) or '（尚未配置画像）'}"
            gids = [gid]
        cats = _expand_cats(cat_words)
        if not cats:
            return f"没识别出类别。可用：{'、'.join(CAT_ALIASES)}"
        old = subs_cfg.subs.get(user_qq)
        subs_cfg.subs[user_qq] = Subscription(
            user_qq=user_qq, groups=tuple(gids), cats=tuple(cats),
            inc=old.inc if old else (), exc=old.exc if old else (),
            quiet=old.quiet if old else ("23:00-07:00",),
            instant_min_urg=old.instant_min_urg if old else 2,
            digest=old.digest if old else True,
        )
        _save(subs_cfg, subs_path)
        return f"订阅成功：群 {'、'.join(gids)} × 类别 {'、'.join(cats)}"

    if cmd == "/mute" and len(parts) >= 2:
        s = subs_cfg.subs.get(user_qq)
        if s is None:
            return "先 /sub 订阅再设免打扰。"
        subs_cfg.subs[user_qq] = Subscription(
            user_qq=s.user_qq, groups=s.groups, cats=s.cats, inc=s.inc, exc=s.exc,
            quiet=(parts[1],), instant_min_urg=s.instant_min_urg, digest=s.digest)
        _save(subs_cfg, subs_path)
        return f"免打扰已设为 {parts[1]}"

    if cmd == "/digest" and len(parts) >= 2 and parts[1].lower() in ("on", "off"):
        s = subs_cfg.subs.get(user_qq)
        if s is None:
            return "先 /sub 订阅再设 Digest。"
        on = parts[1].lower() == "on"
        subs_cfg.subs[user_qq] = Subscription(
            user_qq=s.user_qq, groups=s.groups, cats=s.cats, inc=s.inc, exc=s.exc,
            quiet=s.quiet, instant_min_urg=s.instant_min_urg, digest=on)
        _save(subs_cfg, subs_path)
        return f"Digest 已{'开启' if on else '关闭'}"

    return _USAGE
