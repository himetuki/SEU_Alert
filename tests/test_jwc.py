"""教务处直采（ADR-029）：列表解析 / 正文与附件解析 / 扫描去重。

夹具 `jwc_list.html`、`jwc_article.html` 参照 WebPlus CMS 的真实结构编写。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from qq_relay.adapters.web import jwc
from qq_relay.adapters.web.jwc import (
    DEFAULT_COLUMNS,
    load_columns,
    parse_article_page,
    parse_list_page,
    scan,
)

FIX = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class TestParseList:
    def test_parses_internal_articles(self):
        arts = parse_list_page(_read("jwc_list.html"), "jwxx",
                               "https://jwc.seu.edu.cn/jwxx/list.htm")
        assert len(arts) == 2
        url, title, date, aid = arts[0]
        assert url == "https://jwc.seu.edu.cn/2026/0912/c9126a587045/page.htm"
        assert title == "关于2026年秋季学期选课的通知"
        assert date == "20260912"
        assert aid == "c9126a587045"

    def test_excludes_external_links(self):
        """公众号转载等非站内文章链接不进入归档。"""
        arts = parse_list_page(_read("jwc_list.html"), "jwxx",
                               "https://jwc.seu.edu.cn/jwxx/list.htm")
        assert not any("mp.weixin" in u for u, *_ in arts)

    def test_title_from_attr_when_inner_empty(self):
        html = ('<a href="/2026/0912/c123456/page.htm" title="属性标题">'
                '</a>')
        arts = parse_list_page(html, "jwxx", "https://jwc.seu.edu.cn/x/list.htm")
        assert len(arts) == 1
        assert arts[0][1] == "属性标题"

    def test_dedupes_same_url(self):
        one = ('<a href="/2026/0912/c123456/page.htm">同名通知</a>')
        arts = parse_list_page(one + one, "jwxx",
                               "https://jwc.seu.edu.cn/x/list.htm")
        assert len(arts) == 1

    def test_empty_page_returns_empty(self):
        assert parse_list_page("<html><body>无通知</body></html>", "jwxx",
                               "https://jwc.seu.edu.cn/x/list.htm") == []


class TestParseArticle:
    def test_title_content_attachments(self):
        title, content, ts, att = parse_article_page(
            _read("jwc_article.html"), "20260912")
        assert title == "关于2026年秋季学期选课的通知"
        assert "9月20日前" in content
        assert ts > 0
        urls = [a["url"] for a in att]
        assert "/_upload/article/files/ab/cd/xyz123.pdf" in urls
        assert "/_upload/article/files/ef/01/plan456.xlsx" in urls
        assert [a["name"] for a in att][0].endswith(".pdf")

    def test_footer_cut(self):
        _t, content, _ts, _a = parse_article_page(
            _read("jwc_article.html"), "20260912")
        assert "版权所有" not in content
        assert "地址：" not in content

    def test_ts_fallback_to_list_date(self):
        _t, _c, ts, _a = parse_article_page("<html></html>", "20260912")
        from datetime import datetime
        assert ts == int(datetime(2026, 9, 12).timestamp())


class TestColumns:
    def test_builtin_six_columns(self):
        cols = load_columns(Path("nonexistent.yml"))
        assert len(cols) == 6
        assert {c["id"] for c in cols} == {
            "zxdt", "jwxx", "xjgl", "sjjx", "gjjl", "cbxx"}
        assert cols == [dict(c) for c in DEFAULT_COLUMNS]

    def test_yaml_override(self, tmp_path):
        p = tmp_path / "jwc.yml"
        p.write_text(
            "columns:\n"
            "  - {id: only, name: 仅此栏目, url: 'https://jwc.seu.edu.cn/only/list.htm'}\n",
            encoding="utf-8")
        cols = load_columns(p)
        assert [c["id"] for c in cols] == ["only"]

    def test_bad_yaml_falls_back(self, tmp_path):
        p = tmp_path / "jwc.yml"
        p.write_text("columns: [不, 是, 映射]\n", encoding="utf-8")
        assert len(load_columns(p)) == 6


class TestScan:
    def test_scan_with_mock_transport(self, tmp_path):
        """列表页 + 文章页各请求一次，产出 WebNotice（群=web-jwc）。"""
        list_html = _read("jwc_list.html")
        art_html = _read("jwc_article.html")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if request.url.path.endswith("list.htm"):
                return httpx.Response(200, text=list_html)
            return httpx.Response(200, text=art_html)

        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        notices = asyncio.run(run())
        assert len(notices) == 2
        n = notices[0]
        assert n.group_id == "web-jwc"
        assert n.group_name.startswith("教务处")
        assert "【教务信息】" in n.text
        assert "9月20日" in n.text
        assert n.sender == "东南大学教务处"
        # 抓到正文 → 内容指纹键（不含栏目/文章ID，便于跨 ID 去重）
        assert n.key.startswith("jwc:")
        assert "c9126a587045" not in n.key
        assert n.url.startswith("https://jwc.seu.edu.cn/2026/")

    def test_attachments_surfaced_in_text(self, tmp_path):
        """附件（pdf/xls…）以「附件：名称 绝对链接」附在正文之后。"""
        list_html = _read("jwc_list.html")
        art_html = _read("jwc_article.html")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("list.htm"):
                return httpx.Response(200, text=list_html)
            return httpx.Response(200, text=art_html)

        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        text = asyncio.run(run())[0].text
        assert "附件：" in text
        assert "选课操作手册.pdf" in text
        assert "https://jwc.seu.edu.cn/_upload/article/files/ab/cd/xyz123.pdf" in text
        assert "培养方案.xlsx" in text

    def test_same_content_different_id_same_key(self, tmp_path):
        """同一通知换了文章 ID / 链接重新发布 → 内容指纹不变 → 去重键相同。"""
        list_html = (
            '<a href="/2026/0912/c111111/page.htm">关于选课的通知</a>'
            '<a href="/2026/0913/c222222/page.htm">关于选课的通知</a>')
        art_html = _read("jwc_article.html")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("list.htm"):
                return httpx.Response(200, text=list_html)
            return httpx.Response(200, text=art_html)

        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        notices = asyncio.run(run())
        assert len(notices) == 2
        assert notices[0].url != notices[1].url        # 不同链接
        assert notices[0].key == notices[1].key        # 相同指纹

    def test_key_falls_back_to_id_without_content(self, tmp_path):
        """文章页取不到正文时回退按链接去重，避免空正文塌缩成同一个键。"""
        list_html = _read("jwc_list.html")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("list.htm"):
                return httpx.Response(200, text=list_html)
            return httpx.Response(500, text="err")

        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        notices = asyncio.run(run())
        assert len(notices) == 2
        assert len({n.key for n in notices}) == 2      # 互不相同的回退键
        assert all(n.key.startswith("jwc:jwxx:") for n in notices)

    def test_scan_survives_list_error(self, tmp_path):
        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        assert asyncio.run(run()) == []

    def test_article_failure_falls_back_to_list_title(self, tmp_path):
        list_html = _read("jwc_list.html")
        cfg = tmp_path / "jwc.yml"
        cfg.write_text(
            "columns:\n"
            "  - {id: jwxx, name: 教务信息, url: 'https://jwc.seu.edu.cn/jwxx/list.htm'}\n",
            encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("list.htm"):
                return httpx.Response(200, text=list_html)
            return httpx.Response(500, text="err")

        async def run():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(transport=transport) as client:
                return await scan(cfg, client=client)

        notices = asyncio.run(run())
        assert len(notices) == 2
        # 文章页 500 → 用列表页标题兜底，正文为空
        assert notices[0].title == "关于2026年秋季学期选课的通知"
        assert "【教务信息】关于2026年秋季学期选课的通知" in notices[0].text


class TestFingerprint:
    """内容指纹：忽略排版空白，用于跨文章 ID 去重。"""

    def test_whitespace_insensitive(self):
        from qq_relay.adapters.web.jwc import _fingerprint
        assert (_fingerprint("标题", "正文 内容")
                == _fingerprint("标题", "正文\n\n内容")
                == _fingerprint("标题", " 正文\t内容 "))

    def test_content_sensitive(self):
        from qq_relay.adapters.web.jwc import _fingerprint
        assert _fingerprint("标题", "正文") != _fingerprint("标题", "别的正文")
        assert _fingerprint("标题", "正文") != _fingerprint("别标题", "正文")

    def test_stable_length(self):
        from qq_relay.adapters.web.jwc import _fingerprint
        assert len(_fingerprint("t", "c")) == 16


class TestRegistry:
    def test_jwc_registered(self):
        from qq_relay.adapters.web import SCANNERS
        assert "jwc" in SCANNERS
        assert SCANNERS["jwc"] is jwc.scan
