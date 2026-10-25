"""假分类器：关键词规则 → ClassifiedEvent。

**只用于 P1 打通管道**（不花一次模型调用），P2 被 tree.py（JEV 分类树）替换。
它的误报行为正是验收 A5 的测量对象——灌水消息若通过预筛，会被这里粗规则
打上类别；真分类器上线后以金标准集重新校准。
"""

from __future__ import annotations

import re

from ..contracts import ClassifiedEvent, RawEvent

# (关键词组, cat, urg, action)——首个命中的规则生效
STUB_RULES: list[tuple[tuple[str, ...], str, int, str]] = [
    (("作业", "习题", "实验报告", "大作业", "提交"), "homework", 2, "submit"),
    (("考试", "补考", "考点", "考场"), "exam", 3, "attend"),
    (("竞赛", "大赛", "比赛", "报名"), "competition", 2, "signup"),
    (("SRTP", "大创", "国省创", "立项", "开题", "中期", "结题"), "research", 2, "submit"),
    (("交流", "访学", "交换"), "exchange", 2, "signup"),
    (("讲座", "宣讲", "大会", "运动会", "集合"), "lecture", 1, "attend"),
    (("填表", "收集", "接龙", "团课", "截图上报"), "task", 2, "submit"),
    (("停水", "停电", "放假", "缴费", "调课"), "notice", 1, "know"),
]

_DATE_RE = re.compile(
    r"(\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}|"
    r"本周[一二三四五六末天]|下周[一二三四五六末天]|明天|后天|月底|两周内)"
)


def classify_stub(ev: RawEvent, event_id: str,
                  profile_course: str | None = None) -> ClassifiedEvent:
    cat, urg, action = "notice", 1, "know"
    for words, c, u, a in STUB_RULES:
        if any(w in ev.text for w in words):
            cat, urg, action = c, u, a
            break
    has_ddl = bool(_DATE_RE.search(ev.text))
    return ClassifiedEvent(
        event_id=event_id,
        groups=[ev.group_id],
        cat=cat,
        cat2=cat,                       # 假分类器不产次类别
        is_info=1.0,                    # 假分类器"总是自信"
        urg=urg,
        action=action,
        has_ddl=has_ddl,
        course=profile_course,          # 课程来自群画像绑定（与真分类器同规则）
        scope=None,
        channel=None,
        stage=None,
        deadline=None,                  # 假分类器不做提取；模板显示"见原文"
        deadline_src="none",
        low_conf=False,
        raw_text=ev.text,
        model_calls=["stub"],
    )
