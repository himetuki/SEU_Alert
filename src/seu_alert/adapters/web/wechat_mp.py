"""公众号监控（ADR-025）：免登录发现 + 正文抓取 + 大/小模型代读汇总。

链路（全部免登录）：
  搜狗微信文章搜索（type=2，按公众号名）→ /link?url= 跳转解析（JS 片段拼回）
  → mp.weixin.qq.com 文章页（公开）→ 正文解析
  → 大/小模型（Chat Completion）提取讲座字段 → WebNotice

讲座字段（用户要求）：活动题目 / 活动时间 / 活动地点（校区着重 + 教室）/
报名途径（只提取文字路径如"数智东南-工作台-学业生活-素质讲座"，不提取二维码/链接）。

配置：config/wechat-mp.yml（默认监控「东南大学文化素质教育中心」）。
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import httpx
import yaml

from .base import WebNotice, _truncate
from .cas import UA

SOGOU_SEARCH = "https://weixin.sogou.com/weixin?type=2&query={query}"

EXTRACT_SYSTEM = """你是校园讲座信息提取助手。从公众号文章标题与正文中提取讲座/活动信息，
只输出一行 JSON，不要任何其他文字：
{"is_lecture": true或false, "title": "活动题目", "time": "活动时间（保留原文表述）",
 "campus": "校区（九龙湖/四牌楼/丁家桥/无锡/苏州，文中没有则空串）",
 "room": "具体教室或场所（没有则空串）",
 "signup_path": "报名途径的原文描述（如：数智东南-工作台-学业生活-素质讲座；只提取文字路径，忽略二维码、链接、图片；没有则空串）",
 "summary": "50字以内一句话摘要"}
规则：campus 必须依据文中明确信息（校区名/教室楼栋所在校区），无法判断填空串；
非讲座/活动通知（如议程、总结、招生、党建）is_lecture 填 false，其余字段空串。"""


def parse_sogou_list(html_text: str) -> list[dict]:
    """搜狗文章搜索页 → [{title, account, link, ts}]。

    结果在 .txt-box 内：<h3><a href="/link?url=...">标题</a></h3>
    + div.s-p（公众号名）+ span.s2 > timeConvert('unix_ts')。
    """
    out: list[dict] = []
    for box in re.split(r'<div class="txt-box">', html_text)[1:]:
        m = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', box, re.S)
        if not m:
            continue
        link, title = m.group(1), _strip(m.group(2))
        if not title or "/link?url=" not in link:
            continue
        sp = re.search(r'<div class="s-p">(.*?)</div>', box, re.S)
        account = ""
        if sp:
            # 账号名在 <span class="all-time-y2">公众号名</span>
            am = re.search(r'class="all-time-y2"[^>]*>(.*?)</span>', sp.group(1), re.S)
            if not am:
                am = re.search(r"<a[^>]*>(.*?)</a>", sp.group(1), re.S)
            if am:
                account = _strip(re.split(r"<", am.group(1))[0])[:30]
        tm = re.search(r"timeConvert\('(\d{9,10})'\)", box)
        out.append({
            "title": title,
            "account": account,
            "link": link.replace("&amp;", "&"),
            "ts": int(tm.group(1)) if tm else 0,
        })
    return out


def resolve_sogou_link(body: str) -> str:
    """/link?url= 响应体 → 真实 mp.weixin.qq.com URL。

    兼容两种拼法：`url += '…'` 片段序列与 `var url = 'a' + 'b'`。
    """
    parts = re.findall(r"url \+= '([^']*)'", body)
    if not parts:
        m = re.search(r"var url = ((?:'[^']*'(?:\s*\+\s*)?)+)", body)
        if m:
            parts = re.findall(r"'([^']*)'", m.group(1))
    if not parts:
        m = re.search(r'"(https://mp\.weixin\.qq\.com[^"]+)"', body)
        if m:
            return m.group(1)
        raise ValueError("无法解析搜狗跳转链接")
    return "".join(parts)


def parse_mp_article(html_text: str) -> tuple[str, int, str]:
    """mp.weixin.qq.com 文章页 → (title, publish_ts, content)。"""
    title = ""
    m = re.search(r'<h1[^>]*class="rich_media_title[^"]*"[^>]*>(.*?)</h1>', html_text, re.S) \
        or re.search(r'<title[^>]*>(.*?)</title>', html_text, re.S | re.I)
    if m:
        title = _strip(m.group(1))
    ts = 0
    m = re.search(r'var createTime = "(\d{4}-\d{2}-\d{2})"', html_text) \
        or re.search(r'(\d{4}-\d{2}-\d{2})\s*\d{0,2}:?\d{0,2}', html_text)
    if m:
        try:
            ts = int(datetime.strptime(m.group(1)[:10], "%Y-%m-%d").timestamp())
        except ValueError:
            ts = 0
    content = ""
    m = re.search(r'<div class="rich_media_content[^"]*"[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script',
                  html_text, re.S)
    if not m:
        m = re.search(r'id="js_content"[^>]*>(.*?)</div>\s*<script', html_text, re.S)
    if m:
        content = _clean_html(m.group(1))
    return title, ts, content


def _strip(html_text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html_text or "")).strip()


def _clean_html(html_text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html_text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_notice_text(info: dict, content: str) -> str:
    """按用户要求组装：校区着重显示 + 题目/时间/地点/报名途径。"""
    campus = (info.get("campus") or "").strip()
    room = (info.get("room") or "").strip()
    head = f"【{campus}校区】" if campus else "【讲座】"
    loc = "".join(x for x in (campus, room) if x) or "—"
    lines = [
        f"{head}{info.get('title') or ''}",
        f"时间：{info.get('time') or '见原文'}",
        f"地点：{loc}",
        f"报名途径：{info.get('signup_path') or '见原文'}",
        f"摘要：{info.get('summary') or ''}",
        "─" * 40,
        content[:600] + ("…" if len(content) > 600 else ""),
    ]
    return _truncate("\n".join(lines))


async def _extract_with_model(chat, title: str, content: str) -> dict:
    """大/小模型提取讲座字段；失败/未配 → {}（走原文兜底）。"""
    if chat is None or not getattr(chat, "enabled", False):
        return {}
    from ...pipeline.llm import ChatError

    user = f"文章标题：{title}\n\n正文：{content[:2500]}"
    try:
        r = await chat.complete(EXTRACT_SYSTEM, user)
        return _parse_json(r.text)
    except (ChatError, ValueError):
        return {}


def _parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


async def scan(root: Path, *, client: Optional[httpx.AsyncClient] = None,
               chat=None) -> list[WebNotice]:
    """root = wechat-mp.yml。返回新文章的 WebNotice（diff 由 web_seen 承担）。"""
    cfg = yaml.safe_load(Path(root).read_text(encoding="utf-8")) or {}
    accounts = cfg.get("accounts") or []
    layer = str(cfg.get("extract_layer") or "big")
    if not accounts:
        return []
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=25, headers={"User-Agent": UA},
                                   follow_redirects=True)
    out: list[WebNotice] = []
    try:
        for acc in accounts:
            name = str(acc.get("name") or "").strip()
            key = str(acc.get("key") or "").strip() or re.sub(r"\W+", "", name)[:8]
            # 可选：把该公众号的讲座并入指定频道（如人文讲座 web-lecture）
            gid = str(acc.get("group_id") or "").strip() or f"web-mp-{key}"
            if not name:
                continue
            try:
                r = await client.get(SOGOU_SEARCH.format(query=name))
                if r.status_code != 200 or "txt-box" not in r.text:
                    if "验证码" in r.text or "antispider" in r.text:
                        print(f"[wechat_mp:{key}] 搜狗要求验证码，本轮跳过")
                    continue
                items = parse_sogou_list(r.text)[:8]
            except httpx.HTTPError:
                continue
            for it in items:
                # 只保留该账号的文章（account 字段匹配；搜不到匹配时按标题相关性放宽）
                if it["account"] and it["account"] != name:
                    continue
                try:
                    lr = await client.get(
                        "https://weixin.sogou.com" + it["link"],
                        # Referer 必须 URL 编码：raw 中文会让 httpx 构 header 抛
                        # UnicodeEncodeError（ValueError 子类，会被下面的 except 吞掉）
                        headers={"Referer": SOGOU_SEARCH.format(query=quote(name))})
                    url = resolve_sogou_link(lr.text)
                except (httpx.HTTPError, ValueError):
                    continue
                try:
                    ar = await client.get(url)
                    if ar.status_code != 200:
                        continue
                    title, ts, content = parse_mp_article(ar.text)
                except httpx.HTTPError:
                    continue
                title = title or it["title"]
                ts = ts or it["ts"] or int(time.time())
                info = await _extract_with_model(chat, title, content)
                if info and info.get("is_lecture") is False:
                    continue                        # 模型判定非讲座 → 不入库
                text = build_notice_text(info, content) if info else \
                    _truncate(f"【讲座】{title}\n{content}")
                out.append(WebNotice(
                    key=f"mp:{url}",
                    group_id=gid,
                    group_name=name,
                    title=title,
                    text=text,
                    url=url,
                    ts=ts,
                    sender=name,
                ))
    finally:
        if owns:
            await client.aclose()
    return out
