"""契约与配置加载的单元测试（P0）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from seu_alert.config import (
    ConfigError,
    Settings,
    load_groups,
    load_subscriptions,
    load_tree,
    load_web_sources,
)
from seu_alert.contracts import ClassifiedEvent, RawEvent

GOOD_GROUPS = """
groups:
  "111":
    name: 马原群
    kind: course
    course: 马原
    scope: course
    prefilter: [作业, 截止]
    default_cats: [homework, exam]
    roles:
      "10001": { role: 课程老师, note: 王老师 }
    sender_filter:
      mode: blacklist
      blacklist: ["30099"]
      dry_run: true
role_prior:
  课程老师: [homework, exam]
  unknown: [全部]
"""

GOOD_TREE = """
root:
  questions: [is_info, cat, cat2, urg, has_ddl, action]
  drop_if: { is_info_below: 0.6, cat_in: [chat] }
  state_max_chars: 1500
branches:
  - when: { cat: [homework, exam] }
    questions: [channel]
    course_noul_when: "画像未绑定课程"
extract:
  trigger: "规则未拿到 ∧ has_ddl"
  fields:
    homework: [deadline]
    notice: []
"""

GOOD_SUBS = """
subscriptions:
  "100001":
    groups: ["*all"]
    cats: [homework, exam]
    quiet: ["23:00-07:00"]
    instant_min_urg: 2
"""


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestRawEvent:
    def test_content_key_ignores_group_and_sender(self):
        a = RawEvent("qq_group", "1", "群A", "100", "甲", "m1", "高数  作业 周五交", 1)
        b = RawEvent("qq_group", "2", "群B", "200", "乙", "m2", "高数 作业 周五交", 2)
        assert a.content_key() == b.content_key()


class TestClassifiedEvent:
    def test_defaults(self):
        ev = ClassifiedEvent(
            event_id="e1", groups=["1"], cat="homework", cat2="homework",
            is_info=0.9, urg=2, action="submit", has_ddl=True,
        )
        assert ev.low_conf is False
        assert ev.deadline_src == "none"
        assert ev.model_calls == []


class TestLoadGroups:
    def test_ok(self, tmp_path):
        cfg = load_groups(_write(tmp_path, "groups.yml", GOOD_GROUPS))
        g = cfg.profile_of("111")
        assert g is not None and g.kind == "course" and g.course == "马原"
        assert g.role_of("10001") == "课程老师"
        assert g.role_of("999") == "unknown"
        assert g.sender_filter.mode == "blacklist" and g.sender_filter.dry_run is True
        assert cfg.role_prior["unknown"] == ("全部",)

    def test_unknown_cat_rejected(self, tmp_path):
        bad = GOOD_GROUPS.replace("default_cats: [homework, exam]", "default_cats: [homework, 随便]")
        with pytest.raises(ConfigError, match="未知类别"):
            load_groups(_write(tmp_path, "groups.yml", bad))

    def test_course_without_binding_rejected(self, tmp_path):
        bad = GOOD_GROUPS.replace("    course: 马原\n", "")
        with pytest.raises(ConfigError, match="未绑定 course"):
            load_groups(_write(tmp_path, "groups.yml", bad))

    def test_bad_filter_mode_rejected(self, tmp_path):
        bad = GOOD_GROUPS.replace("mode: blacklist", "mode: sometimes")
        with pytest.raises(ConfigError, match="sender_filter.mode 非法"):
            load_groups(_write(tmp_path, "groups.yml", bad))

    def test_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="不存在"):
            load_groups(tmp_path / "nope.yml")


class TestLoadTree:
    def test_ok(self, tmp_path):
        cfg = load_tree(_write(tmp_path, "tree.yml", GOOD_TREE))
        assert cfg.root_questions[0] == "is_info"
        assert cfg.drop_is_info_below == 0.6
        assert cfg.drop_cats == ("chat",)
        assert cfg.branches[0].when_cats == ("homework", "exam")
        assert cfg.extract_fields["homework"] == ("deadline",)

    def test_unknown_cat_rejected(self, tmp_path):
        bad = GOOD_TREE.replace("cat: [homework, exam]", "cat: [homework, 瞎编]")
        with pytest.raises(ConfigError, match="未知类别"):
            load_tree(_write(tmp_path, "tree.yml", bad))


class TestLoadSubscriptions:
    def test_ok(self, tmp_path):
        cfg = load_subscriptions(_write(tmp_path, "subs.yml", GOOD_SUBS))
        sub = cfg.subs["100001"]
        assert sub.groups == ("*all",)
        assert sub.quiet == ("23:00-07:00",)
        assert sub.instant_min_urg == 2

    def test_unknown_cat_rejected(self, tmp_path):
        bad = GOOD_SUBS.replace("cats: [homework, exam]", "cats: [homework, 不存在]")
        with pytest.raises(ConfigError, match="未知类别"):
            load_subscriptions(_write(tmp_path, "subs.yml", bad))


class TestSettings:
    def test_deliver_mode_validation(self, monkeypatch):
        monkeypatch.setenv("DELIVER_MODE", "telepathy")
        with pytest.raises(ConfigError, match="DELIVER_MODE"):
            Settings.from_env()

    def test_classifier_validation(self, monkeypatch):
        monkeypatch.setenv("CLASSIFIER", "magic")
        with pytest.raises(ConfigError, match="CLASSIFIER"):
            Settings.from_env()


class TestEnsureSubscriptionsBootstrap:
    """真实 subscriptions.yml 不入版本库，首次运行从 .example 模板生成（ADR-027）。"""

    def _settings(self, tmp_path, monkeypatch) -> Settings:
        monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("LOG_DIR", str(tmp_path / "data" / "logs"))
        monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "data" / "outbox"))
        return Settings.from_env()

    def test_creates_from_example(self, tmp_path, monkeypatch):
        s = self._settings(tmp_path, monkeypatch)
        s.config_dir.mkdir(parents=True, exist_ok=True)
        (s.config_dir / "subscriptions.yml.example").write_text(
            "subscriptions:\n  \"100001\":\n    cats: [homework]\n", encoding="utf-8")
        s.ensure_dirs()
        real = s.config_dir / "subscriptions.yml"
        assert real.exists()
        assert "100001" in load_subscriptions(real).subs

    def test_does_not_overwrite_existing(self, tmp_path, monkeypatch):
        s = self._settings(tmp_path, monkeypatch)
        s.config_dir.mkdir(parents=True, exist_ok=True)
        (s.config_dir / "subscriptions.yml").write_text(
            "subscriptions:\n  \"999\":\n    cats: [exam]\n", encoding="utf-8")
        (s.config_dir / "subscriptions.yml.example").write_text(
            "subscriptions:\n  \"100001\":\n    cats: [homework]\n", encoding="utf-8")
        s.ensure_dirs()
        assert set(load_subscriptions(s.config_dir / "subscriptions.yml").subs) == {"999"}

    def test_fallback_empty_when_no_example(self, tmp_path, monkeypatch):
        s = self._settings(tmp_path, monkeypatch)
        s.ensure_dirs()
        assert load_subscriptions(s.config_dir / "subscriptions.yml").subs == {}


class TestLoadWebSources:
    """web-sources.yml：新增 jwc 直采源；enabled 控制是否轮询（ADR-029）。"""

    def _write(self, tmp_path, text):
        p = tmp_path / "web-sources.yml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_jwc_kind_accepted(self, tmp_path):
        p = self._write(tmp_path, """
sources:
  - {id: jwc, kind: jwc, name: 教务处直采, root: config/jwc.yml, interval: 900}
""")
        cfg = load_web_sources(p)
        assert [s.kind for s in cfg.sources] == ["jwc"]
        assert cfg.sources[0].enabled is True   # 未写 enabled 默认启用

    def test_enabled_false_parsed(self, tmp_path):
        p = self._write(tmp_path, """
sources:
  - {id: old, kind: seu_monitor, name: 旧通道, root: store, interval: 900, enabled: false}
""")
        assert load_web_sources(p).sources[0].enabled is False

    def test_unknown_kind_rejected(self, tmp_path):
        p = self._write(tmp_path, """
sources:
  - {id: x, kind: 乱写, name: 源, root: store, interval: 900}
""")
        with pytest.raises(ConfigError, match="kind 非法"):
            load_web_sources(p)
