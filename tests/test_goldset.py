"""金标准校准 harness 测试（P2 测量仪器的自检）。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_goldset.py"
_spec = importlib.util.spec_from_file_location("run_goldset", _SCRIPT)
rg = importlib.util.module_from_spec(_spec)
sys.modules["run_goldset"] = rg          # 必须先注册：dataclass 解析字符串注解要用
_spec.loader.exec_module(rg)

FIXTURE = Path(__file__).parent / "fixtures" / "goldset.sample.jsonl"


class TestLoadGoldset:
    def test_load_sample(self):
        rows, errors = rg.load_goldset(FIXTURE)
        assert errors == []
        assert len(rows) == 13
        cats = {r.cat for r in rows}
        assert {"homework", "exam", "chat", "research", "lecture"} <= cats

    def test_bad_cat_rejected(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"id":"x","text":"t","cat":"不存在"}\n', encoding="utf-8")
        rows, errors = rg.load_goldset(p)
        assert rows == [] and any("cat 非法" in e for e in errors)

    def test_missing_field_rejected(self, tmp_path):
        p = tmp_path / "bad2.jsonl"
        p.write_text('{"id":"x","text":"t"}\n', encoding="utf-8")
        rows, errors = rg.load_goldset(p)
        assert rows == [] and any("缺字段" in e for e in errors)

    def test_bad_json_rejected(self, tmp_path):
        p = tmp_path / "bad3.jsonl"
        p.write_text("{oops\n", encoding="utf-8")
        rows, errors = rg.load_goldset(p)
        assert rows == [] and any("JSON" in e for e in errors)


class TestEvaluate:
    def test_stub_on_sample(self):
        rows, _ = rg.load_goldset(FIXTURE)
        m = rg.evaluate(rows, rg.get_classifier("stub"))
        assert m["n"] == 13
        # 留/不留：3 条闲聊应全部丢弃（预筛无关键词命中）
        assert m["keep"]["tn"] == 3
        assert m["keep"]["fp"] == 0
        # 作业行应判 homework（stub 关键词规则）
        assert m["confusion"]["homework"].get("homework") == 1
        # deadline：stub 不做提取 → 5 条有金标准 deadline 的全不中
        assert m["deadline"]["total"] == 5 and m["deadline"]["hit"] == 0

    def test_report_sections(self):
        rows, _ = rg.load_goldset(FIXTURE)
        m = rg.evaluate(rows, rg.get_classifier("stub"))
        report = rg.format_report(m, "stub", "test")
        assert "金标准校准报告" in report
        assert "分类指标" in report and "混淆矩阵" in report
        assert "deadline 提取" in report and "通过线" in report

    def test_tree_classifier_not_ready(self):
        with pytest.raises(SystemExit):
            rg.get_classifier("tree")
