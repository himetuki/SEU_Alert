"""控制台全量配置：.env 表单 + YAML 结构化字段 + 高级 YAML 编辑器。

返回给前端一份 schema（分组/控件/选项/范围）+ 当前值；保存时先全量校验，
再按文件的原子写落盘。复杂文件（groups/colleges/tree/classification）走
高级 YAML 编辑器，保存前必须能被 yaml.safe_load 解析。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

from . import settings_io

# ---------------------------------------------------------------- env schema

ENV_SCHEMA: list[dict] = [
    # 运行
    {"key": "DELIVER_MODE", "section": "运行", "label": "分发方式", "type": "multi",
     "options": [["file", "文件落盘"], ["pushplus", "PushPlus"], ["qq", "QQ 私聊"]],
     "help": "可多选，至少一个"},
    {"key": "CLASSIFIER", "section": "运行", "label": "分类器", "type": "radio",
     "options": [["stub", "本地规则树"], ["tree", "JEV 分类树"]]},
    {"key": "ADMIN_QQ", "section": "运行", "label": "管理员 QQ", "type": "text",
     "help": "告警/复核接收人，可留空"},
    # OneBot
    {"key": "ONEBOT_REVERSE_HOST", "section": "OneBot", "label": "反向 WS 监听地址",
     "type": "text", "default": "127.0.0.1"},
    {"key": "ONEBOT_REVERSE_PORT", "section": "OneBot", "label": "反向 WS 端口",
     "type": "number", "min": 1, "max": 65535, "default": 3001},
    {"key": "ONEBOT_TOKEN", "section": "OneBot", "label": "OneBot Token",
     "type": "password", "secret": True},
    # 目录
    {"key": "DATA_DIR", "section": "目录", "label": "数据目录", "type": "text",
     "default": "./data"},
    {"key": "LOG_DIR", "section": "目录", "label": "日志目录", "type": "text",
     "default": "./data/logs"},
    {"key": "CONFIG_DIR", "section": "目录", "label": "配置目录", "type": "text",
     "default": "./config"},
    {"key": "OUTBOX_DIR", "section": "目录", "label": "分发输出目录", "type": "text",
     "default": "./data/outbox"},
    # 模型
    {"key": "JEV_BASE_URL", "section": "模型", "label": "JEV Base URL", "type": "url"},
    {"key": "JEV_API_KEY", "section": "模型", "label": "JEV API Key", "type": "password",
     "secret": True},
    {"key": "CHAT_BASE_URL", "section": "模型", "label": "对话模型 Base URL", "type": "url"},
    {"key": "CHAT_API_KEY", "section": "模型", "label": "对话模型 API Key", "type": "password",
     "secret": True},
    {"key": "CHAT_MODEL", "section": "模型", "label": "对话模型名", "type": "text"},
    # 投稿提取栈
    {"key": "SUBMIT_EXTRACT_CHAIN", "section": "投稿提取", "label": "提取链", "type": "multi",
     "options": [["vision", "视觉模型"], ["big", "大模型"], ["small", "小模型"]],
     "help": "按勾选顺序启用"},
    {"key": "VISION_BASE_URL", "section": "投稿提取", "label": "视觉 Base URL", "type": "url"},
    {"key": "VISION_API_KEY", "section": "投稿提取", "label": "视觉 API Key",
     "type": "password", "secret": True},
    {"key": "VISION_MODEL", "section": "投稿提取", "label": "视觉模型名", "type": "text"},
    {"key": "BIG_BASE_URL", "section": "投稿提取", "label": "大模型 Base URL", "type": "url"},
    {"key": "BIG_API_KEY", "section": "投稿提取", "label": "大模型 API Key",
     "type": "password", "secret": True},
    {"key": "BIG_MODEL", "section": "投稿提取", "label": "大模型名", "type": "text"},
    {"key": "SMALL_BASE_URL", "section": "投稿提取", "label": "小模型 Base URL", "type": "url"},
    {"key": "SMALL_API_KEY", "section": "投稿提取", "label": "小模型 API Key",
     "type": "password", "secret": True},
    {"key": "SMALL_MODEL", "section": "投稿提取", "label": "小模型名", "type": "text",
     "default": "neohorse-1-9b"},
    # OCR
    {"key": "OCR_PROVIDER", "section": "OCR", "label": "OCR 提供方", "type": "radio",
     "options": [["none", "不用"], ["http", "通用 HTTP"], ["xunfei", "讯飞"]]},
    {"key": "OCR_BASE_URL", "section": "OCR", "label": "OCR 端点", "type": "url"},
    {"key": "OCR_API_KEY", "section": "OCR", "label": "OCR API Key", "type": "password",
     "secret": True},
    {"key": "OCR_API_SECRET", "section": "OCR", "label": "OCR APISecret",
     "type": "password", "secret": True},
    {"key": "OCR_ENGINE_ID", "section": "OCR", "label": "OCR 引擎 ID", "type": "text",
     "default": "sf8e6aca1"},
    # 推送
    {"key": "PUSHPLUS_TOKEN", "section": "PushPlus", "label": "Token",
     "type": "password", "secret": True},
    {"key": "PUSHPLUS_TOPIC", "section": "PushPlus", "label": "群组主题", "type": "text"},
    # 提醒
    {"key": "REMINDER_OFFSETS", "section": "临期提醒", "label": "提前提醒",
     "type": "offsets", "help": "两轮，单位小时（1–168）"},
    {"key": "REMINDER_INTERVAL", "section": "临期提醒", "label": "扫描间隔",
     "type": "slider", "min": 15, "max": 600, "step": 5, "unit": "秒", "default": 60},
    # 讲座会话
    {"key": "SEU_LECTURE_USERNAME", "section": "讲座会话", "label": "一卡通号",
     "type": "text"},
    {"key": "SEU_LECTURE_PASSWORD", "section": "讲座会话", "label": "统一认证密码",
     "type": "password", "secret": True},
    {"key": "SEU_LECTURE_COOKIES", "section": "讲座会话", "label": "Cookie",
     "type": "password", "secret": True},
    # 劳动教育
    {"key": "LABOR_USERNAME", "section": "劳动教育", "label": "一卡通号", "type": "text"},
    {"key": "LABOR_PASSWORD", "section": "劳动教育", "label": "统一认证密码",
     "type": "password", "secret": True},
    {"key": "LABOR_COOKIES", "section": "劳动教育", "label": "Cookie",
     "type": "password", "secret": True},
    {"key": "LABOR_COOKIE_FILE", "section": "劳动教育", "label": "Cookie 文件路径",
     "type": "text"},
]

_KNOWN = {item["key"] for item in ENV_SCHEMA}
_SECRET_RE = re.compile(r"TOKEN|SECRET|PASSWORD|COOKIES|API_KEY", re.I)

RAW_FILES = ("groups.yml", "colleges.yml", "tree.yml", "classification.yml")

CATS = ("homework", "exam", "competition", "research", "exchange",
        "lecture", "task", "notice", "chat")
KINDS = ("course", "grade", "cadre", "class", "program", "club", "other")
SCOPES = ("course", "grade", "class", "school")
ACTIONS = ("submit", "signup", "attend", "know")
FILTER_MODES = ("off", "whitelist", "blacklist")


def _split(value: str) -> list[str]:
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _cats(value) -> list[str]:
    return [str(x) for x in (value or []) if str(x) in CATS]


def _norm_groups(raw: dict) -> dict:
    groups = []
    for gid, g in (raw.get("groups") or {}).items():
        if not isinstance(g, dict):
            continue
        sf = g.get("sender_filter") or {}
        roles = g.get("roles") or {}
        groups.append({
            "id": str(gid),
            "name": str(g.get("name") or ""),
            "kind": str(g.get("kind") or "other"),
            "course": str(g.get("course") or ""),
            "scope": str(g.get("scope") or "school"),
            "prefilter": [str(x) for x in (g.get("prefilter") or [])],
            "default_cats": _cats(g.get("default_cats")),
            "roles": [{"user_id": str(k), "role": str(v.get("role") or ""),
                       "note": str(v.get("note") or "")}
                      for k, v in roles.items() if isinstance(v, dict)],
            "filter_mode": str(sf.get("mode") or "off"),
            "whitelist": [str(x) for x in (sf.get("whitelist") or [])],
            "blacklist": [str(x) for x in (sf.get("blacklist") or [])],
            "roles_allow": [str(x) for x in ((sf.get("roles") or {}).get("allow") or [])],
            "roles_deny": [str(x) for x in ((sf.get("roles") or {}).get("deny") or [])],
            "dry_run": bool(sf.get("dry_run", False)),
            "log_filtered": bool(sf.get("log_filtered", True)),
        })
    prior = [{"role": str(k), "cats": _cats(v)}
             for k, v in (raw.get("role_prior") or {}).items()]
    return {"groups": groups, "role_prior": prior}


def _norm_colleges(raw: dict) -> list[dict]:
    out = []
    for c in raw.get("colleges") or []:
        if isinstance(c, dict):
            out.append({"key": str(c.get("key") or ""),
                        "name": str(c.get("name") or ""),
                        "list": str(c.get("list") or ""),
                        "prefilter": [str(x) for x in (c.get("prefilter") or [])]})
    return out


def _norm_tree(raw: dict) -> dict:
    cats = raw.get("categories") or {}
    categories = []
    for cat in CATS:
        item = cats.get(cat) or {}
        categories.append({"cat": cat,
                           "label": str(item.get("label") or cat),
                           "criteria": str(item.get("criteria") or "")})
    root = raw.get("root") or {}
    drop = root.get("drop_if") or {}
    branches = []
    for b in raw.get("branches") or []:
        if isinstance(b, dict):
            branches.append({
                "cats": _cats((b.get("when") or {}).get("cat")),
                "questions": [str(x) for x in (b.get("questions") or [])],
                "course_noul_when": str(b.get("course_noul_when") or ""),
            })
    extract = raw.get("extract") or {}
    fields = extract.get("fields") or {}
    return {
        "categories": categories,
        "cat2_policy": str(raw.get("cat2_policy") or ""),
        "thresholds": {"is_info_below": float((raw.get("thresholds") or {}).get("is_info_below", 0.6)),
                       "low_conf_margin": float((raw.get("thresholds") or {}).get("low_conf_margin", 0.15))},
        "root": {"call": str(root.get("call") or "jev"),
                 "questions": [str(x) for x in (root.get("questions") or [])],
                 "is_info_below": float(drop.get("is_info_below", 0.6)),
                 "drop_cats": _cats(drop.get("cat_in")),
                 "state_max_chars": int(root.get("state_max_chars") or 1500)},
        "branches": branches,
        "extract": {"trigger": str(extract.get("trigger") or ""),
                    "call": str(extract.get("call") or "chat"),
                    "fields": {cat: [str(x) for x in (fields.get(cat) or [])]
                               for cat in CATS},
                    "fallback": str(extract.get("fallback") or "")},
    }


def _norm_classification(raw: dict) -> dict:
    ov = raw.get("overrides") or {}
    fb = raw.get("fallback") or {}
    source_cats = [{"source": str(k), "cats": _cats(v)}
                   for k, v in (raw.get("source_categories") or {}).items()]
    group_cats = [{"group": str(k), "cats": _cats(v)}
                  for k, v in (raw.get("group_categories") or {}).items()]
    prefix = [{"prefix": str(k), "cat": str(v)}
              for k, v in (raw.get("prefix_categories") or {}).items()
              if str(v) in CATS]
    rules = []
    for r in raw.get("rules") or []:
        if not isinstance(r, dict) or str(r.get("cat")) not in CATS:
            continue
        rules.append({
            "cat": str(r.get("cat")),
            "priority": int(r.get("priority") or 0),
            "urg": int(r.get("urg") or 1),
            "action": str(r.get("action") or "know"),
            "keywords": [str(x) for x in (r.get("keywords") or [])],
            "exclude": [str(x) for x in (r.get("exclude") or [])],
        })
    return {
        "version": int(raw.get("version") or 1),
        "fallback": {"cat": str(fb.get("cat") or "notice"),
                     "urg": int(fb.get("urg") or 1),
                     "action": str(fb.get("action") or "know")},
        "source_categories": source_cats,
        "group_categories": group_cats,
        "notice_title": [str(x) for x in (ov.get("notice_title") or [])],
        "news_title": [str(x) for x in (ov.get("news_title") or [])],
        "prefix_categories": prefix,
        "rules": rules,
    }


# ---------------------------------------------------------------- read

def read_settings(env_path: Path, config_dir: Path) -> dict:
    env = settings_io.read_env(env_path)
    values: dict[str, object] = {}
    secret_set: dict[str, bool] = {}
    for item in ENV_SCHEMA:
        key = item["key"]
        raw = env.get(key, "")
        if item.get("secret"):
            secret_set[key] = bool(raw)
            values[key] = ""
        elif item["type"] == "multi":
            values[key] = _split(raw)
        elif item["type"] == "offsets":
            offsets = []
            for x in _split(raw):
                try:
                    offsets.append(int(x))
                except ValueError:
                    continue
            values[key] = offsets or [24, 3]
        elif item["type"] in ("number", "slider"):
            values[key] = _int(raw, int(item.get("default", 0)))
        else:
            values[key] = raw
        if item.get("secret"):
            values[f"{key}_SET"] = secret_set[key]

    # 未在 schema 中的 .env 键：也放进「其他」，做到全量可见
    extras = []
    for key, raw in env.items():
        if key in _KNOWN:
            continue
        secret = bool(_SECRET_RE.search(key))
        extras.append({"key": key, "value": "" if secret else raw, "secret": secret,
                       "set": bool(raw) if secret else None})
        if secret:
            values[f"{key}_SET"] = bool(raw)

    wechat = settings_io.read_yaml(config_dir / "wechat-mp.yml")
    jwc = settings_io.read_yaml(config_dir / "jwc.yml")
    lecture_site = settings_io.read_yaml(config_dir / "lecture-site.yml")
    labor = settings_io.read_yaml(config_dir / "labor.yml")
    lectures = settings_io.read_yaml(config_dir / "seu-lectures.yml")

    def _accounts(value) -> list[dict]:
        out = []
        for a in value or []:
            if isinstance(a, dict):
                out.append({"key": str(a.get("key") or ""),
                            "name": str(a.get("name") or ""),
                            "group_id": str(a.get("group_id") or "")})
        return out

    def _columns(value) -> list[dict]:
        out = []
        for c in value or []:
            if isinstance(c, dict):
                out.append({"id": str(c.get("id") or ""),
                            "name": str(c.get("name") or ""),
                            "url": str(c.get("url") or "")})
        return out

    groups_raw = settings_io.read_yaml(config_dir / "groups.yml")
    colleges_raw = settings_io.read_yaml(config_dir / "colleges.yml")
    tree_raw = settings_io.read_yaml(config_dir / "tree.yml")
    cls_raw = settings_io.read_yaml(config_dir / "classification.yml")

    return {
        "env": values,
        "env_schema": ENV_SCHEMA,
        "env_extras": extras,
        "sources": [{
            "id": src.id, "name": src.name, "kind": src.kind,
            "enabled": src.enabled, "interval": src.interval,
        } for src in _sources(config_dir)],
        "yaml": {
            "wechat": {
                "accounts": _accounts(wechat.get("accounts")),
                "extract_layer": str(wechat.get("extract_layer") or "big"),
                "interval": _int(wechat.get("interval"), 1800),
            },
            "jwc": {
                "base_url": str(jwc.get("base_url") or "https://jwc.seu.edu.cn"),
                "columns": _columns(jwc.get("columns")),
            },
            "lecture_site": {
                "group_id": str(lecture_site.get("group_id") or "web-lecture"),
                "group_name": str(lecture_site.get("group_name") or "人文讲座"),
                "columns": _columns(lecture_site.get("columns")),
            },
            "labor": {
                "location_whitelist": [str(x) for x in
                                       ((labor.get("filters") or {}).get("location_whitelist") or [])],
                "category_blacklist": [str(x) for x in
                                       ((labor.get("filters") or {}).get("category_blacklist") or [])],
            },
            "seu_lectures": {"keyword": str(lectures.get("keyword") or "")},
        },
        "groups": _norm_groups(groups_raw),
        "colleges": _norm_colleges(colleges_raw),
        "tree": _norm_tree(tree_raw),
        "classification": _norm_classification(cls_raw),
        "defaults": {
            "env": {
                "DELIVER_MODE": ["file"], "CLASSIFIER": "stub", "ADMIN_QQ": "",
                "REMINDER_OFFSETS": [24, 3], "REMINDER_INTERVAL": 60,
                "SUBMIT_EXTRACT_CHAIN": ["vision", "big", "small"],
                "CHAT_MODEL": "neohorse-1-9b",
                "ONEBOT_REVERSE_HOST": "127.0.0.1", "ONEBOT_REVERSE_PORT": 3001,
                **{item["key"]: item["default"]
                   for item in ENV_SCHEMA if "default" in item},
            },
            "source_interval": 900,
            "wechat": {"extract_layer": "big", "interval": 1800},
            "labor": {"location_whitelist": [], "category_blacklist": []},
            "seu_lectures": {"keyword": ""},
        },
    }


def _sources(config_dir: Path):
    from .config import load_web_sources
    return load_web_sources(config_dir / "web-sources.yml").sources


# ---------------------------------------------------------------- save

def _require_http(url: str, field: str) -> str:
    url = url.strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        raise ValueError(f"{field} 必须以 http:// 或 https:// 开头")
    return url


def _clean(value) -> str:
    text = str(value or "").strip()
    if "\n" in text or "\r" in text:
        raise ValueError("配置值不能包含换行")
    return text


def _str_list(value, field: str) -> list[str]:
    if not isinstance(value, list):
        value = _split(str(value or ""))
    return [_clean(x) for x in value if _clean(x)]


def _dump_with_header(path: Path, data: dict) -> str:
    header = ""
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()
        block = []
        for line in lines:
            if line.strip().startswith("#") or not line.strip():
                block.append(line)
            else:
                break
        header = "\n".join(block).rstrip() + "\n\n" if block else ""
    return header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def _build_groups(payload: dict) -> dict:
    data = payload.get("groups") or {}
    rows = data.get("groups") or []
    out: dict[str, dict] = {}
    for g in rows:
        gid = _clean(g.get("id"))
        name = _clean(g.get("name"))
        if not gid or not name:
            raise ValueError("群画像需要群号/群名")
        if gid in out:
            raise ValueError(f"群号重复：{gid}")
        kind = str(g.get("kind") or "other")
        if kind not in KINDS:
            raise ValueError(f"{gid} 的 kind 非法")
        scope = str(g.get("scope") or "school")
        if scope not in SCOPES:
            raise ValueError(f"{gid} 的 scope 非法")
        mode = str(g.get("filter_mode") or "off")
        if mode not in FILTER_MODES:
            raise ValueError(f"{gid} 的发送者过滤模式非法")
        item = {
            "name": name, "kind": kind, "scope": scope,
            "prefilter": _str_list(g.get("prefilter"), "prefilter"),
            "default_cats": _cats(g.get("default_cats")),
            "roles": {_clean(r.get("user_id")): {
                "role": _clean(r.get("role")), "note": _clean(r.get("note"))}
                for r in (g.get("roles") or []) if _clean(r.get("user_id"))},
            "sender_filter": {
                "mode": mode,
                "whitelist": _str_list(g.get("whitelist"), "whitelist"),
                "blacklist": _str_list(g.get("blacklist"), "blacklist"),
                "roles": {"allow": _str_list(g.get("roles_allow"), "roles.allow"),
                          "deny": _str_list(g.get("roles_deny"), "roles.deny")},
                "dry_run": bool(g.get("dry_run")),
                "log_filtered": bool(g.get("log_filtered", True)),
            },
        }
        course = _clean(g.get("course"))
        if course:
            item["course"] = course
        out[gid] = item
    prior = {}
    for r in data.get("role_prior") or []:
        role = _clean(r.get("role"))
        if role:
            prior[role] = _cats(r.get("cats"))
    return {"groups": out, "role_prior": prior}


def _build_colleges(payload: list) -> dict:
    out, seen = [], set()
    for c in payload or []:
        key, name = _clean(c.get("key")), _clean(c.get("name"))
        url = _require_http(_clean(c.get("list")), "学院列表页")
        if not key or not name or not url:
            raise ValueError("学院需要 key / name / list")
        if key in seen:
            raise ValueError(f"学院 key 重复：{key}")
        seen.add(key)
        out.append({"key": key, "name": name, "list": url,
                    "prefilter": _str_list(c.get("prefilter"), "prefilter")})
    return {"colleges": out}


def _build_tree(payload: dict) -> dict:
    cats = {str(c.get("cat")): {"label": _clean(c.get("label")),
                                "criteria": _clean(c.get("criteria"))}
            for c in payload.get("categories") or []}
    missing = [c for c in CATS if c not in cats]
    if missing:
        raise ValueError(f"JEV 类别缺失：{missing}")
    th = payload.get("thresholds") or {}
    is_info = float(th.get("is_info_below", 0.6))
    margin = float(th.get("low_conf_margin", 0.15))
    if not 0 <= is_info <= 1 or not 0 <= margin <= 1:
        raise ValueError("JEV 阈值需在 0–1 之间")
    root = payload.get("root") or {}
    chars = int(root.get("state_max_chars") or 1500)
    if not 200 <= chars <= 5000:
        raise ValueError("state_max_chars 需在 200–5000")
    branches = []
    for b in payload.get("branches") or []:
        bcats = _cats(b.get("cats"))
        if not bcats:
            raise ValueError("JEV 分支至少选择一个类别")
        item = {"when": {"cat": bcats},
                "questions": _str_list(b.get("questions"), "questions")}
        note = _clean(b.get("course_noul_when"))
        if note:
            item["course_noul_when"] = note
        branches.append(item)
    ex = payload.get("extract") or {}
    fields = {cat: _str_list((ex.get("fields") or {}).get(cat), "fields")
              for cat in CATS}
    return {
        "categories": cats,
        "cat2_policy": _clean(payload.get("cat2_policy")),
        "thresholds": {"is_info_below": is_info, "low_conf_margin": margin},
        "root": {"call": _clean(root.get("call")) or "jev",
                 "questions": _str_list(root.get("questions"), "questions"),
                 "drop_if": {"is_info_below": float(root.get("is_info_below", is_info)),
                             "cat_in": _cats(root.get("drop_cats"))},
                 "state_max_chars": chars},
        "branches": branches,
        "extract": {"trigger": _clean(ex.get("trigger")),
                    "call": _clean(ex.get("call")) or "chat",
                    "fields": fields,
                    "fallback": _clean(ex.get("fallback"))},
    }


def _build_classification(payload: dict) -> dict:
    rules = []
    for r in payload.get("rules") or []:
        cat = str(r.get("cat") or "")
        if cat not in CATS:
            raise ValueError(f"规则类别非法：{cat}")
        action = str(r.get("action") or "know")
        if action not in ACTIONS:
            raise ValueError(f"规则动作非法：{action}")
        keywords = _str_list(r.get("keywords"), "keywords")
        if not keywords:
            raise ValueError(f"{cat} 规则的关键词不能为空")
        rules.append({"cat": cat, "priority": int(r.get("priority") or 0),
                      "urg": int(r.get("urg") or 0), "action": action,
                      "keywords": keywords,
                      "exclude": _str_list(r.get("exclude"), "exclude")})
    if not rules:
        raise ValueError("至少保留一条分类规则")

    source_cats = {}
    for row in payload.get("source_categories") or []:
        source = _clean(row.get("source"))
        cats = _cats(row.get("cats"))
        if not source or not cats:
            raise ValueError("来源白名单需要来源名与至少一个类别")
        source_cats[source] = cats
    group_cats = {}
    for row in payload.get("group_categories") or []:
        group = _clean(row.get("group"))
        cats = _cats(row.get("cats"))
        if not group or not cats:
            raise ValueError("频道白名单需要频道名与至少一个类别")
        group_cats[group] = cats
    prefix = {}
    for row in payload.get("prefix_categories") or []:
        name, cat = _clean(row.get("prefix")), str(row.get("cat") or "")
        if not name or cat not in CATS:
            raise ValueError("栏目前缀映射非法")
        prefix[name] = cat
    fb = payload.get("fallback") or {}
    if str(fb.get("cat")) not in CATS:
        raise ValueError("默认类别非法")
    return {
        "version": int(payload.get("version") or 1),
        "fallback": {"cat": str(fb.get("cat")), "urg": int(fb.get("urg") or 0),
                     "action": str(fb.get("action") or "know")},
        "source_categories": source_cats,
        "group_categories": group_cats,
        "overrides": {"notice_title": _str_list(payload.get("notice_title"), "notice_title"),
                      "news_title": _str_list(payload.get("news_title"), "news_title")},
        "prefix_categories": prefix,
        "rules": rules,
    }


def save_settings(env_path: Path, config_dir: Path, payload: dict) -> dict:
    env_in = payload.get("env") or {}
    updates: dict[str, str] = {}

    for item in ENV_SCHEMA:
        key, kind = item["key"], item["type"]
        if key not in env_in:
            continue
        val = env_in[key]
        if kind == "multi":
            allowed = [x[0] for x in item["options"]]
            chosen = [x for x in (val or []) if x in allowed]
            if not chosen:
                raise ValueError(f"{item['label']} 至少选择一个")
            updates[key] = ",".join(chosen)
        elif kind == "radio":
            allowed = [x[0] for x in item["options"]]
            if str(val) not in allowed:
                raise ValueError(f"{item['label']} 选项非法")
            updates[key] = str(val)
        elif kind in ("number", "slider"):
            v = int(val)
            if not int(item.get("min", v)) <= v <= int(item.get("max", v)):
                raise ValueError(f"{item['label']} 超出范围")
            updates[key] = str(v)
        elif kind == "offsets":
            offsets = [int(x) for x in (val or [])]
            if not offsets or len(offsets) > 4 or any(not 1 <= x <= 168 for x in offsets):
                raise ValueError("提醒提前量需 1–4 个、每个 1–168 小时")
            updates[key] = ",".join(str(x) for x in offsets)
        elif item.get("secret"):
            v = _clean(val)
            if v:                                   # 留空 = 保持原值
                updates[key] = v
        elif kind == "url":
            updates[key] = _require_http(_clean(val), item["label"])
        else:
            updates[key] = _clean(val)

    # 其他（非 schema）键：允许更新 .env 中已存在的键，避免误写任意变量
    existing = set(settings_io.read_env(env_path))
    known = _KNOWN | existing | {x["key"] for x in (payload.get("env_extras") or [])}
    for key, val in env_in.items():
        if key in known and key not in updates and not key.endswith("_SET"):
            v = _clean(val)
            if v:
                updates[key] = v

    # ---- YAML 结构化 ----
    y = payload.get("yaml") or {}
    # 兼容旧 payload（wechat/lectures 顶层）
    if not y.get("wechat") and payload.get("wechat"):
        y["wechat"] = payload["wechat"]
    if not y.get("seu_lectures") and payload.get("lectures"):
        y["seu_lectures"] = payload["lectures"]
    writes: list[tuple[Path, str]] = []

    wechat_in = y.get("wechat") or {}
    if wechat_in:
        if "accounts" in wechat_in:
            raw_accounts = wechat_in.get("accounts") or []
        else:                                   # 只改 layer/interval 时保留原账号
            raw_accounts = (settings_io.read_yaml(
                config_dir / "wechat-mp.yml").get("accounts") or [])
        accounts = []
        for a in raw_accounts:
            name = _clean(a.get("name"))
            if not name:
                continue
            accounts.append({
                "key": _clean(a.get("key")) or re.sub(r"\W+", "", name)[:8],
                "name": name,
                "group_id": _clean(a.get("group_id")),
            })
        layer = str(wechat_in.get("extract_layer") or "big")
        if layer not in ("big", "small"):
            raise ValueError("公众号提取层只能是 big 或 small")
        interval = int(wechat_in.get("interval") or 1800)
        if not 60 <= interval <= 86400:
            raise ValueError("公众号扫描间隔需在 60–86400 秒")
        writes.append((config_dir / "wechat-mp.yml", _dump_with_header(
            config_dir / "wechat-mp.yml",
            {"accounts": accounts, "extract_layer": layer, "interval": interval})))

    jwc_in = y.get("jwc") or {}
    if jwc_in:
        columns = []
        for c in jwc_in.get("columns") or []:
            cid, name = _clean(c.get("id")), _clean(c.get("name"))
            url = _require_http(_clean(c.get("url")), "教务处栏目 URL")
            if cid and name and url:
                columns.append({"id": cid, "name": name, "url": url})
        if not columns:
            raise ValueError("教务处至少保留一个栏目")
        base = _require_http(_clean(jwc_in.get("base_url")), "教务处 Base URL")
        writes.append((config_dir / "jwc.yml", _dump_with_header(
            config_dir / "jwc.yml", {"base_url": base, "columns": columns})))

    ls_in = y.get("lecture_site") or {}
    if ls_in:
        columns = []
        for c in ls_in.get("columns") or []:
            cid, name = _clean(c.get("id")), _clean(c.get("name"))
            url = _require_http(_clean(c.get("url")), "讲座栏目 URL")
            if cid and name and url:
                columns.append({"id": cid, "name": name, "url": url})
        if not columns:
            raise ValueError("讲座网站至少保留一个栏目")
        writes.append((config_dir / "lecture-site.yml", _dump_with_header(
            config_dir / "lecture-site.yml", {
                "group_id": _clean(ls_in.get("group_id")) or "web-lecture",
                "group_name": _clean(ls_in.get("group_name")) or "人文讲座",
                "columns": columns,
            })))

    labor_in = y.get("labor") or {}
    if labor_in:
        writes.append((config_dir / "labor.yml", _dump_with_header(
            config_dir / "labor.yml", {"filters": {
                "location_whitelist": _str_list(
                    labor_in.get("location_whitelist"), "地点白名单"),
                "category_blacklist": _str_list(
                    labor_in.get("category_blacklist"), "类别黑名单"),
            }})))

    lec_in = y.get("seu_lectures") or {}
    if lec_in:
        settings_io.update_simple_yaml(
            config_dir / "seu-lectures.yml",
            {"keyword": _clean(lec_in.get("keyword"))})

    # 分组白名单
    valid_ids = {src.id for src in _sources(config_dir)}
    src_changes: dict[str, dict] = {}
    for item in payload.get("sources") or []:
        sid = _clean(item.get("id"))
        if sid not in valid_ids:
            raise ValueError(f"未知采集源：{sid}")
        interval = int(item.get("interval") or 900)
        if not 60 <= interval <= 86400:
            raise ValueError(f"{sid} 的扫描间隔需在 60–86400 秒")
        src_changes[sid] = {"enabled": bool(item.get("enabled")), "interval": interval}

    # 复杂 YAML：先构建并校验，再与其它文件一起落盘
    complex_writes: list[tuple[Path, str]] = []
    if payload.get("groups") is not None:
        complex_writes.append((config_dir / "groups.yml", _dump_with_header(
            config_dir / "groups.yml", _build_groups(payload))))
    if payload.get("colleges") is not None:
        complex_writes.append((config_dir / "colleges.yml", _dump_with_header(
            config_dir / "colleges.yml", _build_colleges(payload.get("colleges")))))
    if payload.get("tree") is not None:
        complex_writes.append((config_dir / "tree.yml", _dump_with_header(
            config_dir / "tree.yml", _build_tree(payload.get("tree")))))
    if payload.get("classification") is not None:
        complex_writes.append((config_dir / "classification.yml", _dump_with_header(
            config_dir / "classification.yml",
            _build_classification(payload.get("classification")))))

    # ---- 全部校验通过后落盘 ----
    settings_io.update_env(env_path, updates)
    settings_io.update_web_sources(config_dir / "web-sources.yml", src_changes)
    for path, text in writes:
        settings_io.write_text(path, text)
    for path, text in complex_writes:
        settings_io.write_text(path, text)

    return {"updated": ["env", "web-sources.yml"] +
            [p.name for p, _ in writes] + [p.name for p, _ in complex_writes]}