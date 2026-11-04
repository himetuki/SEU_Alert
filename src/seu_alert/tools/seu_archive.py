"""Windows 原生 SEU-Monitor 归档生成器（无需 Go / WSL）。

背景：SEU-Monitor 是 Linux/Go 程序；本机是 Windows 时无法直接运行。
本工具用项目自带的教务处直采（jwc.py，ADR-029）抓取六个栏目，写出
**SEU-Monitor 兼容的归档目录**，供 `seu_monitor` 适配器消费：

    <root>/web/教务处/<栏目中文名>/<标题--通知ID>/
        ├── meta.json    # site_id/column/notice_id/title/url/date/attachments
        └── text.md      # "# 标题 / 来源 / 正文"

用法（Windows 直接跑）：

    .venv\\Scripts\\python -m seu_alert.tools.seu_archive --once
    # 默认 root=seu-projects-test/SEU-Monitor/store，config=config/jwc.yml

之后后台的 seu-monitor 源（enabled: true）会在下一轮扫描（或点「立即扫描」）
把归档读入管线。只抓公开页面，不复制 SEU-Monitor 源码（ADR-029 许可边界）。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from ..adapters.web.base import WebNotice
from ..adapters.web.jwc import scan

_WIN_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')


def _safe(name: str, limit: int = 80) -> str:
    """目录名净化：去掉 Windows 非法字符，保留中文。"""
    name = _WIN_BAD.sub("_", str(name or "")).strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    return (name[:limit] or "notice")


def _id_part(nid: str) -> str:
    """通知 ID 可能是站外 URL（部分栏目转载公众号文章）→ 用短哈希做目录名。"""
    nid = str(nid or "").strip()
    if nid.startswith(("http://", "https://")):
        return "u" + hashlib.sha256(nid.encode("utf-8")).hexdigest()[:10]
    return _safe(nid, 48)


def write_archive(root: Path, notices: list[WebNotice]) -> int:
    """把 WebNotice 列表写成 SEU-Monitor 兼容归档；返回写入条数。"""
    root = Path(root)
    written = 0
    for n in notices:
        column = n.column or "最新动态"
        nid = n.notice_id or (n.key.split(":")[-1] if n.key else "") or _safe(n.title)[:16]
        nid = _id_part(nid)
        folder = root / "web" / "教务处" / _safe(column) / f"{_safe(n.title)}--{nid}"
        folder.mkdir(parents=True, exist_ok=True)

        ts = n.ts or int(datetime.now().timestamp())
        meta = {
            "site_id": "jwc",
            "column": column,
            "notice_id": nid,
            "title": n.title,
            "url": n.url,
            "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "source": "seu_alert.tools.seu_archive (Windows native)",
            "attachments": [],
        }
        (folder / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # 只写正文（去掉「【栏目】标题」头）：适配器回读时会再拼一次，
        # 这样生成的 text 与 jwc 直采完全一致，内容哈希相同 → 多源自动去重合并。
        head = f"【{column}】{n.title}\n"
        body = n.text[len(head):] if n.text.startswith(head) else n.text
        (folder / "text.md").write_text(body + "\n", encoding="utf-8")
        written += 1
    return written


async def generate(root: Path, config: Path, max_articles: int = 15) -> int:
    """抓取教务处栏目 → 写归档。"""
    notices = await scan(config, fetch_articles=True, max_articles=max_articles)
    return write_archive(root, notices)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m seu_alert.tools.seu_archive",
        description="Windows 原生生成 SEU-Monitor 兼容归档（无需 Go/WSL）")
    ap.add_argument("--once", action="store_true",
                    help="抓取一轮并写归档（默认行为）")
    ap.add_argument("--root", default="seu-projects-test/SEU-Monitor/store",
                    help="归档根目录（默认 %(default)s）")
    ap.add_argument("--config", default="config/jwc.yml",
                    help="栏目配置（默认 %(default)s）")
    ap.add_argument("--max-articles", type=int, default=15,
                    help="每栏目最多抓取文章数（默认 %(default)s）")
    args = ap.parse_args(argv)
    n = asyncio.run(generate(Path(args.root), Path(args.config), args.max_articles))
    print(f"[seu-archive] 写入 {n} 条 → {Path(args.root) / 'web' / '教务处'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
