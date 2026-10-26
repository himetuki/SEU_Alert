# -*- coding: utf-8 -*-
"""一次性：修复发现脚本的 URL（补 .seu.edu.cn 后缀）并输出 colleges.yml 数据。"""
import re
from pathlib import Path

rows = []
for line in Path("data/colleges-notices.tsv").read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    host, name, url = parts
    if url.startswith("#"):
        rows.append((host, name, url))
        continue
    # https://smjgs/8446/list.htm -> https://smjgs.seu.edu.cn/8446/list.htm
    fixed = re.sub(r"^(https?://)([a-z0-9-]+)/(.*)$",
                   lambda m: f"{m.group(1)}{m.group(2)}.seu.edu.cn/{m.group(3)}"
                   if "." not in m.group(2) else m.group(0), url)
    rows.append((host, name, fixed))

out = Path("data/colleges-fixed.tsv")
out.write_text("\n".join(f"{h}\t{n}\t{u}" for h, n, u in rows) + "\n",
               encoding="utf-8")
ok = sum(1 for _, _, u in rows if not u.startswith("#"))
print(f"修复完成：{ok} 个可用，{len(rows) - ok} 个未发现 → {out}")
