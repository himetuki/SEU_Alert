"""规则分类器：标题优先、来源白名单、前缀直判、公示/新闻覆盖。"""

from __future__ import annotations

from pathlib import Path

import pytest

from seu_alert.contracts import RawEvent
from seu_alert.pipeline import classifier_stub as cs

CFG = """\
rules:
  - cat: homework
    priority: 80
    urg: 2
    action: submit
    keywords: [作业, 提交]
  - cat: competition
    priority: 90
    urg: 2
    action: signup
    keywords: [竞赛, 数学建模]
  - cat: lecture
    priority: 76
    urg: 1
    action: attend
    keywords: [讲座]
  - cat: task
    priority: 70
    urg: 2
    action: submit
    keywords: [报名, 申请]
  - cat: notice
    priority: 10
    urg: 1
    action: know
    keywords: [通知, 安排]
overrides:
  notice_title: [公示, 名单]
  news_title: [顺利举办, 荣获]
prefix_categories:
  讲座: lecture
  公示: notice
source_categories:
  web_crawl: [notice, competition, lecture, task]
  qq_group: [homework, competition, lecture, task, notice]
group_categories:
  web-lecture: [lecture, task, notice]
fallback: {cat: notice, urg: 1, action: know}
"""


@pytest.fixture
def rs(tmp_path, monkeypatch):
    p = tmp_path / "classification.yml"
    p.write_text(CFG, encoding="utf-8")
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    cs._cache = None
    return cs.load_rules(p)


def test_web_crawl_never_homework(rs):
    # 网站来源白名单没有 homework → 即使标题写着“作业提交”也降级为 notice
    cat = cs.classify_text("关于作业提交的通知", rs, allow_body=False,
                           allowed=rs.source_cats["web_crawl"])[0]
    assert cat == "notice"


def test_qq_group_can_homework(rs):
    cat = cs.classify_text("高数作业提交", rs, allow_body=False,
                           allowed=rs.source_cats["qq_group"])[0]
    assert cat == "homework"


def test_group_whitelist_overrides_source(rs):
    # web-lecture 只允许 lecture/task/notice
    cat = cs.classify_text("数学建模竞赛报名", rs, allow_body=False,
                           allowed=rs.group_cats["web-lecture"])[0]
    assert cat in ("task", "lecture", "notice")
    assert cat != "competition"


def test_prefix_category(rs):
    assert cs.classify_text("【讲座】文化素质教育学分解答", rs,
                            allow_body=False)[0] == "lecture"


def test_notice_override(rs):
    assert cs.classify_text("2026年奖学金获奖名单公示", rs,
                            allow_body=False)[0] == "notice"


def test_news_override(rs):
    assert cs.classify_text("我院团队荣获全国一等奖", rs,
                            allow_body=False)[0] == "notice"


def test_body_only_ignored(rs):
    text = "关于本周事项\n请完成作业并提交"
    assert cs.classify_text(text, rs, allow_body=False)[0] == "notice"
    assert cs.classify_text(text, rs, allow_body=True)[0] == "homework"


def test_classify_stub_uses_source_whitelist(rs, monkeypatch):
    monkeypatch.setattr(cs, "load_rules", lambda *a, **k: rs)

    def ev(source: str, group: str) -> RawEvent:
        return RawEvent(source=source, group_id=group, group_name=group,
                        sender_id="s", sender_card="s", msg_id="m",
                        text="高数作业提交", ts=0)

    assert cs.classify_stub(ev("web_crawl", "web-jwc"), "e1").cat == "notice"
    assert cs.classify_stub(ev("qq_group", "123456"), "e2").cat == "homework"