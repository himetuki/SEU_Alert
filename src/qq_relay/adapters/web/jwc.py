"""东南大学教务处直采（ADR-029：自包含采集，替代对 SEU-Monitor 的运行期依赖）。

教务处站点为 WebPlus CMS，六个栏目列表页统一 `/list.htm`，文章链接模式
`/<栏目>/YYYY/MMDD/c<hash>/page.htm` 或 `/<栏目>/YYYY/MMDD/c<hash>a<id>/page.htm`，
文章页正文容器为 `wp_articlecontent`（旧模板为 `Article_Content`）。

与 seu_colleges（学院站）同构，差别只在栏目固定为六项、群固定为 web-jwc。

配置：config/jwc.yml（栏目清单 + 抓取参数）。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml

from .base import TEXT_MAX, WebNotice, _truncate

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 教务处默认六栏目（可用 config/jwc.yml 覆盖）
DEFAULT_COLUMNS = (
    {"id": "zxdt", "name": "最新动态", "url": "https://jwc.seu.edu.cn/zxdt/list.htm"},
    {"id": "jwxx", "name": "教务信息", "url": "https://jwc.seu.edu.cn/jwxx/list.htm"},
    {"id": "xjgl", "name": "学籍管理", "url": "https://jwc.seu.edu.cn/xjgl/list.htm"},
    {"id": "sjjx", "name": "实践教学", "url": "https://jwc.seu.edu.cn/sjjx/list.htm"},
    {"id": "gjjl", "name": "国际交流", "url": "https://jwc.seu.edu.cn/gjjl/list.htm"},
    {"id": "cbxx", "name": "文化素质教育", "url": "https://jwc.seu.edu.cn/cbxx/list.htm"},
)

# 文章链接：/2026/1021/c9126a587045/page.htm（栏目段可有可无）
# 单行书写：re.X 会把模式里的真实换行与空白当字面量，容易踩坑。
_ARTICLE_RE = re.compile(
    r"""href=['"](?P<href>(?:https?://[^/'"]+)?/(?:[a-z0-9]+/)?(?P<y>\d{4})/(?P<md>\d{4})/(?P<cid>c[0-9a-z]+)(?:a\d+)?/page\.htm)['"][^>]*>(?P<inner>.*?)</a>""",
    re.S | re.I)

# 兼容教务处"新版列表"：news-list-item 结构化节点
_NEWS_LIST_ITEM_RE = re.compile(
    r"""class=['"][^'"]*news-list-item[^'"]*['"][^>]*>(?P<body>.*?)</li>""", re.S | re.I)
_NEWS_ITEM_TITLE_RE = re.compile(
    r"""class=['"][^'"]*news-item-title[^'"]*['"][^>]*>(?P<inner>.*?)</""", re.S | re.I)
_NEWS_ITEM_DATE_RE = re.compile(
    r"""class=['"][^'"]*news-item-date-ym[^'"]*['"][^>]*>(?P<inner>.*?)</""", re.S | re.I)
_NEWS_ITEM_LINK_RE = re.compile(r"""<a[^>]+href=['"](?P<href>[^'"]+)['"][^>]*>""", re.I)

_TITLE_RES = (
    re.compile(r"""class=['"][^'"]*(?:arti_title|Article_Title)[^'"]*['"][^>]*>(.*?)</""", re.S),
    re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I),
)
_DATE_RES = (
    re.compile(r"""class=['"][^'"]*(?:arti_update|Article_PublishDate)[^'"]*['"][^>]*>([^<]+)<""", re.S),
    re.compile(r"(\d{4}-\d{2}-\d{2})\s*\d{0,2}:?\d{0,2}", re.S),
)
_CONTENT_RES = (
    re.compile(r"""class=['"][^'"]*(?:wp_articlecontent|Article_Content)[^'"]*['"][^>]*>(.*?)</div>""", re.S),
    re.compile(r"""class=['"][^'"]*(?:wp_articlecontent|Article_Content)[^'"]*['"][^>]*>(.{0,20000})""", re.S),
)

_FOOTER_MARKERS = ("相关学科单位", "加入我们", "地址：", "版权所有", "Copyright",
                   "综合管理入口", "友情链接", "联系我们")

# 附件扩展名（与正文一起登记的下载项）
_ATTACH_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".zip", ".rar", ".7z", ".txt")
_ATTACH_HREF_RE = re.compile(
    r"""href=['"](?P<href>[^'"]+\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|txt))['"][^>]*>(?P<text>.*?)</a>""",
    re.S | re.I)


def _strip_tags(html_text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\s+", " ", text).strip()


def _cut_footer(text: str) -> str:
    cut = len(text)
    for mk in _FOOTER_MARKERS:
        i = text.find(mk)
        if 0 < i < cut:
            cut = i
    return text[:cut].strip()


def _abs_url(base: str, ref: str) -> str:
    """相对链接 → 绝对链接（教务处站内链接）。"""
    if not ref:
        return ""
    ref = ref.strip()
    if ref.startswith(("http://", "https://")):
        return ref
    if ref.startswith("//"):
        return "https:" + ref
    if ref.startswith("/"):
        from urllib.parse import urlparse
        host = urlparse(base).netloc
        return f"https://{host}{ref}"
    from urllib.parse import urljoin
    return urljoin(base, ref)


def _parse_ts(ymd: str, fallback: float) -> int:
    """从 YYYYMMDD 或 YYYY-MM-DD 解析时间戳。"""
    s = re.sub(r"\D", "", ymd or "")[:8]
    if len(s) == 8:
        try:
            return int(datetime(int(s[:4]), int(s[4:6]), int(s[6:8])).timestamp())
        except (ValueError, TypeError):
            pass
    return int(fallback)


def load_columns(path: Path) -> list[dict]:
    """读 config/jwc.yml；不存在时用内置六栏目。"""
    p = Path(path)
    if p.is_file():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            data = {}
    else:
        data = {}
    cols = data.get("columns")
    if not cols:
        return [dict(c) for c in DEFAULT_COLUMNS]
    out = []
    for c in cols:
        if isinstance(c, dict) and c.get("url"):
            out.append({"id": str(c.get("id") or "col"),
                        "name": str(c.get("name") or c.get("id") or "栏目"),
                        "url": str(c["url"])})
    return out or [dict(c) for c in DEFAULT_COLUMNS]


def load_group(path: Path) -> tuple[str, str]:
    """读同文件的群覆盖（默认教务处 web-jwc）。

    用于复用同一套解析器开第二种频道：如人文讲座网站源：
        group_id: web-lecture
        group_name: 人文讲座（文化素质教育栏目）
    """
    p = Path(path)
    data: dict = {}
    if p.is_file():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            data = {}
    return (str(data.get("group_id") or "web-jwc"),
            str(data.get("group_name") or "教务处（jwc.seu.edu.cn）"))


def parse_list_page(html_text: str, column_id: str,
                    base: str) -> list[tuple[str, str, str, str]]:
    """列表页 → [(绝对URL, 标题, YYYYMMDD, 文章ID)]，按出现顺序去重。

    兼容两种模板：
      1) 新版 news-list-wrap / news-list-item（标题、日期为独立节点）
      2) 旧版表格 td.main > a（日期取行内最后一个 cell）
    未识别出任何条目时返回空列表（由调用方判断是否为异常页）。
    """
    out: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    def _push(href: str, title: str, date: str) -> None:
        url = _abs_url(base, href)
        if not url or url in seen:
            return
        title = title.strip()
        if not title:
            return
        # 文章 ID：/2026/1021/c9126a587045/page.htm → c9126a587045
        m = re.search(r"/(c[0-9a-z]+)(?:a\d+)?/page\.htm", url, re.I)
        aid = m.group(1) if m else url
        seen.add(url)
        out.append((url, title, date, aid))

    # --- 新版结构 ---
    for item in _NEWS_LIST_ITEM_RE.finditer(html_text):
        body = item.group("body")
        tm = _NEWS_ITEM_TITLE_RE.search(body)
        dm = _NEWS_ITEM_DATE_RE.search(body)
        lm = _NEWS_ITEM_LINK_RE.search(body)
        if not (tm and lm):
            continue
        title = _strip_tags(tm.group("inner"))
        date = _strip_tags(dm.group("inner")) if dm else ""
        _push(lm.group("href"), title, date)
    if out:
        return out

    # --- 旧版/通用：直接扫文章链接 ---
    for m in _ARTICLE_RE.finditer(html_text):
        title = _strip_tags(m.group("inner"))
        if not title:
            # 标题可能在 a 的 title 属性里
            tm = re.search(r"""title=['"]([^'"]+)['"]""", m.group(0))
            title = tm.group(1).strip() if tm else ""
        _push(m.group("href"), title, f"{m.group('y')}{m.group('md')}")

    # --- 兜底：按行取日期（td.main 结构）---
    if out and not any(d for _, _, d, _ in out):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.S | re.I)
        date_by_url: dict[str, str] = {}
        for row in rows:
            cells = [_strip_tags(c) for c in re.findall(
                r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
            href_m = _ARTICLE_RE.search(row)
            if href_m and cells:
                date_by_url[_abs_url(base, href_m.group("href"))] = cells[-1]
        if date_by_url:
            out = [(u, t, date_by_url.get(u, d), a) for u, t, d, a in out]
    return out


def parse_article_page(html_text: str, url_date: str) -> tuple[str, str, int, list[dict]]:
    """文章页 → (title, content, ts, attachments)。

    attachments: [{"url","name"}]，正文内的附件下载链接（pdf/doc/xls/…）。
    """
    title = ""
    for rx in _TITLE_RES:
        m = rx.search(html_text)
        if m:
            title = _strip_tags(m.group(1))
            if title:
                break

    ts = 0
    for rx in _DATE_RES:
        m = rx.search(html_text)
        if m:
            try:
                ts = int(datetime.strptime(m.group(1).strip()[:10],
                                           "%Y-%m-%d").timestamp())
                break
            except (ValueError, TypeError):
                continue
    if not ts:
        ts = _parse_ts(url_date, 0)

    content = ""
    for rx in _CONTENT_RES:
        m = rx.search(html_text)
        if m:
            content = _cut_footer(_strip_tags(m.group(1)))
            if len(content) >= 100:
                break

    attachments: list[dict] = []
    seen_att: set[str] = set()
    for m in _ATTACH_HREF_RE.finditer(html_text):
        href = m.group("href").strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        name = _strip_tags(m.group("text")) or href.rsplit("/", 1)[-1]
        # 过滤教务处导航位的"下载专区"等
        if name in ("下载专区", "下载中心", "附件下载专区"):
            continue
        if href in seen_att:
            continue
        seen_att.add(href)
        attachments.append({"url": href, "name": name})
    return title, content, ts, attachments


def _fingerprint(title: str, content: str) -> str:
    """内容指纹：标题 + 正文，忽略排版空白。

    用途是**跨文章 ID 去重**——学校换 ID / 换链接重新发布同一条通知时，
    指纹不变 → 不重复推送（对齐 SEU-Monitor 的内容去重语义）。
    只取前 16 位十六进制，碰撞概率对本场景足够低。
    """
    norm = re.sub(r"\s+", "", f"{title}\n{content}")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


async def scan(root: Path, *, client: Optional[httpx.AsyncClient] = None,
               fetch_articles: bool = True,
               max_articles: int = 15) -> list[WebNotice]:
    """扫描教务处六栏目 → WebNotice（群 = web-jwc）。

    root = config/jwc.yml 路径（不存在则用内置六栏目）。
    max_articles：每栏目每轮最多抓取的文章数。

    去重键：
      - 抓到正文 → `jwc:<内容指纹>`（同一通知换 ID 重发时不重复推送）
      - 文章页取不到正文 → 回退 `jwc:<栏目>:<文章ID>`（按链接去重）
    """
    columns = load_columns(root)
    group_id, group_name = load_group(root)
    if not columns:
        return []
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20, headers={"User-Agent": UA},
                                   follow_redirects=True)
    out: list[WebNotice] = []
    try:
        for col in columns:
            base = col["url"]
            try:
                resp = await client.get(base)
                if resp.status_code != 200:
                    continue
                articles = parse_list_page(resp.text, col["id"], base)[:max_articles]
            except httpx.HTTPError:
                continue
            for url, list_title, url_date, aid in articles:
                title, content, ts = list_title, "", _parse_ts(url_date, 0)
                attachments: list[dict] = []
                if fetch_articles:
                    try:
                        ar = await client.get(url)
                        if ar.status_code == 200:
                            title, content, ts, attachments = parse_article_page(
                                ar.text, url_date)
                            title = title or list_title
                    except httpx.HTTPError:
                        pass

                # 附件：给出可点击的绝对链接（不在此层下载归档）
                att_links = [f"{a['name']} {_abs_url(base, a['url'])}"
                             for a in attachments]
                suffix = ("\n附件：" + " ｜ ".join(att_links)) if att_links else ""
                head = f"【{col['name']}】{title}"
                # 给附件行留出预算，避免被正文挤掉
                budget = max(200, TEXT_MAX - len(head) - len(suffix) - 4)
                text = f"{head}\n{content[:budget]}{suffix}"

                key = (f"jwc:{_fingerprint(title, content)}" if content
                       else f"jwc:{col['id']}:{aid}")
                out.append(WebNotice(
                    key=key,
                    group_id=group_id,
                    group_name=group_name,
                    title=title,
                    text=text,
                    url=url,
                    ts=ts,
                    sender="东南大学教务处",
                    column=col["name"],
                    notice_id=aid,
                ))
    finally:
        if owns:
            await client.aclose()
    return out
