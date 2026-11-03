"""Windows 原生 SEU 归档生成器测试（tools/seu_archive.py）。

覆盖：归档布局 → seu_monitor 适配器回读；Windows 非法字符净化；group 覆盖。
"""

from __future__ import annotations

import json

from qq_relay.adapters.web.base import WebNotice
from qq_relay.adapters.web.jwc import load_group
from qq_relay.adapters.web.seu_monitor import scan as scan_archive
from qq_relay.tools.seu_archive import write_archive


def _notice(**kw) -> WebNotice:
    base = dict(
        key="jwc:fp-1", group_id="web-jwc", group_name="教务处",
        title="关于2026年秋季学期选课的通知",
        text="【教务信息】关于2026年秋季学期选课的通知\n请于9月20日前完成选课。",
        url="https://jwc.seu.edu.cn/2026/0912/c1a2/page.htm",
        ts=1790000000, sender="东南大学教务处",
        column="教务信息", notice_id="c1a2",
    )
    base.update(kw)
    return WebNotice(**base)


class TestSeuArchive:
    def test_roundtrip_into_consumer(self, tmp_path):
        assert write_archive(tmp_path, [_notice()]) == 1
        got = scan_archive(tmp_path)
        assert len(got) == 1
        assert got[0].title == "关于2026年秋季学期选课的通知"
        assert "请于9月20日前完成选课" in got[0].text
        assert got[0].url.endswith("page.htm")
        assert got[0].group_id == "web-jwc"

    def test_meta_layout(self, tmp_path):
        write_archive(tmp_path, [_notice()])
        meta_path = (tmp_path / "web" / "教务处" / "教务信息"
                     / "关于2026年秋季学期选课的通知--c1a2" / "meta.json")
        assert meta_path.is_file()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["notice_id"] == "c1a2"
        assert meta["column"] == "教务信息"
        assert meta["date"].startswith("20")
        text_path = meta_path.parent / "text.md"
        assert text_path.is_file()
        assert "请于9月20日前完成选课" in text_path.read_text(encoding="utf-8")

    def test_windows_illegal_chars_sanitized(self, tmp_path):
        n = _notice(title='关于<选课>:考试/安排?"新"', notice_id="c9")
        assert write_archive(tmp_path, [n]) == 1
        found = list((tmp_path / "web" / "教务处").rglob("meta.json"))
        assert len(found) == 1
        parts = found[0].relative_to(tmp_path).parts
        assert not any(ch in part for part in parts for ch in '<>:"/\\|*?')

    def test_url_notice_id_hashed(self, tmp_path):
        """栏目转载公众号文章时 notice_id 是站外 URL → 短哈希，避免非法路径。"""
        n = _notice(title="转载公众号讲座", notice_id="https://mp.weixin.qq.com/s/abc")
        assert write_archive(tmp_path, [n]) == 1
        metas = list((tmp_path / "web" / "教务处").rglob("meta.json"))
        assert len(metas) == 1
        assert any(p.startswith("u") and len(p) == 11
                   for p in (part.split("--")[-1] for part in metas[0].relative_to(tmp_path).parts))

    def test_multiple_columns(self, tmp_path):
        a = _notice(key="jwc:a", column="最新动态", notice_id="a1",
                    title="通知A", text="【最新动态】通知A\n正文A")
        b = _notice(key="jwc:b", column="文化素质教育", notice_id="b1",
                    title="讲座B", text="【文化素质教育】讲座B\n正文B")
        assert write_archive(tmp_path, [a, b]) == 2
        assert len(list((tmp_path / "web" / "教务处" / "最新动态").glob("*/meta.json"))) == 1
        assert len(list((tmp_path / "web" / "教务处" / "文化素质教育").glob("*/meta.json"))) == 1


class TestLoadGroup:
    def test_default_when_missing(self, tmp_path):
        assert load_group(tmp_path / "none.yml") == (
            "web-jwc", "教务处（jwc.seu.edu.cn）")

    def test_override(self, tmp_path):
        p = tmp_path / "lecture-site.yml"
        p.write_text("group_id: web-lecture\ngroup_name: 人文讲座\ncolumns: []",
                     encoding="utf-8")
        assert load_group(p) == ("web-lecture", "人文讲座")
