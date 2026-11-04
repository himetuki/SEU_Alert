"""配置驱动的规则分类器（CLASSIFIER=stub 时使用）。

两份独立配置：
- `config/classification.yml`：本地规则分类树（关键词/优先级/覆盖词/栏目前缀）
- `config/tree.yml`：JEV 分类配置（类别定义、题干、阈值）

评分：标题核心词命中 ×200 + 正文 ×100 + priority；标题命中优先于正文。
公示/名单类标题直接判 notice；新闻/报道类标题也判 notice；栏目前缀
（如【讲座】【国际交流】）可按 `prefix_categories` 直接映射类别。
文件缺失或解析失败时回退内置规则，保证管道可启动。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import yaml

from ..contracts import ClassifiedEvent, RawEvent

CATS = ("homework", "exam", "competition", "research", "exchange",
        "lecture", "task", "notice", "chat")


@dataclass(frozen=True)
class Rule:
    cat: str
    priority: int
    urg: int
    action: str
    keywords: tuple[str, ...]
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    default: tuple[str, int, str]
    notice_markers: tuple[str, ...]
    news_markers: tuple[str, ...]
    prefix_cats: dict[str, str] = field(default_factory=dict)
    source_cats: dict[str, tuple[str, ...]] = field(default_factory=dict)
    group_cats: dict[str, tuple[str, ...]] = field(default_factory=dict)


_FALLBACK_RULES: tuple[Rule, ...] = (
    Rule("homework", 80, 2, "submit",
         ("作业", "习题", "实验报告", "大作业", "提交"),
         ("公示", "名单", "获奖", "评审", "奖学金")),
    Rule("exam", 100, 3, "attend",
         ("考试", "补考", "考点", "考场"), ("公示", "名单", "获奖")),
    Rule("competition", 90, 2, "signup",
         ("竞赛", "大赛", "比赛", "报名"),
         ("公示", "名单", "获奖", "结果")),
    Rule("research", 88, 2, "submit",
         ("SRTP", "大创", "国省创", "立项", "开题", "中期", "结题"),
         ("公示", "名单", "获奖", "结果")),
    Rule("exchange", 86, 2, "signup",
         ("交流", "访学", "交换"), ("公示", "名单", "获奖", "结果")),
    Rule("lecture", 76, 1, "attend",
         ("讲座", "宣讲", "大会", "运动会", "集合"), ("公示", "名单", "获奖")),
    Rule("task", 70, 2, "submit",
         ("填表", "收集", "接龙", "团课", "截图上报"),
         ("公示", "名单", "获奖", "结果")),
    Rule("notice", 10, 1, "know",
         ("停水", "停电", "放假", "缴费", "调课")),
)
_FALLBACK_DEFAULT = ("notice", 1, "know")
_FALLBACK_NOTICE = ("公示", "名单", "获奖", "评奖结果", "评审结果", "评选结果",
                    "通过名单", "拟推荐", "表彰名单", "结果公布")
_FALLBACK_NEWS = ("顺利举办", "成功举办", "举行", "开幕", "启幕", "仪式",
                  "集体备课", "实践研修", "荣获", "称号", "走访", "慰问",
                  "视察", "安全检查", "调研", "工作纪实", "专题报道", "喜报",
                  "入选", "获评", "新进展", "取得进展", "研究进展", "研究成果",
                  "第一名")

_DATE_RE = re.compile(
    r"(\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}|"
    r"本周[一二三四五六末天]|下周[一二三四五六末天]|明天|后天|月底|两周内)"
)
_PREFIX_RE = re.compile(r"【([^】]*)】")

_cache: Optional[tuple[tuple[str, float], RuleSet]] = None


def config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get("CONFIG_DIR", "./config")) / "classification.yml"


def _fallback() -> RuleSet:
    return RuleSet(_FALLBACK_RULES, _FALLBACK_DEFAULT,
                   _FALLBACK_NOTICE, _FALLBACK_NEWS, {})


def load_rules(path: str | Path | None = None) -> RuleSet:
    """读分类配置；按 mtime 缓存；异常时回退内置规则。"""
    global _cache
    p = config_path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return _fallback()
    key = (str(p.resolve()), mtime)
    if _cache and _cache[0] == key:
        return _cache[1]

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return _fallback()

    rules: list[Rule] = []
    for raw in data.get("rules") or []:
        if not isinstance(raw, dict):
            continue
        cat = str(raw.get("cat") or "").strip()
        if cat not in CATS:
            continue
        keywords = tuple(str(x).strip() for x in (raw.get("keywords") or [])
                         if str(x).strip())
        if not keywords:
            continue
        rules.append(Rule(
            cat=cat,
            priority=int(raw.get("priority", 0)),
            urg=int(raw.get("urg", 1)),
            action=str(raw.get("action") or "know"),
            keywords=keywords,
            exclude=tuple(str(x).strip() for x in (raw.get("exclude") or [])
                          if str(x).strip()),
        ))
    if not rules:
        return _fallback()

    fb = data.get("fallback") if isinstance(data.get("fallback"), dict) else {}
    default = (str(fb.get("cat") or "notice"),
               int(fb.get("urg", 1)), str(fb.get("action") or "know"))
    ov = data.get("overrides") if isinstance(data.get("overrides"), dict) else {}
    notice = tuple(str(x).strip() for x in
                   (ov.get("notice_title") or _FALLBACK_NOTICE) if str(x).strip())
    news = tuple(str(x).strip() for x in
                 (ov.get("news_title") or _FALLBACK_NEWS) if str(x).strip())
    prefixes = {str(k).strip(): str(v).strip()
                for k, v in (data.get("prefix_categories") or {}).items()
                if str(k).strip() and str(v).strip() in CATS}

    def _cats(value) -> tuple[str, ...]:
        return tuple(str(x).strip() for x in (value or [])
                     if str(x).strip() in CATS)

    source_cats = {str(k).strip(): _cats(v)
                   for k, v in (data.get("source_categories") or {}).items()
                   if str(k).strip() and _cats(v)}
    group_cats = {str(k).strip(): _cats(v)
                  for k, v in (data.get("group_categories") or {}).items()
                  if str(k).strip() and _cats(v)}
    rs = RuleSet(tuple(rules), default, notice or _FALLBACK_NOTICE,
                 news or _FALLBACK_NEWS, prefixes, source_cats, group_cats)
    _cache = (key, rs)
    return rs


def _rule_for(rs: RuleSet, cat: str) -> Optional[Rule]:
    return next((r for r in rs.rules if r.cat == cat), None)


def classify_text(text: str, ruleset: RuleSet | None = None,
                  title: str | None = None,
                  allow_body: bool = True,
                  allowed: Iterable[str] | None = None) -> tuple[str, int, str, int]:
    """返回 (cat, urg, action, 命中数)。allowed = 来源/频道允许的类别白名单。"""
    rs = ruleset or load_rules()
    allowed_set = set(allowed) if allowed is not None else None

    def ok(cat: str) -> bool:
        return allowed_set is None or cat in allowed_set

    def default() -> tuple[str, int, str]:
        if ok(rs.default[0]):
            return rs.default
        if ok("notice"):
            return "notice", 1, "know"
        return (next(iter(allowed_set), "notice"), 1, "know")

    title = (title if title is not None else text.split("\n", 1)[0]).strip()
    body = text.split("\n", 1)[1] if "\n" in text else ""
    # 去掉标题前缀的【学院/栏目】标记，避免“统计学院/国际学院”污染关键词
    core = re.sub(r"^(?:【[^】]*】\s*)+", "", title).strip() or title
    lt, lb = core.lower(), body.lower()

    if ok("notice"):
        for pat in rs.notice_markers:
            if pat in title:
                return "notice", 1, "know", 1
        if any(p in core for p in rs.news_markers):   # 新闻/报道类
            return "notice", 1, "know", 1

    # 栏目前缀直判（【讲座】【国际交流】【公示】…），不在白名单则跳过
    for token in _PREFIX_RE.findall(title):
        cat = rs.prefix_cats.get(token.strip())
        if cat and ok(cat):
            rule = _rule_for(rs, cat)
            return cat, rule.urg if rule else 1, rule.action if rule else "know", 1

    best_title: Optional[Rule] = None
    best_title_score = 0
    best_body: Optional[Rule] = None
    best_body_score = 0
    hits = 0
    for r in rs.rules:
        if not ok(r.cat):
            continue
        if any(x and x.lower() in lt for x in r.exclude):
            continue
        th = sum(1 for k in r.keywords if k and k.lower() in lt)
        bh = sum(1 for k in r.keywords if k and k.lower() in lb)
        if th:
            score = th * 200 + bh * 100 + r.priority
            if score > best_title_score:
                best_title, best_title_score = r, score
                hits = th + bh
        elif bh and allow_body:
            score = bh * 100 + r.priority
            if score > best_body_score:
                best_body, best_body_score = r, score
                hits = max(hits, bh)
    if best_title is not None:
        return best_title.cat, best_title.urg, best_title.action, hits
    if allow_body and best_body is not None:
        return best_body.cat, best_body.urg, best_body.action, hits
    d = default()
    return d[0], d[1], d[2], 0


def classify_stub(ev: RawEvent, event_id: str,
                  profile_course: str | None = None) -> ClassifiedEvent:
    rs = load_rules()
    title = ev.text.split("\n", 1)[0]
    # 频道白名单优先，其次来源白名单（网站不可能有“作业”）
    allowed = rs.group_cats.get(ev.group_id) or rs.source_cats.get(ev.source)
    # 网页采集的通知：标题足够代表内容，正文常含新闻噪音 → 只看标题
    allow_body = ev.source != "web_crawl"
    cat, urg, action, _ = classify_text(ev.text, rs, title=title,
                                        allow_body=allow_body,
                                        allowed=allowed)
    has_ddl = bool(_DATE_RE.search(ev.text))
    return ClassifiedEvent(
        event_id=event_id,
        groups=[ev.group_id],
        cat=cat,
        cat2=cat,                       # 规则分类器不产次类别
        is_info=1.0,
        urg=urg,
        action=action,
        has_ddl=has_ddl,
        course=profile_course,
        scope=None,
        channel=None,
        stage=None,
        deadline=None,
        deadline_src="none",
        low_conf=False,
        raw_text=ev.text,
        model_calls=["stub"],
    )