"""东南大学各学院通知扫描（ADR-024：全院系覆盖，按学院订阅）。

学院官网均为 WebPlus CMS（与教务处/计软智同款），列表页文章链接模式
`/YYYY/MMDD/c<hash>/page.htm`，文章页选择器 arti_title/arti_update/
wp_articlecontent（兼容 Article_Title/Article_PublishDate/Article_Content）。

配置：config/colleges.yml（33 个学院，scripts/discover_colleges.py 自动发现）。
异步 scanner：WebPoller 的 poll_once 已支持 await 返回值。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
import yaml

from .base import WebNotice, _truncate

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# WebPlus 文章链接：/2026/1021/c9126a587045/page.htm
_ARTICLE_RE = re.compile(
    r"href=['\"](?:https?://[^/']+)?/(\d{4})/(\d{4})/(c[0-9a-z]+)/page\.htm['\"][^>]*>(.*?)</a>",
    re.S | re.I)

_TITLE_RES = [
    re.compile(r"class=['\"][^'\"]*(?:arti_title|Article_Title)[^'\"]*['\"][^>]*>(.*?)</", re.S),
    re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I),
]
_DATE_RES = [
    re.compile(r"class=['\"][^'\"]*(?:arti_update|Article_PublishDate)[^'\"]*['\"][^>]*>([^<]+)<", re.S),
    re.compile(r"(\d{4}-\d{2}-\d{2})\s*\d{0,2}:?\d{0,2}", re.S),
]
_CONTENT_RES = [
    re.compile(r"class=['\"][^'\"]*(?:wp_articlecontent|Article_Content)[^'\"]*['\"][^>]*>(.*?)</div>", re.S),
    # 兜底：贪婪截取 20000 字符（含页脚噪声，分类用文本可容忍；渲染前已截断）
    re.compile(r"class=['\"][^'\"]*(?:wp_articlecontent|Article_Content)[^'\"]*['\"][^>]*>(.{0,20000})", re.S),
]


_FOOTER_MARKERS = ("相关学科单位", "加入我们", "地址：", "版权所有", "Copyright",
                   "综合管理入口", "数字中大院")


def _cut_footer(text: str) -> str:
    """WebPlus 文章页正文 div 里常嵌导航/页脚，按标记截断。"""
    cut = len(text)
    for mk in _FOOTER_MARKERS:
        i = text.find(mk)
        if 0 < i < cut:
            cut = i
    return text[:cut].strip()


def _strip_tags(html_text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_ts(y: str, md: str, default: float) -> int:
    try:
        return int(datetime(int(y), int(md[:2]), int(md[2:4])).timestamp())
    except (ValueError, TypeError):
        return int(default)


def load_colleges(path: Path) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out = []
    for c in data.get("colleges") or []:
        if c.get("key") and c.get("list"):
            out.append(c)
    return out


def parse_list_page(html_text: str) -> list[tuple[str, str, str]]:
    """列表页 → [(url_path, title, ts_source)]，按出现顺序去重。"""
    seen: set[str] = set()
    out: list[tuple[str, str, str]] = []
    for m in _ARTICLE_RE.finditer(html_text):
        y, md, cid, inner = m.group(1), m.group(2), m.group(3), m.group(4)
        path = f"/{y}/{md}/{cid}/page.htm"
        if path in seen:
            continue
        seen.add(path)
        title = _strip_tags(inner)
        if not title:
            continue
        out.append((path, title, f"{y}{md}"))
    return out


def parse_article_page(html_text: str, url_date: str) -> tuple[str, str, int]:
    """文章页 → (title, content, ts)。"""
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
    content = ""
    for rx in _CONTENT_RES:
        m = rx.search(html_text)
        if m:
            content = _cut_footer(_strip_tags(m.group(1)))
            if len(content) >= 100:          # 第一个 </div> 截断太早 → 用长窗口兜底
                break
    if not ts and url_date:
        ts = _parse_ts(url_date[:4], url_date[4:], 0)
    return title, content, ts


async def scan(root: Path, *, client: Optional[httpx.AsyncClient] = None,
               fetch_articles: bool = True,
               max_articles: int = 12) -> list[WebNotice]:
    """扫描所有学院列表页 → WebNotice。root = colleges.yml 路径。

    max_articles：每个学院每轮最多抓取的文章数（首页通常 10-20 条，
    控制对学院站的请求压力；增量轮次只新增未见的）。
    """
    colleges = load_colleges(root)
    if not colleges:
        return []
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20,
                                   headers={"User-Agent": UA},
                                   follow_redirects=True)
    out: list[WebNotice] = []
    try:
        for c in colleges:
            host = c["list"].split("/")[2]
            try:
                resp = await client.get(c["list"])
                if resp.status_code != 200:
                    continue
                articles = parse_list_page(resp.text)[:max_articles]
            except httpx.HTTPError:
                continue
            for path, list_title, url_date in articles:
                title, content, ts = list_title, "", _parse_ts(
                    url_date[:4], url_date[4:], 0)
                if fetch_articles:
                    try:
                        ar = await client.get(f"https://{host}{path}")
                        if ar.status_code == 200:
                            title, content, ts = parse_article_page(
                                ar.text, url_date)
                    except httpx.HTTPError:
                        pass
                text = _truncate(f"【{c['name']}】{title}\n{content}")
                out.append(WebNotice(
                    key=f"college:{host}:{path}",
                    group_id=f"web-{c['key']}",
                    group_name=c["name"],
                    title=title,
                    text=text,
                    url=f"https://{host}{path}",
                    ts=ts,
                    sender=c["name"],
                ))
    finally:
        if owns:
            await client.aclose()
    return out
