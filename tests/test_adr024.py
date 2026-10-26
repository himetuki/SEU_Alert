"""ADR-024 测试：全院系采集（真实页面夹具）+ 劳动教育移植（解析/过滤/RSA/CAS 流程）。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from qq_relay.adapters.web.labor import (
    FilterOptions,
    LaborSession,
    course_to_notice,
    eligible,
    parse_courses,
    rsa_encrypt_password,
)
from qq_relay.adapters.web.seu_colleges import (
    load_colleges,
    parse_article_page,
    parse_list_page,
    scan,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------- 学院采集

class TestCollegesParser:
    def test_parse_real_list_page(self):
        arts = parse_list_page(
            (FIXTURES / "arch_list.html").read_text(encoding="utf-8", errors="ignore"))
        assert len(arts) >= 8
        path, title, url_date = arts[0]
        assert path.startswith("/2026/") and path.endswith("page.htm")
        assert "建筑学院" in title
        assert url_date.startswith("2026")

    def test_parse_real_article_page(self):
        title, content, ts = parse_article_page(
            (FIXTURES / "arch_article.html").read_text(encoding="utf-8", errors="ignore"),
            "20261021")
        assert "博士新生奖" in title
        assert ts > 0
        assert "相关学科单位" not in content        # 页脚导航已截断

    def test_parse_article_double_quotes(self):
        html = ('<html><body><h1 class="Article_Title">测试通知</h1>'
                '<span class="Article_PublishDate">2026-11-01</span>'
                '<div class="wp_articlecontent"><p>请于11月15日前提交。</p></div>'
                "</body></html>")
        title, content, ts = parse_article_page(html, "")
        assert title == "测试通知"
        assert "11月15日" in content
        assert ts > 0

    def test_load_colleges_config(self):
        root = Path("config/colleges.yml")
        colleges = load_colleges(root)
        assert len(colleges) >= 30
        names = {c["name"] for c in colleges}
        assert "建筑学院" in names and "计算机科学与工程学院" in names


class TestCollegesScanMocked:
    def test_scan_end_to_end(self, tmp_path):
        list_html = (FIXTURES / "arch_list.html").read_text(encoding="utf-8", errors="ignore")
        article_html = (FIXTURES / "arch_article.html").read_text(encoding="utf-8", errors="ignore")
        cfg = tmp_path / "colleges.yml"
        cfg.write_text(
            "colleges:\n"
            "  - key: arch\n"
            "    name: 建筑学院\n"
            "    list: https://arch.seu.edu.cn/9126/list.htm\n",
            encoding="utf-8")

        def handler(request: httpx.Request) -> httpx.Response:
            if "list.htm" in str(request.url):
                return httpx.Response(200, text=list_html)
            return httpx.Response(200, text=article_html)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        notices = asyncio.run(scan(cfg, client=client, fetch_articles=True,
                                   max_articles=3))
        assert len(notices) == 3
        n = notices[0]
        assert n.group_id == "web-arch"
        assert n.group_name == "建筑学院"
        assert "建筑学院" in n.text
        assert n.key.startswith("college:arch.seu.edu.cn:")


# ---------------------------------------------------------------- 劳动教育

def _row(cells: list[str], limit_line: str | None = None,
         td_data: dict | None = None, tr_class: str = "c--tr") -> str:
    """按劳动教育真实表格结构造一行。

    第一列固定为 td-data 选择列（与线上一致）；cells[0] 对应第 2 列。
    limit_line 放在 cells[6]（第 8 列，即 7+offset-1，offset=1 时的地点列）。
    """
    tds = []
    if td_data:
        inner = "".join(
            f'<td-data data-name="{k}" data-value="{v}"></td-data>'
            for k, v in td_data.items())
        tds.append(f"<td>{inner}</td>")
    else:
        tds.append("<td></td>")
    for i, c in enumerate(cells):
        if limit_line is not None and i == 6:
            tds.append(f'<td><span class="limit-line">{limit_line}</span></td>')
            continue
        tds.append(f"<td>{c}</td>")
    return f'<tr class="{tr_class}">{"".join(tds)}</tr>'


def _table(*rows: str) -> str:
    return (f'<html><body><table id="c_app_page_index_XuanKe_table">'
            f'<tbody>{"".join(rows)}</tbody></table></body></html>')


# 线上结构：cell1=td-data 选择列 → offset=1 → name=cell4, category=cell5,
# location=cell8(limit-line), time=cell9, deadline=cell10, enrollment=cell11,
# teacher=cell16。cells 列表从第 2 列开始。
FULL_ROW = ["1", "", "校园清洁劳动", "日常生活劳动", "—", "—", "",
            "11月20日 14:00", "11月18日 12:00", "30/50",
            "—", "—", "—", "—", "张老师", "—"]
TD = {"SJItemID": "111", "SJItemKaiKeID": "222"}


class TestLaborParser:
    def test_basic_row(self):
        html = _table(_row(FULL_ROW, limit_line="九龙湖校区", td_data=TD))
        courses = parse_courses(html, FilterOptions())
        assert len(courses) == 1
        c = courses[0]
        assert c.name == "校园清洁劳动"
        assert c.category == "日常生活劳动"
        assert c.location == "九龙湖校区"
        assert "11月20日" in c.time
        assert c.enrollment == "30/50"
        assert c.teacher == "张老师"
        assert c.invalid is False
        assert c.item_id == "111" and c.kai_ke_id == "222"
        assert c.unique_id == "校园清洁劳动|11月20日 14:00"

    def test_offset_zero_variant(self):
        # cell1 为纯数字且 cell2 非数字 → offset=0 → name=cell3, seq=col1
        row = _row(["1", "劳动教育", "图书馆整理", "服务性劳动", "—", "—", "",
                    "11月21日 09:00", "11月19日 12:00", "20/40",
                    "—", "—", "—", "—", "李老师", "—"],
                   limit_line="四牌楼校区", td_data=None)
        # td_data=None 时第一列是空 td，这里手动改成数字列
        row = row.replace("<td></td>", "<td>1</td>", 1)
        courses = parse_courses(_table(row), FilterOptions())
        assert len(courses) == 1
        c = courses[0]
        assert c.name == "图书馆整理"
        assert c.seq == "1"
        assert c.location == "四牌楼校区"

    def test_expired_invalid(self):
        row = _row([*FULL_ROW[:8], "已截止", *FULL_ROW[9:]],
                   limit_line="九龙湖校区", td_data=TD)
        courses = parse_courses(_table(row), FilterOptions())
        assert courses[0].invalid is True

    def test_filters(self):
        html = _table(
            _row(FULL_ROW, limit_line="九龙湖校区", td_data=TD),
            _row(["2", "", "食堂帮厨", "服务性劳动", "—", "—", "",
                 "11月22日 09:00", "11月20日 12:00", "10/10",
                 "—", "—", "—", "—", "王老师", "—"],
                 limit_line="四牌楼校区", td_data=TD))
        opts = FilterOptions(location_whitelist=("九龙湖",),
                             category_blacklist=("服务性劳动",))
        ok = eligible(parse_courses(html, opts), opts)
        names = {c.name for c in ok}
        assert names == {"校园清洁劳动"}

    def test_empty_page(self):
        assert parse_courses("<html>无表格</html>", FilterOptions()) == []

    def test_course_to_notice(self):
        c = parse_courses(_table(_row(FULL_ROW, limit_line="九龙湖校区",
                                      td_data=TD)), FilterOptions())[0]
        n = course_to_notice(c)
        assert n.group_id == "web-labor"
        assert "选课" in n.text and "校园清洁劳动" in n.text
        assert n.key.startswith("labor:")


class TestLaborRsa:
    def test_encrypt_roundtrip(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        body = pem.replace("-----BEGIN PUBLIC KEY-----", "").replace(
            "-----END PUBLIC KEY-----", "").replace("\n", "")
        enc = rsa_encrypt_password(body, "MyP@ssw0rd")     # 无 PEM 头也能解析
        from base64 import b64decode
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        plain = key.decrypt(b64decode(enc), padding.PKCS1v15())
        assert plain.decode() == "MyP@ssw0rd"


class TestLaborCasFlow:
    """CAS 自动登录全流程（MockTransport，不联网）。"""

    def _keypair_pem_body(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        return pem.replace("-----BEGIN PUBLIC KEY-----", "").replace(
            "-----END PUBLIC KEY-----", "").replace("\n", "")

    def test_cookie_mode_fetches_courses(self):
        html = _table(_row(FULL_ROW, limit_line="九龙湖校区"))

        def handler(request):
            assert "JSESSIONID" in request.headers.get("cookie", "")
            return httpx.Response(200, text=html)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = LaborSession(client, cookies={"JSESSIONID": "abc"})
        page = asyncio.run(session.fetch_course_page())
        assert "c_app_page_index_XuanKe_table" in page

    def test_cas_login_flow(self):
        pem_body = self._keypair_pem_body()
        html = _table(_row(FULL_ROW, limit_line="九龙湖校区"))
        state = {"logged_in": False}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "needCaptcha" in url:
                return httpx.Response(200, json={"success": True,
                                                 "needStage2Validation": False})
            if "getChiperKey" in url:
                return httpx.Response(200, json={"success": True,
                                                 "publicKey": pem_body})
            if "casback/casLogin" in url:
                body = json.loads(request.content)
                assert body["username"] == "2220250000"
                assert body["password"] and body["password"] != "pw"
                return httpx.Response(200, json={
                    "success": True, "data": {"ticket": "TGT-1"}})
            if "UnifiedAuth/CASLogin" in url:
                state["logged_in"] = True
                return httpx.Response(200, text="ok")
            if "XuanKe/Index" in url:
                if not state["logged_in"]:
                    return httpx.Response(200, text="<html>登录页</html>")
                return httpx.Response(200, text=html)
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = LaborSession(client, username="2220250000", password="pw")
        page = asyncio.run(session.fetch_course_page())
        assert state["logged_in"] is True
        assert "c_app_page_index_XuanKe_table" in page

    def test_cas_need_manual_on_sms(self):
        def handler(request):
            if "needCaptcha" in str(request.url):
                return httpx.Response(200, json={"success": True,
                                                 "needStage2Validation": True})
            return httpx.Response(404)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = LaborSession(client, username="u", password="p")
        with pytest.raises(Exception, match="短信"):
            asyncio.run(session.fetch_course_page())
