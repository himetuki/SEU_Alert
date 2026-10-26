"""数据契约：全管道唯一的事件结构。

改契约 = 改这里，且必须先改 docs/architecture.md 再改代码（项目约定）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RawEvent:
    """所有采集源（QQ群/爬虫/用户上报）归一后的入口结构。"""

    source: str                      # qq_group | web_crawl | user_report
    group_id: str
    group_name: str
    sender_id: str
    sender_card: str
    msg_id: str
    text: str
    ts: int
    at_all: bool = False
    hints: dict = field(default_factory=dict)   # 提取层预填字段（course/deadline/channel），Runner 分类后合并

    def content_key(self) -> str:
        """去重键：同一条通知在多个群转发只判一次（群不参与，sender 不参与）。"""
        import hashlib

        norm = "".join(self.text.split())
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()


@dataclass
class ClassifiedEvent:
    """分类树输出（分类器契约，与模型实现解耦）。"""

    event_id: str
    groups: list[str]                 # 去重 fan-in：所有来源群，任一命中订阅即推
    cat: str                          # 9 类之一
    cat2: str                         # 次类别，可与 cat 相同 = 无
    is_info: float
    urg: int                          # 0-3
    action: str                       # submit | signup | attend | know
    has_ddl: bool
    course: Optional[str] = None      # 画像绑定或提取
    scope: Optional[str] = None       # course | grade | class | school
    channel: Optional[str] = None     # chaoxing | yuketang | email | offline | other
    stage: Optional[str] = None       # research 类：立项/选题/开题/中期/结题/分数
    deadline: Optional[str] = None    # ISO8601
    deadline_src: str = "none"        # regex | llm | none
    low_conf: bool = False            # choice 概率边缘 / 兜底触发 / L4 失败
    verified: int = 0                 # +1 核验确认数（计划书双按钮，ADR-023）
    reminded_json: str = "[]"         # 已发送的临期提醒档位（reminder 调度，ADR-023）
    raw_text: str = ""
    model_calls: list[str] = field(default_factory=list)
    created_at: int = 0
