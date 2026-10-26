# -*- coding: utf-8 -*-
"""一次性：从东南大学官网院系设置页提取学院名单（子域 + 中文名）。"""
import html
import re
from pathlib import Path

raw = Path("data/seu_yxsz.html").read_text(encoding="utf-8", errors="ignore")

# 结构：<a href='http://arch.seu.edu.cn/' target='_blank' title='建筑学院'>
pattern = re.compile(
    r"""href=['"]https?://([a-z0-9-]+)\.seu\.edu\.cn/?['"][^>]*title=['"]([^'"]+)['"]""")
seen: dict[str, str] = {}
for host, name in pattern.findall(raw):
    name = html.unescape(name).strip()
    if host not in seen:
        seen[host] = name

# 行政/服务站点（非学院）
SKIP = {"www", "news", "xxgk", "lib", "jsgzb", "zsb", "i", "mail", "hjlp",
        "yingxin", "yzb", "seugs", "kjc", "opc", "zzb", "zcgs", "jwc"}

colleges = {h: n for h, n in seen.items() if h not in SKIP}
for h, n in sorted(colleges.items(), key=lambda x: x[1]):
    print(f"{h}\t{n}")
print("COLLEGE_TOTAL", len(colleges))
