"""东南大学劳动教育课程监控（ADR-024：移植 SEU-Labor-Course-Pusher 源码逻辑）。

移植来源：`seu-projects-test/SEU-Labor-Course-Pusher`（Rust，作者 zz6zz666）：
- `site.rs`    课程表解析（table#c_app_page_index_XuanKe_table，列偏移/td-data/已满已截止）
- `watcher.rs` 轮询与 diff（unique_id = 课程名|时间；本项目的 web_seen 承担同一职责）
- `login.rs`   CAS 无浏览器登录（探测验证码 → RSA 公钥 → 加密密码 → casLogin → 票据兑换）

**不用其打包 exe**；推送复用本项目 deliver 层（PushPlus/file/qq）。
会话优先级：cookie（env/文件）→ CAS 自动登录（一卡通+密码）；需要短信/验证码时
返回 NeedManual，跳过本轮并告警，绝不静默失败。

配置：config/labor.yml；密钥走 .env（LABOR_USERNAME/LABOR_PASSWORD/LABOR_COOKIES）。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx
import yaml

from .base import WebNotice

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

COURSE_PAGE = "https://labor.seu.edu.cn/SJItemKaiKe/XuanKe/Index"
CAS_NEED_CAPTCHA = "https://auth.seu.edu.cn/auth/casback/needCaptcha"
CAS_CHIPER_KEY = "https://auth.seu.edu.cn/auth/casback/getChiperKey"
CAS_LOGIN_URL = "https://auth.seu.edu.cn/auth/casback/casLogin"
CAS_SERVICE = "https://labor.seu.edu.cn/UnifiedAuth/CASLogin"
COURSE_TABLE_ID = "c_app_page_index_XuanKe_table"


class LaborError(Exception):
    pass


@dataclass
class LaborCourse:
    seq: str = ""
    name: str = ""
    category: str = ""
    location: str = ""
    time: str = ""
    enrollment: str = ""
    teacher: str = ""
    deadline: str = ""
    invalid: bool = False
    item_id: str = ""
    kai_ke_id: str = ""

    @property
    def unique_id(self) -> str:
        return f"{self.name}|{self.time}"


@dataclass
class FilterOptions:
    location_whitelist: tuple[str, ...] = ()
    category_blacklist: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "FilterOptions":
        d = d or {}
        return cls(
            location_whitelist=tuple(str(x) for x in (d.get("location_whitelist") or [])),
            category_blacklist=tuple(str(x) for x in (d.get("category_blacklist") or [])),
        )

    def location_ok(self, loc: str) -> bool:
        return (not self.location_whitelist
                or any(kw in loc for kw in self.location_whitelist))

    def category_ok(self, cat: str) -> bool:
        return cat not in self.category_blacklist


# ---------------------------------------------------------------- 解析（移植 site.rs）

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_tags(html_text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    return _clean(re.sub(r"<[^>]+>", " ", text))


def _cell_texts(row_html: str) -> list[str]:
    """提取一行内所有 <td>…</td> 的纯文本（含嵌套标签）。

    注意：`<td(?:\s[^>]*)?>` 不能写成 `<td[^>]*>`——后者会把 `<td-data>`
    自定义元素也当成单元格，导致列全错位。
    """
    cells = re.findall(r"<td(?:\s[^>]*)?>(.*?)</td>", row_html, re.S | re.I)
    return [_strip_tags(c) for c in cells]


def _td_data_map(first_cell_html: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"<td-data[^>]*data-name=['\"]([^'\"]+)['\"][^>]*"
                         r"data-value=['\"]([^'\"]*)['\"]", first_cell_html, re.I):
        out[m.group(1)] = m.group(2)
    return out


def _is_pure_number(s: str) -> bool:
    return bool(re.fullmatch(r"\d+", s.strip()))


def _limit_line(cell_html: str) -> str:
    m = re.search(r"class=['\"][^'\"]*limit-line[^'\"]*['\"][^>]*>(.*?)</",
                  cell_html, re.S | re.I)
    return _strip_tags(m.group(1)) if m else ""


def parse_courses(page_html: str, opts: FilterOptions) -> list[LaborCourse]:
    """移植 site.rs::parse：表格 → tbody → tr.c--tr/c-tr → td 列（含偏移探测）。"""
    tm = re.search(rf'<table[^>]*id="{COURSE_TABLE_ID}"[^>]*>(.*?)</table>',
                   page_html, re.S | re.I)
    if not tm:
        return []
    table = tm.group(1)
    bm = re.search(r"<tbody[^>]*>(.*?)</tbody>", table, re.S | re.I)
    body = bm.group(1) if bm else table
    rows = re.findall(r"<tr[^>]*class=['\"][^'\"]*(?:c--tr|c-tr)[^'\"]*['\"][^>]*>(.*?)</tr>",
                      body, re.S | re.I)
    out: list[LaborCourse] = []
    for row_html in rows:
        raw_cells = re.findall(r"<td(?:\s[^>]*)?>(.*?)</td>", row_html, re.S | re.I)
        cells = [_strip_tags(c) for c in raw_cells]
        if len(cells) < 4:
            continue

        def ct(n: int) -> str:               # 1-based，越界返回"无"
            return cells[n - 1] if 1 <= n <= len(cells) else "无"

        col1, col2 = ct(1), ct(2)
        offset = 0 if (_is_pure_number(col1) and not _is_pure_number(col2)) else 1
        name = ct(3 + offset)
        category = ct(4 + offset)
        deadline = ct(9 + offset)
        enrollment = ct(10 + offset)
        location = (_limit_line(raw_cells[7 + offset - 1])
                    if 7 + offset <= len(raw_cells) else "") or "无"
        invalid = ("已满" in enrollment) or ("已截止" in deadline)
        out.append(LaborCourse(
            seq=col2 if offset == 1 else col1,
            name=name, category=category, location=location,
            time=ct(8 + offset), enrollment=enrollment,
            teacher=ct(15 + offset), deadline=deadline, invalid=invalid,
            item_id=_td_data_map(raw_cells[0]).get("SJItemID", ""),
            kai_ke_id=_td_data_map(raw_cells[0]).get("SJItemKaiKeID", ""),
        ))
    return out


def eligible(courses: list[LaborCourse], opts: FilterOptions) -> list[LaborCourse]:
    return [c for c in courses
            if not c.invalid and opts.location_ok(c.location)
            and opts.category_ok(c.category)]


# ---------------------------------------------------------------- 会话（移植 login.rs）

def rsa_encrypt_password(public_key_pem: str, password: str) -> str:
    """CAS 密码加密：RSA PKCS#1 v1.5 → base64。公钥为 PEM（可能无头，自动补）。"""
    import base64

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = public_key_pem.strip()
    if "BEGIN PUBLIC KEY" not in pem:
        pem = ("-----BEGIN PUBLIC KEY-----\n"
               + "\n".join(pem[i:i + 64] for i in range(0, len(pem), 64))
               + "\n-----END PUBLIC KEY-----")
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not hasattr(key, "encrypt"):
        raise LaborError("CAS 公钥不是 RSA 公钥")
    ct = key.encrypt(password.encode("utf-8"),
                     padding.PKCS1v15())
    return base64.b64encode(ct).decode("ascii")


class LaborSession:
    """cookie 优先，CAS 自动登录兜底。"""

    def __init__(self, client: httpx.AsyncClient,
                 username: str = "", password: str = "",
                 cookies: Optional[dict] = None) -> None:
        self.client = client
        self.username = username
        self.password = password
        self.cookies: dict[str, str] = dict(cookies or {})

    @classmethod
    def cookies_from_env(cls) -> dict[str, str]:
        raw = os.environ.get("LABOR_COOKIES", "").strip()
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
                if isinstance(data, list):                     # [{name,value},...]
                    return {str(c["name"]): str(c["value"]) for c in data}
            except (ValueError, KeyError, TypeError):
                pass
            # 退化："k=v; k2=v2"
            out = {}
            for part in raw.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    out[k.strip()] = v.strip()
            return out
        path = os.environ.get("LABOR_COOKIE_FILE", "").strip()
        if path and Path(path).is_file():
            try:
                return {str(k): str(v) for k, v in
                        json.loads(Path(path).read_text(encoding="utf-8")).items()}
            except (ValueError, OSError):
                pass
        return {}

    async def cas_login(self) -> str:
        """移植 login.rs::auto_run。返回 "" 成功；"need_manual:…" 需人工；异常抛 LaborError。"""
        if not (self.username and self.password):
            raise LaborError("未配置 LABOR_USERNAME/LABOR_PASSWORD，也未提供 cookie")
        # 0) 探测验证码/短信
        r = await self.client.get(CAS_NEED_CAPTCHA)
        cap = r.json() if r.status_code == 200 else {}
        if cap.get("needStage2Validation"):
            return "need_manual:服务端要求短信二次验证"
        info = str(cap.get("info") or "")
        if not cap.get("success") or ("验证码" in info and "不需要" not in info):
            return f"need_manual:登录需要验证码（{info}）"
        # 1) RSA 公钥 → 加密密码
        r = await self.client.post(CAS_CHIPER_KEY, json={})
        key = r.json() if r.status_code == 200 else {}
        pem = str(key.get("publicKey") or "")
        if not key.get("success") or not pem:
            raise LaborError("获取 CAS 公钥失败")
        enc = rsa_encrypt_password(pem, self.password)
        # 2) 提交登录
        r = await self.client.post(CAS_LOGIN_URL, json={
            "service": CAS_SERVICE, "username": self.username,
            "password": enc, "captcha": "", "rememberMe": False,
            "loginType": "account", "wxBinded": False,
            "mobilePhoneNum": "", "fingerPrint": "stable_qq_relay",
        })
        data = r.json() if r.status_code == 200 else {}
        if not data.get("success"):
            raise LaborError(f"CAS 登录失败: {str(data)[:200]}")
        # 3) 票据兑换（casback 重定向链由 httpx follow_redirects 自动完成）
        ticket = (data.get("data") or {}).get("ticket") \
            or (data.get("data") or {}).get("st") or ""
        if ticket:
            await self.client.get(
                f"{CAS_SERVICE}?ticket={ticket}", follow_redirects=True)
        self.cookies = dict(self.client.cookies)
        return ""

    async def fetch_course_page(self) -> str:
        for k, v in self.cookies.items():
            self.client.cookies.set(k, v)
        r = await self.client.get(COURSE_PAGE)
        # 非 200 或页面无课程表 → 会话过期：尝试一次 CAS 自动登录后重取
        if r.status_code != 200 or COURSE_TABLE_ID not in r.text:
            note = await self.cas_login()
            if note:
                raise LaborError(note)
            r = await self.client.get(COURSE_PAGE)
            if r.status_code != 200:
                raise LaborError(f"课程页 HTTP {r.status_code}")
            if COURSE_TABLE_ID not in r.text:
                raise LaborError("登录后仍未取到课程表（会话无效）")
        return r.text


# ---------------------------------------------------------------- 扫描入口

def course_to_notice(c: LaborCourse) -> WebNotice:
    text = (f"【劳动教育·新增课程】{c.name}"
            f"（类别：{c.category or '—'}｜时间：{c.time or '—'}"
            f"｜地点：{c.location or '—'}｜余量：{c.enrollment or '—'}"
            f"｜教师：{c.teacher or '—'}）"
            f"请及时登录劳动教育课程平台选课（labor.seu.edu.cn）。")
    return WebNotice(
        key=f"labor:{c.unique_id}",
        group_id="web-labor",
        group_name="劳动教育课程平台",
        title=f"劳动教育新增课程：{c.name}",
        text=text,
        url=COURSE_PAGE,
        ts=0,                                # 课程表无发布日期，用扫描时刻
        sender="劳动教育课程平台",
    )


async def scan(root: Path, *, client: Optional[httpx.AsyncClient] = None,
               now_ts: Optional[int] = None) -> list[WebNotice]:
    """root = labor.yml 路径。返回全部 eligible 课程（diff 由 web_seen 承担）。"""
    cfg = yaml.safe_load(Path(root).read_text(encoding="utf-8")) or {}
    opts = FilterOptions.from_dict(cfg.get("filters"))
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=25, headers={"User-Agent": UA},
                                   follow_redirects=True)
    try:
        session = LaborSession(
            client,
            username=os.environ.get("LABOR_USERNAME", ""),
            password=os.environ.get("LABOR_PASSWORD", ""),
            cookies=LaborSession.cookies_from_env(),
        )
        page = await session.fetch_course_page()
        courses = eligible(parse_courses(page, opts), opts)
        import time
        ts = now_ts if now_ts is not None else int(time.time())
        out = []
        for c in courses:
            n = course_to_notice(c)
            n.ts = ts
            out.append(n)
        return out
    finally:
        if owns:
            await client.aclose()
