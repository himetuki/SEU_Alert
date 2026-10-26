# -*- coding: utf-8 -*-
"""一次性：为每个学院发现"通知公告"列表页 URL（WebPlus CMS 的 /<id>/list.htm）。

输出 data/colleges-notices.tsv：host  学院名  通知列表URL（# 开头=未发现）
"""
import asyncio
import re
import sys
from pathlib import Path

import httpx

KEYWORDS = ("通知", "公告", "新闻", "要闻", "动态")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def load_colleges() -> list[tuple[str, str]]:
    rows = []
    for line in Path("data/colleges.tsv").read_text(encoding="utf-8").splitlines():
        if line.startswith("COLLEGE_TOTAL"):
            continue
        host, name = line.split("\t", 1)
        rows.append((host.strip(), name.strip()))
    return rows


def pick_notice_urls(html_text: str, base_host: str) -> list[str]:
    """从首页 HTML 里找通知类列表页候选，按相关度排序。"""
    cands: list[tuple[int, str]] = []
    for m in re.finditer(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
                         html_text, re.S | re.I):
        href, text = m.group(1), re.sub(r"<[^>]+>|\s+", "", m.group(2))
        if "list.htm" not in href:
            continue
        score = sum(2 if k in text else 0 for k in ("通知", "公告"))
        score += sum(1 if k in text else 0 for k in ("新闻", "要闻", "动态"))
        if "通知" in text and "公告" in text:
            score += 3
        if score <= 0:
            continue
        if href.startswith("http"):
            url = href
        else:
            url = f"https://{base_host}/{href.lstrip('/')}"
        cands.append((score, url))
    cands.sort(key=lambda x: -x[0])
    seen, out = set(), []
    for _, u in cands:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def probe(client: httpx.AsyncClient, host: str, name: str):
    for scheme in ("https://",):
        try:
            r = await client.get(f"{scheme}{host}.seu.edu.cn/",
                                 headers=UA, follow_redirects=True, timeout=15)
            if r.status_code != 200:
                return host, name, f"#HTTP{r.status_code}"
            urls = pick_notice_urls(r.text, host)
            return host, name, (urls[0] if urls else "#未发现")
        except Exception as e:
            return host, name, f"#错误:{type(e).__name__}"
    return host, name, "#不可达"


async def main():
    colleges = load_colleges()
    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(
            *(probe(client, h, n) for h, n in colleges))
    out = Path("data/colleges-notices.tsv")
    lines = []
    for host, name, url in sorted(results, key=lambda x: x[1]):
        lines.append(f"{host}\t{name}\t{url}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    found = sum(1 for _, _, u in results if not u.startswith("#"))
    print(f"完成：{found}/{len(results)} 个学院发现通知列表页 → {out}")


if __name__ == "__main__":
    asyncio.run(main())
