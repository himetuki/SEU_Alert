"""P1 测试共享 fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest

from qq_relay.config import (
    GroupsConfig,
    Settings,
    SubscriptionsConfig,
    Subscription,
    load_groups,
)

GROUPS_YAML = """
groups:
  "111":
    name: 马原群
    kind: course
    course: 马原
    scope: course
    prefilter: [作业, 截止, 考试]
    default_cats: [homework, exam]
    roles:
      "10001": { role: 课程老师, note: 王老师 }
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
  "222":
    name: 2024级年级群
    kind: grade
    scope: grade
    prefilter: [竞赛, 报名, 收集, 活动]
    default_cats: [competition, task, lecture, notice]
    roles: {}
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
  "333":
    name: 黑名单群
    kind: other
    scope: grade
    prefilter: []
    roles: {}
    sender_filter: { mode: blacklist, blacklist: ["999"], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
  "444":
    name: 干跑群
    kind: other
    scope: grade
    prefilter: []
    roles: {}
    sender_filter: { mode: blacklist, blacklist: ["999"], roles: { allow: [], deny: [] }, dry_run: true, log_filtered: true }
  "web-jwc":
    name: 教务处（jwc.seu.edu.cn）
    kind: web
    scope: school
    prefilter: [通知, 报名, 申请, 截止, 公示, 选拔, 考试, 讲座, 竞赛, 选课, 成绩, 毕业, 答辩, 补考]
    default_cats: [notice, exam, lecture, competition, task, exchange]
    roles: {}
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
  "web-cse":
    name: 计软智学院（cse.seu.edu.cn）
    kind: web
    scope: school
    prefilter: [通知, 公示, 报名, 截止, 答辩, 免推, 免试, 招聘, 讲座, 竞赛, 科研, 转专业]
    default_cats: [notice, task, lecture, competition, research]
    roles: {}
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
role_prior:
  课程老师: [homework, exam]
  unknown: [全部]
"""


@pytest.fixture
def groups_yaml_path(tmp_path) -> Path:
    p = tmp_path / "groups.yml"
    p.write_text(GROUPS_YAML, encoding="utf-8")
    return p


@pytest.fixture
def groups_cfg(groups_yaml_path) -> GroupsConfig:
    return load_groups(groups_yaml_path)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "data" / "logs",
        config_dir=tmp_path / "config",
        outbox_dir=tmp_path / "data" / "outbox",
        onebot_host="127.0.0.1", onebot_port=0, onebot_token="",
        deliver_mode="file", classifier="stub", admin_qq="",
        jev_base_url="", jev_api_key="",
        chat_base_url="", chat_api_key="", chat_model="",
    )


@pytest.fixture
def subs_cfg() -> SubscriptionsConfig:
    return SubscriptionsConfig(subs={
        "100001": Subscription(
            user_qq="100001", groups=("111",), cats=("homework", "exam"),
            quiet=(), instant_min_urg=2, digest=True),
        "100002": Subscription(
            user_qq="100002", groups=("222",), cats=("competition",),
            quiet=(), instant_min_urg=2, digest=True),
    })
