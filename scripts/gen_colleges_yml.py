# -*- coding: utf-8 -*-
"""一次性：由 data/colleges-fixed.tsv 生成 config/colleges.yml（33 个学院）。"""
from pathlib import Path

HEADER = """# 东南大学各学院通知采集配置（ADR-024：全院系覆盖 + 按学院订阅）
# 来源：东南大学官网院系设置页自动发现（scripts/discover_colleges.py，2026-10-26）
# 未发现列表页的学院（chem/math/futuretech/bme）暂缺，发现后手动补一条即可。
# 字段：key=群后缀（web-<key>） name=学院名 list=通知列表页 prefilter=画像预筛词
"""

PREFILTER = ("通知,公告,报名,截止,公示,选拔,考试,讲座,竞赛,提交,答辩,免试,"
             "成绩,调课,选课,公示,招聘,科研")

rows = []
for line in Path("data/colleges-fixed.tsv").read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    host, name, url = parts
    if url.startswith("#"):
        continue
    rows.append((host, name, url))

lines = [HEADER, "colleges:"]
for host, name, url in sorted(rows, key=lambda r: r[1]):
    lines.append(f'  - key: {host}')
    lines.append(f'    name: {name}')
    lines.append(f'    list: {url}')
    lines.append(f'    prefilter: [{PREFILTER}]')
out = Path("config/colleges.yml")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"生成 {out}: {len(rows)} 个学院")
