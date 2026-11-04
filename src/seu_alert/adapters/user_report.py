"""用户投稿采集（ADR-023）：文字/图片 → 提取栈 → RawEvent(source=user_report)。

群归属：投稿可指定 group_id 或 course；仅给 course 时用合成群 `course:<课程名>`
（在 groups.yml 里配 kind=course 画像后即享有课程绑定与画像预筛词）。
本地实现：SubmissionIntake 供内部测试/前端回调直接调用；HTTP 入口后续接公众号。
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from uuid import uuid4

from ..contracts import RawEvent
from ..pipeline.extract_stack import ExtractResult, SubmissionExtractor
from ..store import queries

OnNotice = Callable[[RawEvent], object]


@dataclass(frozen=True)
class Submission:
    submission_id: str
    user: str
    course: Optional[str]
    group_id: str
    raw_text: str
    image_path: Optional[str]
    extracted_text: str
    chain_used: tuple[str, ...]
    low_conf: bool
    raw_event_id: str


class SubmissionIntake:
    def __init__(self, extractor: SubmissionExtractor, on_notice: OnNotice,
                 db=None, images_dir: Optional[Path] = None) -> None:
        self.extractor = extractor
        self.on_notice = on_notice
        self.db = db
        self.images_dir = Path(images_dir) if images_dir else None

    def _read_image_b64(self, image_path: str) -> Optional[str]:
        p = Path(image_path)
        if not p.is_file():
            return None
        return base64.b64encode(p.read_bytes()).decode("ascii")

    async def submit(self, *, user: str = "internal", text: Optional[str] = None,
                     image_path: Optional[str] = None,
                     course: Optional[str] = None,
                     group_id: Optional[str] = None) -> Submission:
        if not text and not image_path:
            raise ValueError("投稿必须带 text 或 image_path")
        sid = uuid4().hex[:12]
        image_b64 = self._read_image_b64(image_path) if image_path else None
        result: ExtractResult = await self.extractor.extract(text=text, image_b64=image_b64)

        gid = group_id or (f"course:{course}" if course else "submit:unknown")
        final_text = result.text or (text or "").strip()
        hints = {}
        if course:
            hints["course"] = course
        ev = RawEvent(
            source="user_report",
            group_id=gid,
            group_name=course or "用户投稿",
            sender_id=f"user:{user}",
            sender_card=str(user),
            msg_id=sid,
            text=final_text,
            ts=int(time.time()),
            at_all=False,
            hints=hints,
        )
        await self.on_notice(ev)

        if self.db is not None:
            await queries.insert_submission(
                self.db, submission_id=sid, user=user, course=course,
                group_id=gid, raw_text=(text or ""), image_path=image_path,
                extracted_text=final_text,
                chain_used=",".join(result.chain_used),
                low_conf=result.low_conf, raw_event_id=sid)

        return Submission(submission_id=sid, user=user, course=course,
                          group_id=gid, raw_text=(text or ""),
                          image_path=image_path, extracted_text=final_text,
                          chain_used=result.chain_used,
                          low_conf=result.low_conf, raw_event_id=sid)
