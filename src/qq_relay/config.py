"""配置加载与校验：.env + YAML → dataclass。

P0 范围：加载 + 校验（未知 cat、缺字段直接 ConfigError，不带病启动）。
P3 将扩展为单一配置管理器（单写者 / 原子写 / 热更新，ADR-018）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# src/qq_relay/config.py → 项目根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CATS = ("homework", "exam", "competition", "research", "exchange", "lecture", "task", "notice", "chat")
ACTIONS = ("submit", "signup", "attend", "know")
GROUP_KINDS = ("course", "grade", "cadre", "class", "program", "club", "other")
SCOPES = ("course", "grade", "class", "school")
FILTER_MODES = ("off", "whitelist", "blacklist")

# 通用预筛词（与群画像词取并集）；groups.yml 的 prefilter_generic 可覆盖
DEFAULT_GENERIC_WORDS: tuple[str, ...] = (
    "通知", "请", "截止", "报名", "提交", "收到请回复", "DDL", "ddl",
    "作业", "考试", "讲座", "竞赛", "收集", "填写", "活动",
)


class ConfigError(Exception):
    """配置缺失或非法——启动期直接失败，不带病运行。"""


def load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")  # 已存在的系统环境变量优先


def _path_from_env(name: str, default: str) -> Path:
    p = Path(os.environ.get(name, default))
    return p if p.is_absolute() else (PROJECT_ROOT / p)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    log_dir: Path
    config_dir: Path
    outbox_dir: Path
    onebot_host: str
    onebot_port: int
    onebot_token: str
    deliver_mode: str
    classifier: str
    admin_qq: str
    jev_base_url: str
    jev_api_key: str
    chat_base_url: str
    chat_api_key: str
    chat_model: str

    @classmethod
    def from_env(cls) -> "Settings":
        load_env()
        deliver_mode = os.environ.get("DELIVER_MODE", "file")
        if deliver_mode not in ("file", "qq"):
            raise ConfigError(f"DELIVER_MODE 只能是 file|qq，当前 {deliver_mode!r}")
        classifier = os.environ.get("CLASSIFIER", "stub")
        if classifier not in ("stub", "tree"):
            raise ConfigError(f"CLASSIFIER 只能是 stub|tree，当前 {classifier!r}")
        return cls(
            data_dir=_path_from_env("DATA_DIR", "./data"),
            log_dir=_path_from_env("LOG_DIR", "./data/logs"),
            config_dir=_path_from_env("CONFIG_DIR", "./config"),
            outbox_dir=_path_from_env("OUTBOX_DIR", "./data/outbox"),
            onebot_host=os.environ.get("ONEBOT_REVERSE_HOST", "127.0.0.1"),
            onebot_port=int(os.environ.get("ONEBOT_REVERSE_PORT", "3001")),
            onebot_token=os.environ.get("ONEBOT_TOKEN", ""),
            deliver_mode=deliver_mode,
            classifier=classifier,
            admin_qq=os.environ.get("ADMIN_QQ", ""),
            jev_base_url=os.environ.get("JEV_BASE_URL", "https://tokenrhythm.studio"),
            jev_api_key=os.environ.get("JEV_API_KEY", ""),
            chat_base_url=os.environ.get("CHAT_BASE_URL", "https://tokenrhythm.studio"),
            chat_api_key=os.environ.get("CHAT_API_KEY", ""),
            chat_model=os.environ.get("CHAT_MODEL", "neohorse-1-9b"),
        )

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.log_dir, self.outbox_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML 解析失败 {path}: {e}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件顶层必须是映射: {path}")
    return data


# ---------------- groups.yml ----------------


@dataclass(frozen=True)
class SenderFilter:
    mode: str = "off"
    whitelist: tuple[str, ...] = ()
    blacklist: tuple[str, ...] = ()
    roles_allow: tuple[str, ...] = ()
    roles_deny: tuple[str, ...] = ()
    dry_run: bool = False
    log_filtered: bool = True

    @classmethod
    def from_dict(cls, d: Optional[dict], gid: str) -> "SenderFilter":
        d = d or {}
        mode = d.get("mode", "off")
        if isinstance(mode, bool):
            # YAML 1.1 会把 off/on 解析成布尔——给出明确提示而不是 cryptic 报错
            if mode:
                raise ConfigError(
                    f"群 {gid} sender_filter.mode：YAML 把 on/off 解析成了布尔值，"
                    f'请给 mode 加引号（mode: "off" / "whitelist" / "blacklist"）')
            mode = "off"
        if mode not in FILTER_MODES:
            raise ConfigError(f"群 {gid} sender_filter.mode 非法: {mode!r}")
        roles = d.get("roles") or {}
        return cls(
            mode=mode,
            whitelist=tuple(str(x) for x in (d.get("whitelist") or [])),
            blacklist=tuple(str(x) for x in (d.get("blacklist") or [])),
            roles_allow=tuple(str(x) for x in (roles.get("allow") or [])),
            roles_deny=tuple(str(x) for x in (roles.get("deny") or [])),
            dry_run=bool(d.get("dry_run", False)),
            log_filtered=bool(d.get("log_filtered", True)),
        )


@dataclass(frozen=True)
class GroupProfile:
    group_id: str
    name: str
    kind: str
    course: Optional[str]
    scope: str
    prefilter: tuple[str, ...]
    default_cats: tuple[str, ...]
    roles: dict[str, str]            # user_id → 角色
    sender_filter: SenderFilter

    def role_of(self, sender_id: str) -> str:
        return self.roles.get(sender_id, "unknown")


@dataclass(frozen=True)
class GroupsConfig:
    groups: dict[str, GroupProfile]
    role_prior: dict[str, tuple[str, ...]]
    generic_words: tuple[str, ...] = DEFAULT_GENERIC_WORDS

    def profile_of(self, group_id: str) -> Optional[GroupProfile]:
        return self.groups.get(group_id)


def load_groups(path: Path) -> GroupsConfig:
    raw = load_yaml(path)
    groups_raw = raw.get("groups") or {}
    if not isinstance(groups_raw, dict):
        raise ConfigError("groups.yml: groups 必须是映射")
    groups: dict[str, GroupProfile] = {}
    for gid, g in groups_raw.items():
        g = g or {}
        kind = g.get("kind", "other")
        if kind not in GROUP_KINDS:
            raise ConfigError(f"群 {gid} kind 非法: {kind!r}")
        scope = g.get("scope", "course" if kind == "course" else "grade")
        if scope not in SCOPES:
            raise ConfigError(f"群 {gid} scope 非法: {scope!r}")
        if kind == "course" and not g.get("course"):
            raise ConfigError(f"群 {gid} kind=course 但未绑定 course")
        cats = tuple(str(c) for c in (g.get("default_cats") or []))
        bad = [c for c in cats if c not in CATS]
        if bad:
            raise ConfigError(f"群 {gid} default_cats 含未知类别: {bad}")
        roles_raw = g.get("roles") or {}
        roles: dict[str, str] = {}
        for uid, spec in roles_raw.items():
            # 支持两种写法："10001": 课程老师  或  "10001": { role: 课程老师, note: 王老师 }
            role = str(spec.get("role", "unknown")) if isinstance(spec, dict) else str(spec)
            roles[str(uid)] = role
        groups[str(gid)] = GroupProfile(
            group_id=str(gid),
            name=str(g.get("name", "")),
            kind=kind,
            course=(str(g["course"]) if g.get("course") else None),
            scope=scope,
            prefilter=tuple(str(w) for w in (g.get("prefilter") or [])),
            default_cats=cats,
            roles=roles,
            sender_filter=SenderFilter.from_dict(g.get("sender_filter"), str(gid)),
        )
    role_prior: dict[str, tuple[str, ...]] = {}
    for role, cats in (raw.get("role_prior") or {}).items():
        cats_t = tuple(str(c) for c in (cats or []))
        if cats_t and cats_t != ("全部",):
            bad = [c for c in cats_t if c not in CATS]
            if bad:
                raise ConfigError(f"role_prior[{role}] 含未知类别: {bad}")
        role_prior[str(role)] = cats_t
    generic = raw.get("prefilter_generic")
    generic_words = tuple(str(w) for w in generic) if generic else DEFAULT_GENERIC_WORDS
    return GroupsConfig(groups=groups, role_prior=role_prior, generic_words=generic_words)


# ---------------- tree.yml ----------------


@dataclass(frozen=True)
class TreeBranch:
    when_cats: tuple[str, ...]
    questions: tuple[str, ...]
    course_noul_when: Optional[str] = None


@dataclass(frozen=True)
class TreeConfig:
    root_questions: tuple[str, ...]
    drop_is_info_below: float
    drop_cats: tuple[str, ...]
    state_max_chars: int
    branches: tuple[TreeBranch, ...]
    extract_fields: dict[str, tuple[str, ...]]
    extract_trigger: str


def load_tree(path: Path) -> TreeConfig:
    raw = load_yaml(path)
    root = raw.get("root") or {}
    questions = tuple(str(q) for q in (root.get("questions") or []))
    if not questions:
        raise ConfigError("tree.yml: root.questions 不能为空")
    drop_if = root.get("drop_if") or {}
    branches: list[TreeBranch] = []
    for b in raw.get("branches") or []:
        when = b.get("when") or {}
        cats = tuple(str(c) for c in (when.get("cat") or []))
        bad = [c for c in cats if c not in CATS]
        if bad:
            raise ConfigError(f"tree.yml 分支 when.cat 含未知类别: {bad}")
        branches.append(TreeBranch(
            when_cats=cats,
            questions=tuple(str(q) for q in (b.get("questions") or [])),
            course_noul_when=(str(b["course_noul_when"]) if b.get("course_noul_when") else None),
        ))
    extract = raw.get("extract") or {}
    fields: dict[str, tuple[str, ...]] = {}
    for cat, fs in (extract.get("fields") or {}).items():
        if cat not in CATS:
            raise ConfigError(f"tree.yml extract.fields 含未知类别: {cat}")
        fields[cat] = tuple(str(f) for f in (fs or []))
    return TreeConfig(
        root_questions=questions,
        drop_is_info_below=float(drop_if.get("is_info_below", 0.6)),
        drop_cats=tuple(str(c) for c in (drop_if.get("cat_in") or [])),
        state_max_chars=int(root.get("state_max_chars", 1500)),
        branches=tuple(branches),
        extract_fields=fields,
        extract_trigger=str(extract.get("trigger", "")),
    )


# ---------------- subscriptions.yml ----------------


@dataclass(frozen=True)
class Subscription:
    user_qq: str
    groups: tuple[str, ...]          # 或 ("*all",)
    cats: tuple[str, ...]
    inc: tuple[str, ...] = ()
    exc: tuple[str, ...] = ()
    quiet: tuple[str, ...] = ()
    instant_min_urg: int = 2
    digest: bool = True


@dataclass(frozen=True)
class SubscriptionsConfig:
    subs: dict[str, Subscription]


def load_subscriptions(path: Path) -> SubscriptionsConfig:
    raw = load_yaml(path)
    subs: dict[str, Subscription] = {}
    for qq, s in (raw.get("subscriptions") or {}).items():
        s = s or {}
        cats = tuple(str(c) for c in (s.get("cats") or []))
        bad = [c for c in cats if c not in CATS]
        if bad:
            raise ConfigError(f"用户 {qq} cats 含未知类别: {bad}")
        kw = s.get("keywords") or {}
        subs[str(qq)] = Subscription(
            user_qq=str(qq),
            groups=tuple(str(g) for g in (s.get("groups") or [])),
            cats=cats,
            inc=tuple(str(w) for w in (kw.get("inc") or [])),
            exc=tuple(str(w) for w in (kw.get("exc") or [])),
            quiet=tuple(str(w) for w in (s.get("quiet") or [])),
            instant_min_urg=int(s.get("instant_min_urg", 2)),
            digest=bool(s.get("digest", True)),
        )
    return SubscriptionsConfig(subs=subs)
