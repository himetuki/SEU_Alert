# -*- coding: utf-8 -*-
"""一次性：给 groups.yml 追加 ADR-025 的两个画像群。"""
from pathlib import Path

BLOCK = '''
  "web-mp-wzjy":
    name: 东南大学文化素质教育中心（公众号）
    kind: web
    scope: school
    prefilter: [讲座, 活动, 报名, 预约, 素质, 通知, 时间, 地点, 工作台]
    default_cats: [lecture, task, notice]
    roles: {}
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }

  "web-lecture":
    name: 人文讲座（预约系统监控）
    kind: web
    scope: school
    prefilter: [讲座, 预约, 人文, 素质, 时间, 地点, 开放, 余量]
    default_cats: [lecture, task]
    roles: {}
    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }
'''

p = Path("config/groups.yml")
text = p.read_text(encoding="utf-8")
if '"web-mp-wzjy"' not in text:
    p.write_text(text.rstrip() + "\n" + BLOCK, encoding="utf-8")
    print("已追加 web-mp-wzjy / web-lecture 画像")
else:
    print("画像已存在，跳过")
