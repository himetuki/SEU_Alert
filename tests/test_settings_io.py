"""配置页读写测试：行级保留注释、字段增补、AdminContext 校验与落盘。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from qq_relay import admin as admin_mod
from qq_relay.admin import AdminContext
from qq_relay.settings_io import (
    read_env,
    update_env,
    update_simple_yaml,
    update_web_sources,
)

SOURCES = """# 采集源
sources:
  - id: jwc
    kind: jwc
    name: 教务处
    root: config/jwc.yml
    interval: 900          # 默认 15 分钟
  - id: labor
    kind: labor
    name: 劳动教育
    root: config/labor.yml
    interval: 900
    enabled: false
"""


class TestSettingsIo:
    def test_env_preserves_comments_and_appends(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "# 模型\nJEV_BASE_URL=https://old.test  # 旧地址\nOTHER=1\n",
            encoding="utf-8")
        update_env(env, {"JEV_BASE_URL": "https://new.test", "ADMIN_QQ": "10001"})
        text = env.read_text(encoding="utf-8")
        assert "# 模型" in text and "# 旧地址" in text
        assert "JEV_BASE_URL=https://new.test" in text
        assert "ADMIN_QQ=10001" in text
        assert read_env(env)["JEV_BASE_URL"] == "https://new.test"

    def test_web_sources_update_and_insert(self, tmp_path):
        p = tmp_path / "web-sources.yml"
        p.write_text(SOURCES, encoding="utf-8")
        update_web_sources(p, {
            "jwc": {"enabled": False, "interval": 1200},
            "labor": {"enabled": True, "interval": 600},
        })
        text = p.read_text(encoding="utf-8")
        assert "# 默认 15 分钟" in text           # 注释保留
        assert "interval: 1200" in text
        assert "enabled: false" in text          # jwc 新增字段
        assert "enabled: true" in text           # labor 原地更新
        # 结构仍能被 YAML 解析
        import yaml
        data = yaml.safe_load(text)
        by_id = {s["id"]: s for s in data["sources"]}
        assert by_id["jwc"]["enabled"] is False
        assert by_id["jwc"]["interval"] == 1200
        assert by_id["labor"]["enabled"] is True
        assert by_id["labor"]["interval"] == 600

    def test_simple_yaml(self, tmp_path):
        p = tmp_path / "wechat-mp.yml"
        p.write_text("# 公众号\nextract_layer: big  # 默认\ninterval: 1800\n",
                     encoding="utf-8")
        update_simple_yaml(p, {"extract_layer": "small", "interval": 900})
        text = p.read_text(encoding="utf-8")
        assert "# 公众号" in text and "# 默认" in text
        assert "extract_layer: small" in text
        assert "interval: 900" in text


class TestAdminSettings:
    def _ctx(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config"
        cfg.mkdir()
        (cfg / "web-sources.yml").write_text(SOURCES, encoding="utf-8")
        (cfg / "wechat-mp.yml").write_text(
            "extract_layer: big\ninterval: 1800\n", encoding="utf-8")
        (cfg / "seu-lectures.yml").write_text('keyword: ""\n', encoding="utf-8")
        (tmp_path / ".env").write_text(
            "PUSHPLUS_TOKEN=old-token\nDELIVER_MODE=file\n", encoding="utf-8")
        settings = SimpleNamespace(
            config_dir=cfg, deliver_mode="file", classifier="stub", admin_qq="",
            reminder_interval=60, pushplus_token="old-token", pushplus_topic="",
            jev_base_url="https://tokenrhythm.studio", jev_api_key="k",
            chat_base_url="https://tokenrhythm.studio", chat_api_key="k",
            chat_model="neohorse-1-9b",
            submit_extract_chain=("vision", "big", "small"),
        )
        monkeypatch.setattr(admin_mod, "runtime_root", lambda: tmp_path)
        return AdminContext(SimpleNamespace(settings=settings), {}, None)

    def test_view_masks_secrets(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch)
        d = ctx.settings_view()
        assert d["env"]["PUSHPLUS_TOKEN_SET"] is True
        assert "PUSHPLUS_TOKEN" not in d["env"]          # 不回明文
        assert d["env"]["DELIVER_MODE"] == ["file"]
        assert d["sources"][0]["id"] == "jwc"

    def test_save_and_blank_secret_keeps_old(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch)
        ctx.save_settings({
            "env": {"DELIVER_MODE": ["file", "pushplus"], "CLASSIFIER": "tree",
                    "ADMIN_QQ": "10001", "REMINDER_OFFSETS": [24, 3],
                    "REMINDER_INTERVAL": 120, "PUSHPLUS_TOKEN": "",
                    "PUSHPLUS_TOPIC": "topic", "JEV_BASE_URL": "https://a.test",
                    "JEV_API_KEY": "", "CHAT_BASE_URL": "",
                    "CHAT_API_KEY": "", "CHAT_MODEL": "m",
                    "SUBMIT_EXTRACT_CHAIN": ["vision", "small"]},
            "sources": [{"id": "jwc", "enabled": False, "interval": 1200},
                        {"id": "labor", "enabled": True, "interval": 600}],
            "wechat": {"extract_layer": "small", "interval": 900},
            "lectures": {"keyword": "AI"},
        })
        env = read_env(tmp_path / ".env")
        assert env["DELIVER_MODE"] == "file,pushplus"
        assert env["CLASSIFIER"] == "tree"
        assert env["REMINDER_INTERVAL"] == "120"
        assert env["PUSHPLUS_TOKEN"] == "old-token"    # 空值不改写
        assert env["PUSHPLUS_TOPIC"] == "topic"
        assert env["SUBMIT_EXTRACT_CHAIN"] == "vision,small"
        assert (tmp_path / "config" / "wechat-mp.yml").read_text(
            encoding="utf-8").count("extract_layer: small") == 1
        assert "keyword: AI" in (tmp_path / "config" / "seu-lectures.yml").read_text(
            encoding="utf-8")

    def test_validation(self, tmp_path, monkeypatch):
        ctx = self._ctx(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            ctx.save_settings({"env": {"DELIVER_MODE": []}})
        with pytest.raises(ValueError):
            ctx.save_settings({"env": {"DELIVER_MODE": ["file"], "KLASS": 1},
                               "sources": [{"id": "nope"}]})
