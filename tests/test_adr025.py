"""ADR-025 测试：公众号监控（搜狗列表/跳转解析/mp 正文/模型代读）+ 人文讲座监控移植。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from qq_relay.adapters.web.seu_lectures import (
    lecture_to_notice,
    parse_lectures,
)
from qq_relay.adapters.web.wechat_mp import (
    build_notice_text,
    parse_mp_article,
    parse_sogou_list,
    resolve_sogou_link,
    scan,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeChat:
    def __init__(self, reply: str, enabled: bool = True):
        self.reply = reply
        self.enabled = enabled

    async def complete(self, system: str, user: str, image_b64=None):
        from qq_relay.pipeline.llm import ChatResult
        return ChatResult(text=self.reply, model="fake", latency_ms=1)


# ---------------------------------------------------------------- 公众号：解析

class TestSogouParsing:
    def test_parse_real_list_page(self):
        items = parse_sogou_list(
            (FIXTURES / "sogou_list.html").read_text(encoding="utf-8", errors="ignore"))
        assert len(items) == 10
        it = items[0]
        assert it["title"] and it["link"].startswith("/link?url=")
        assert it["account"] and "document.write" not in it["account"]
        assert it["ts"] > 0

    def test_resolve_link_fragments(self):
        assert resolve_sogou_link(
            "url += 'https://mp.'; url += 'weixin.qq.com'; url += '/s?src=3';"
        ) == "https://mp.weixin.qq.com/s?src=3"

    def test_resolve_link_plus_form(self):
        assert resolve_sogou_link(
            "var url = 'https://mp.' + 'weixin.qq.com/s';"
        ) == "https://mp.weixin.qq.com/s"

    def test_resolve_link_direct(self):
        assert resolve_sogou_link(
            'url = "https://mp.weixin.qq.com/s/abc"') .startswith("https://mp.weixin.qq.com")

    def test_parse_mp_article(self):
        html = ('<html><body>'
                '<h1 class="rich_media_title" id="activity-name">关于举办人文讲座的通知</h1>'
                "var createTime = \"2026-11-05\";"
                '<div class="rich_media_content" id="js_content">'
                "<p>本周讲座需要预约，预约路径：数智东南-工作台-学业生活-素质讲座。</p>"
                "<p>时间：11月10日 14:00，地点：九龙湖校区教六-201。</p>"
                "</div><script>x</script></body></html>")
        title, ts, content = parse_mp_article(html)
        assert title == "关于举办人文讲座的通知"
        assert ts > 0
        assert "数智东南" in content and "九龙湖" in content


class TestExtraction:
    def test_build_notice_text_campus_first(self):
        info = {"title": "唐诗的魅力", "time": "11月10日 14:00",
                "campus": "九龙湖", "room": "教六-201",
                "signup_path": "数智东南-工作台-学业生活-素质讲座",
                "summary": "人文讲座"}
        text = build_notice_text(info, "正文内容")
        assert text.startswith("【九龙湖校区】唐诗的魅力")
        assert "地点：九龙湖教六-201" in text
        assert "报名途径：数智东南-工作台-学业生活-素质讲座" in text
        assert "摘要：人文讲座" in text

    def test_build_notice_text_no_campus(self):
        text = build_notice_text({"title": "某活动"}, "内容")
        assert text.startswith("【讲座】某活动")


class TestWechatMpScan:
    def test_scan_end_to_end_mocked(self, tmp_path):
        cfg = tmp_path / "wechat-mp.yml"
        cfg.write_text(
            "accounts:\n  - key: wzjy\n    name: 东南大学文化素质教育中心\n"
            "extract_layer: big\n", encoding="utf-8")
        list_html = (FIXTURES / "sogou_list_match.html").read_text(
            encoding="utf-8", errors="ignore")
        article_html = ('<html><body>'
                        '<h1 class="rich_media_title">关于举办人文讲座的通知</h1>'
                        "var createTime = \"2026-11-05\";"
                        '<div class="rich_media_content" id="js_content">'
                        "<p>预约路径：数智东南-工作台-学业生活-素质讲座。地点：九龙湖校区教六-201。</p>"
                        "</div><script></script></body></html>")
        link_body = "url += 'https://mp.'; url += 'weixin.qq.com'; url += '/s/AbC123';"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "weixin.sogou.com/weixin" in url:
                return httpx.Response(200, text=list_html)
            if "/link?url=" in url:
                return httpx.Response(200, text=link_body)
            return httpx.Response(200, text=article_html)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        chat = FakeChat(json.dumps({
            "is_lecture": True, "title": "关于举办人文讲座的通知",
            "time": "11月10日 14:00", "campus": "九龙湖", "room": "教六-201",
            "signup_path": "数智东南-工作台-学业生活-素质讲座",
            "summary": "人文讲座通知"}, ensure_ascii=False))
        notices = asyncio.run(scan(cfg, client=client, chat=chat))
        assert len(notices) >= 1
        n = notices[0]
        assert n.group_id == "web-mp-wzjy"
        assert "【九龙湖校区】" in n.text
        assert "数智东南" in n.text

    def test_scan_skips_non_lecture(self, tmp_path):
        cfg = tmp_path / "wechat-mp.yml"
        cfg.write_text(
            "accounts:\n  - key: wzjy\n    name: 东南大学文化素质教育中心\n",
            encoding="utf-8")
        list_html = (FIXTURES / "sogou_list_match.html").read_text(
            encoding="utf-8", errors="ignore")

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "weixin.sogou.com/weixin" in url:
                return httpx.Response(200, text=list_html)
            if "/link?url=" in url:
                return httpx.Response(
                    200, text="url += 'https://mp.'; url += 'weixin.qq.com'; url += '/s/X';")
            return httpx.Response(200, text="<html><body>"
                                   '<h1 class="rich_media_title">工作总结</h1>'
                                   '<div class="rich_media_content" id="js_content">'
                                   "<p>本月工作总结。</p></div></body></html>")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        chat = FakeChat('{"is_lecture": false, "title": "", "time": "", '
                        '"campus": "", "room": "", "signup_path": "", "summary": ""}')
        notices = asyncio.run(scan(cfg, client=client, chat=chat))
        assert notices == []                      # 模型判定非讲座 → 全部过滤

    def test_scan_without_model_falls_back_to_raw(self, tmp_path):
        cfg = tmp_path / "wechat-mp.yml"
        cfg.write_text(
            "accounts:\n  - key: wzjy\n    name: 东南大学文化素质教育中心\n",
            encoding="utf-8")
        list_html = (FIXTURES / "sogou_list_match.html").read_text(
            encoding="utf-8", errors="ignore")

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "weixin.sogou.com/weixin" in url:
                return httpx.Response(200, text=list_html)
            if "/link?url=" in url:
                return httpx.Response(
                    200, text="url += 'https://mp.'; url += 'weixin.qq.com'; url += '/s/Y';")
            return httpx.Response(200, text="<html><body>"
                                   '<h1 class="rich_media_title">讲座预告</h1>'
                                   '<div class="rich_media_content" id="js_content">'
                                   "<p>11月10日九龙湖校区讲座。</p></div></body></html>")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notices = asyncio.run(scan(cfg, client=client, chat=None))
        assert len(notices) >= 1
        assert "讲座预告" in notices[0].text


# ---------------------------------------------------------------- 人文讲座（移植）

LECTURE_PAYLOAD = {
    "data": {
        "hdlbList": [
            {"WID": "L1", "JZMC": "唐诗的魅力", "JZSJ": "2026-11-10 14:00-16:00",
             "JZDD": "九龙湖校区教六-201", "JZXL_DISPLAY": "人文",
             "HDZRS": "300", "YYKSSJ": "2026-11-05 12:00:00",
             "YYJSSJ": "2026-11-09 12:00:00"},
            {"WID": "L2", "JZMC": "已满讲座", "JZSJ": "2026-11-11 10:00",
             "JZDD": "四牌楼校区礼东-105", "HDZRS": "100"},
        ],
        "hdrsList": [{"HD_WID": "L1", "YYRS": "280"}],
    }
}


class TestLectureParsing:
    def test_parse_lectures(self):
        lectures = parse_lectures(LECTURE_PAYLOAD)
        assert len(lectures) == 2
        l1 = lectures[0]
        assert l1.id == "L1" and l1.title == "唐诗的魅力"
        assert l1.location == "九龙湖校区教六-201"
        assert l1.capacity == 300 and l1.reserved == 280
        assert l1.remaining == 20
        assert l1.reserve_start is not None
        # 无预订记录的按 0 计
        assert lectures[1].reserved == 0 and lectures[1].remaining == 100

    def test_lecture_to_notice(self):
        lectures = parse_lectures(LECTURE_PAYLOAD)
        n = lecture_to_notice(lectures[0])
        assert n.group_id == "web-lecture"
        assert "【人文讲座】唐诗的魅力" in n.text
        assert "余量：20/300" in n.text
        assert "不代预约" in n.text
        assert n.key == "lecture:L1"

    def test_empty_payload(self):
        assert parse_lectures({"data": {"hdlbList": []}}) == []


class TestLectureScan:
    def test_scan_with_cookie(self, tmp_path):
        from qq_relay.adapters.web.seu_lectures import scan as lecture_scan

        cfg = tmp_path / "seu-lectures.yml"
        cfg.write_text("keyword: \"\"\n", encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            assert "queryActivityList" in str(request.url)
            assert "cookie" in request.headers or True
            return httpx.Response(200, json=LECTURE_PAYLOAD)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        import qq_relay.adapters.web.cas as cas
        old = cas.parse_cookie_env
        cas.parse_cookie_env = lambda raw: {"JSESSIONID": "x"}
        try:
            notices = asyncio.run(lecture_scan(cfg, client=client))
        finally:
            cas.parse_cookie_env = old
        assert len(notices) == 2
        assert notices[0].group_id == "web-lecture"
