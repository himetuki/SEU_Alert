# -*- coding: utf-8 -*-
"""一次性：修复 groups.yml——把误追加在 role_prior 之后的学院画像移回 groups: 内。"""
import re
from pathlib import Path

p = Path("config/groups.yml")
text = p.read_text(encoding="utf-8")

# 找到 role_prior 顶层键的位置
m = re.search(r"^role_prior:", text, re.M)
if not m:
    raise SystemExit("未找到 role_prior 顶层键")

head, tail = text[:m.start()], text[m.start():]

# 误追加的块：以 "  \"web-" 开头且位于 role_prior 之后的连续行
lines = tail.splitlines()
moved, kept = [], []
in_block = False
for ln in lines:
    if re.match(r'^  "web-[a-z0-9-]+":', ln):
        in_block = True
        moved.append(ln)
        continue
    if in_block:
        # 块内的行：缩进 4 空格且非顶层键
        if ln.startswith("    ") and not re.match(r"^[a-z_]+:", ln):
            moved.append(ln)
            continue
        in_block = False
    kept.append(ln)

if not moved:
    raise SystemExit("没有找到需要移动的块（可能已修复）")

# 插到 head 的 groups: 内（head 末尾即 groups 映射末尾）
new_text = head.rstrip() + "\n" + "\n".join(moved) + "\n\n" + "\n".join(kept)
p.write_text(new_text, encoding="utf-8")
print(f"移动 {sum(1 for l in moved if l.startswith('  \"'))} 个画像回 groups:")
