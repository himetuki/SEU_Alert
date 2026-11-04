"""控制台全量配置：结构化 YAML + 高级 YAML 的校验与落盘。"""

from __future__ import annotations

import pytest
import yaml

from seu_alert import settings_io, settings_schema


def _mk(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "web-sources.yml").write_text(
        "sources:\n"
        "  - id: jwc\n    kind: jwc\n    name: 教务处\n    root: config/jwc.yml\n    interval: 900\n"
        "  - id: labor\n    kind: labor\n    name: 劳动\n    root: config/labor.yml\n"
        "    interval: 900\n    enabled: false\n", encoding="utf-8")
    (cfg / "wechat-mp.yml").write_text(
        "accounts:\n  - key: wzjy\n    name: 文化素质教育中心\n    group_id: web-lecture\n"
        "extract_layer: big\ninterval: 1800\n", encoding="utf-8")
    (cfg / "jwc.yml").write_text(
        "base_url: https://jwc.seu.edu.cn\ncolumns:\n"
        "  - id: jwxx\n    name: 教务信息\n    url: https://jwc.seu.edu.cn/jwxx/list.htm\n",
        encoding="utf-8")
    (cfg / "lecture-site.yml").write_text(
        "group_id: web-lecture\ngroup_name: 人文讲座\ncolumns:\n"
        "  - id: cbxx\n    name: 文化素质教育\n    url: https://jwc.seu.edu.cn/cbxx/list.htm\n",
        encoding="utf-8")
    (cfg / "labor.yml").write_text("filters:\n  location_whitelist: []\n  category_blacklist: []\n",
                                   encoding="utf-8")
    (cfg / "seu-lectures.yml").write_text('keyword: ""\n', encoding="utf-8")
    (cfg / "groups.yml").write_text("groups: {}\n", encoding="utf-8")
    (cfg / "colleges.yml").write_text("colleges: []\n", encoding="utf-8")
    (cfg / "tree.yml").write_text("root: {}\n", encoding="utf-8")
    (cfg / "classification.yml").write_text("version: 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text(
        "DELIVER_MODE=file\nPUSHPLUS_TOKEN=old-token\n", encoding="utf-8")
    return cfg


def _payload():
    return {
        "env": {
            "DELIVER_MODE": ["file", "pushplus"], "CLASSIFIER": "stub",
            "ADMIN_QQ": "10001", "ONEBOT_REVERSE_PORT": "3001",
            "REMINDER_OFFSETS": [24, 3], "REMINDER_INTERVAL": 120,
            "PUSHPLUS_TOKEN": "", "PUSHPLUS_TOPIC": "t",
            "JEV_BASE_URL": "https://a.test", "CHAT_BASE_URL": "https://b.test",
            "CHAT_MODEL": "m", "SUBMIT_EXTRACT_CHAIN": ["vision", "small"],
            "OCR_PROVIDER": "none",
        },
        "sources": [{"id": "jwc", "enabled": True, "interval": 1200},
                    {"id": "labor", "enabled": True, "interval": 600}],
        "yaml": {
            "wechat": {"accounts": [{"key": "wzjy", "name": "文化素质教育中心",
                                     "group_id": "web-lecture"},
                                    {"key": "jwc", "name": "教务处", "group_id": ""}],
                       "extract_layer": "small", "interval": 900},
            "jwc": {"base_url": "https://jwc.seu.edu.cn",
                    "columns": [{"id": "jwxx", "name": "教务信息",
                                 "url": "https://jwc.seu.edu.cn/jwxx/list.htm"}]},
            "lecture_site": {"group_id": "web-lecture", "group_name": "人文讲座",
                             "columns": [{"id": "cbxx", "name": "文化素质教育",
                                          "url": "https://jwc.seu.edu.cn/cbxx/list.htm"}]},
            "labor": {"location_whitelist": ["九龙湖"], "category_blacklist": ["讲座"]},
            "seu_lectures": {"keyword": "AI"},
        },
        "groups": {
            "groups": [{
                "id": "1", "name": "测试群", "kind": "course", "course": "马原",
                "scope": "course", "prefilter": ["作业"],
                "default_cats": ["homework", "exam"],
                "roles": [{"user_id": "10001", "role": "课程老师", "note": ""}],
                "filter_mode": "off", "whitelist": [], "blacklist": [],
                "roles_allow": [], "roles_deny": [],
                "dry_run": False, "log_filtered": True,
            }],
            "role_prior": [{"role": "课程老师", "cats": ["homework"]}],
        },
        "colleges": [{"key": "cs", "name": "计算机学院",
                      "list": "https://cs.seu.edu.cn/list.htm",
                      "prefilter": ["通知"]}],
        "tree": {
            "categories": [{"cat": c, "label": c, "criteria": c}
                           for c in ("homework", "exam", "competition", "research",
                                     "exchange", "lecture", "task", "notice", "chat")],
            "thresholds": {"is_info_below": 0.6, "low_conf_margin": 0.15},
            "cat2_policy": "同 cat = 无次类",
            "root": {"call": "jev", "questions": ["is_info"],
                     "is_info_below": 0.6, "drop_cats": ["chat"],
                     "state_max_chars": 1500},
            "branches": [{"cats": ["homework"], "questions": ["channel"],
                          "course_noul_when": ""}],
            "extract": {"trigger": "x", "call": "chat",
                        "fields": {"homework": ["deadline"]}, "fallback": "y"},
        },
        "classification": {
            "version": 1,
            "fallback": {"cat": "notice", "urg": 1, "action": "know"},
            "source_categories": [{"source": "web_crawl",
                                   "cats": ["notice", "task"]}],
            "group_categories": [{"group": "web-lecture",
                                  "cats": ["lecture", "notice"]}],
            "notice_title": ["公示"], "news_title": ["荣获"],
            "prefix_categories": [{"prefix": "讲座", "cat": "lecture"}],
            "rules": [{"cat": "competition", "priority": 90, "urg": 2,
                       "action": "signup", "keywords": ["竞赛"],
                       "exclude": ["公示"]}],
        },
    }


def test_full_save(tmp_path):
    cfg = _mk(tmp_path)
    settings_schema.save_settings(tmp_path / ".env", cfg, _payload())

    env = settings_io.read_env(tmp_path / ".env")
    assert env["DELIVER_MODE"] == "file,pushplus"
    assert env["REMINDER_INTERVAL"] == "120"
    assert env["PUSHPLUS_TOKEN"] == "old-token"       # 空密钥保持
    assert env["PUSHPLUS_TOPIC"] == "t"

    wx = yaml.safe_load((cfg / "wechat-mp.yml").read_text(encoding="utf-8"))
    assert [a["name"] for a in wx["accounts"]] == ["文化素质教育中心", "教务处"]
    assert wx["extract_layer"] == "small" and wx["interval"] == 900

    jwc = yaml.safe_load((cfg / "jwc.yml").read_text(encoding="utf-8"))
    assert jwc["columns"][0]["id"] == "jwxx"

    ls = yaml.safe_load((cfg / "lecture-site.yml").read_text(encoding="utf-8"))
    assert ls["group_id"] == "web-lecture"

    labor = yaml.safe_load((cfg / "labor.yml").read_text(encoding="utf-8"))
    assert labor["filters"]["location_whitelist"] == ["九龙湖"]

    assert "keyword: AI" in (cfg / "seu-lectures.yml").read_text(encoding="utf-8")

    groups = yaml.safe_load((cfg / "groups.yml").read_text(encoding="utf-8"))
    assert groups["groups"]["1"]["name"] == "测试群"
    assert groups["groups"]["1"]["kind"] == "course"
    assert groups["groups"]["1"]["sender_filter"]["mode"] == "off"
    assert groups["role_prior"]["课程老师"] == ["homework"]

    colleges = yaml.safe_load((cfg / "colleges.yml").read_text(encoding="utf-8"))
    assert colleges["colleges"][0]["key"] == "cs"

    tree = yaml.safe_load((cfg / "tree.yml").read_text(encoding="utf-8"))
    assert tree["categories"]["homework"]["criteria"] == "homework"
    assert tree["branches"][0]["when"]["cat"] == ["homework"]

    cls = yaml.safe_load((cfg / "classification.yml").read_text(encoding="utf-8"))
    assert cls["rules"][0]["cat"] == "competition"
    assert cls["source_categories"]["web_crawl"] == ["notice", "task"]
    assert cls["prefix_categories"]["讲座"] == "lecture"

    # 采集源 enabled/interval
    src = yaml.safe_load((cfg / "web-sources.yml").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in src["sources"]}
    assert by_id["labor"]["enabled"] is True and by_id["labor"]["interval"] == 600


def test_invalid_groups_rejected_without_writes(tmp_path):
    cfg = _mk(tmp_path)
    before = (tmp_path / ".env").read_text(encoding="utf-8")
    body = _payload()
    body["groups"] = {"groups": [{"id": "", "name": ""}], "role_prior": []}
    with pytest.raises(ValueError):
        settings_schema.save_settings(tmp_path / ".env", cfg, body)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == before
    assert (cfg / "groups.yml").read_text(encoding="utf-8") == "groups: {}\n"


def test_invalid_env_rejected(tmp_path):
    cfg = _mk(tmp_path)
    body = _payload()
    body["env"]["REMINDER_OFFSETS"] = [0, 200]
    with pytest.raises(ValueError):
        settings_schema.save_settings(tmp_path / ".env", cfg, body)