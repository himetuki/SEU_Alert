"""东南大学人文讲座监控（ADR-025）：移植 seu-lecture-cli 的**监控能力**。

移植来源：`seu-projects-test/seu-lecture-cli`（wynter-yaxley，MIT）：
- `core/lecture.py` 的 `parse_lectures` / 分页读取（queryActivityList.do）
- `core/auth.py` 的 CAS 登录（已收敛到本包 `cas.py`，与劳动教育共用）

**不使用**其预约/抢票能力（reserve.py / captcha.py / clock.py 一律不移植）。
会话：SEU_LECTURE_USERNAME/PASSWORD（CAS）或 SEU_LECTURE_COOKIES。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

from .base import WebNotice, _truncate
from .cas import UA, apply_cookies, cas_auto_login, parse_cookie_env

EHALL = "https://ehall.seu.edu.cn/"
LECTURE_API = EHALL + "gsapp/sys/yddjzxxtjappseu"
QUERY = LECTURE_API + "/queryActivityList.do"


class LectureError(Exception):
    pass


@dataclass
class Lecture:
    id: str
    title: str
    lecture_time: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    reserve_start: Optional[datetime] = None
    reserve_end: Optional[datetime] = None
    location: Optional[str] = None
    category: Optional[str] = None
    capacity: Optional[int] = None
    reserved: Optional[int] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining(self) -> Optional[int]:
        if self.capacity is None or self.reserved is None:
            return None
        return max(self.capacity - self.reserved, 0)


def _int(v: Any) -> Optional[int]:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_time(v: Any) -> Optional[datetime]:
    s = _str(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def _rows(payload: dict, key: str) -> tuple[list[dict], dict]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], (data if isinstance(data, dict) else {})
    return [r for r in rows if isinstance(r, dict)], (data if isinstance(data, dict) else {})


def parse_lectures(payload: dict) -> list[Lecture]:
    """queryActivityList.do 响应 → Lecture 列表（移植 parse_lectures，含 hdrsList 余量）。"""
    rows, extra = _rows(payload, "hdlbList")
    counts = extra.get("hdrsList")
    booked: dict[str, Optional[int]] = {}
    for item in counts if isinstance(counts, list) else []:
        if isinstance(item, dict) and isinstance(item.get("HD_WID"), str):
            booked[item["HD_WID"]] = _int(item.get("YYRS"))
    default_booked = 0 if isinstance(counts, list) else None
    out: list[Lecture] = []
    for row in rows:
        wid = _str(row.get("WID")) or _str(row.get("HD_WID"))
        if not wid:
            continue
        reserved = booked.get(wid, _int(row.get("YYRS")) if "YYRS" in row else default_booked)
        out.append(Lecture(
            id=wid,
            title=_str(row.get("JZMC")) or _str(row.get("HDMC")) or "(untitled)",
            lecture_time=_str(row.get("JZSJ")),
            start=_parse_time(row.get("JZSJ")) or _parse_time(row.get("HDKSSJ")),
            end=_parse_time(row.get("HDJSSJ")),
            reserve_start=_parse_time(row.get("YYKSSJ")),
            reserve_end=_parse_time(row.get("YYJSSJ")),
            location=_str(row.get("JZDD")),
            category=_str(row.get("JZXL_DISPLAY")),
            capacity=_int(row.get("HDZRS")),
            reserved=reserved,
            raw=row,
        ))
    return out


def lecture_to_notice(l: Lecture) -> WebNotice:
    remaining = f"{l.remaining}/{l.capacity}" if l.remaining is not None else "—"
    lines = [
        f"【人文讲座】{l.title}",
        f"时间：{l.lecture_time or '见预约系统'}",
        f"地点：{l.location or '见预约系统'}",
        f"预约开放：{l.reserve_start.strftime('%m-%d %H:%M') if l.reserve_start else '见预约系统'}"
        f" 至 {l.reserve_end.strftime('%m-%d %H:%M') if l.reserve_end else '—'}",
        f"余量：{remaining}（预约系统实时）",
        "预约途径：东南大学 ehall → 研究生讲座预约系统（本提醒仅监控，不代预约）",
    ]
    return WebNotice(
        key=f"lecture:{l.id}",
        group_id="web-lecture",
        group_name="人文讲座（预约系统监控）",
        title=f"人文讲座：{l.title}",
        text=_truncate("\n".join(lines)),
        url=LECTURE_API,
        ts=int((l.start or datetime.now()).timestamp()),
        sender="东南大学讲座预约系统",
    )


async def _fetch_lectures(client: httpx.AsyncClient, max_pages: int = 5) -> list[Lecture]:
    out: list[Lecture] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        r = await client.post(QUERY, data={"pageIndex": page, "pageSize": 100},
                              headers={"User-Agent": UA,
                                       "Referer": LECTURE_API + "/*default/index.do"})
        if r.status_code != 200:
            raise LectureError(f"讲座列表 HTTP {r.status_code}")
        try:
            payload = r.json()
        except ValueError as e:
            raise LectureError(f"讲座列表响应非 JSON: {r.text[:200]}") from e
        batch = parse_lectures(payload)
        ids = {x.id for x in batch}
        if page > 1 and batch and ids <= seen:
            break
        seen |= ids
        out.extend(batch)
        if len(batch) < 100:
            break
    return out


async def scan(root: Path, *, client: Optional[httpx.AsyncClient] = None) -> list[WebNotice]:
    """root = seu-lectures.yml。CAS/cookie 会话 → 讲座列表 → WebNotice。"""
    cfg = yaml.safe_load(Path(root).read_text(encoding="utf-8")) or {}
    keyword = str(cfg.get("keyword") or "").strip()
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=25, headers={"User-Agent": UA},
                                   follow_redirects=True)
    try:
        apply_cookies(client, parse_cookie_env(os.environ.get("SEU_LECTURE_COOKIES", "")))
        lectures = await _fetch_lectures(client)
        if not lectures:
            note = await cas_auto_login(
                client, os.environ.get("SEU_LECTURE_USERNAME", ""),
                os.environ.get("SEU_LECTURE_PASSWORD", ""), LECTURE_API)
            if note:
                raise LectureError(note)
            lectures = await _fetch_lectures(client)
        if keyword:
            lectures = [l for l in lectures if keyword in (l.title or "")]
        return [lecture_to_notice(l) for l in lectures]
    finally:
        if owns:
            await client.aclose()
