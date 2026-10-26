# -*- coding: utf-8 -*-
"""一次性：把 33 个学院画像追加进 config/groups.yml（web-<key>，kind=web）。"""
import re
from pathlib import Path

PREFILTER = ("通知,公告,报名,截止,公示,选拔,考试,讲座,竞赛,提交,答辩,免试,"
             "成绩,调课,选课,招聘,科研")

groups = Path("config/groups.yml")
text = groups.read_text(encoding="utf-8")
existing = set(re.findall(r'^  "(web-[a-z0-9-]+)":', text, re.M))

lines = ["\n# ---- 各学院站点画像（ADR-024，scripts/gen_colleges_yml.py 生成）----"]
added = 0
for line in Path("data/colleges-fixed.tsv").read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    host, name, url = parts
    if url.startswith("#"):
        continue
    gid = f"web-{host}"
    if gid in existing:
        continue
    lines += [
        f'  "{gid}":',
        f'    name: {name}',
        '    kind: web',
        '    scope: school',
        f'    prefilter: [{PREFILTER}]',
        '    default_cats: [notice, task, lecture, competition, exam]',
        '    roles: {}',
        '    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }',
    ]
    added += 1

# 劳动教育平台画像
if '"web-labor"' not in existing:
    lines += [
        '  "web-labor":',
        '    name: 劳动教育课程平台',
        '    kind: web',
        '    scope: school',
        '    prefilter: [选课, 报名, 新增课程, 劳动教育, 余量, 截止]',
        '    default_cats: [task, lecture]',
        '    roles: {}',
        '    sender_filter: { mode: "off", whitelist: [], blacklist: [], roles: { allow: [], deny: [] }, dry_run: false, log_filtered: true }',
    ]
    added += 1

groups.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n",
                  encoding="utf-8")
print(f"groups.yml 追加 {added} 个画像")
