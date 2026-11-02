"""SEU-Monitor（Go）归档库扫描。

目录约定（README）：
    <root>/web/教务处/<栏目中文名>/<通知标题--稳定ID>/
        ├── text.md      # 正文、来源链接、发布时间
        └── meta.json    # Notice(site/column/id/title/url/date) + 哈希 + 附件

root 默认 `~/.local/share/seu-monitor`；Windows 开发期在 WSL 里跑监控，
root 用 `--data-dir` 指到项目内目录（或配置里写 \\wsl.localhost\\... 路径）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .base import WebNotice, _truncate

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                 "%Y/%m/%d %H:%M:%S", "%Y/%m/%d")


def _parse_ts(value: str, fallback: float) -> int:
    for fmt in _DATE_FORMATS:
        try:
            return int(datetime.strptime(value.strip(), fmt).timestamp())
        except (ValueError, AttributeError):
            continue
    return int(fallback)


def scan(root: Path) -> list[WebNotice]:
    web_dir = Path(root) / "web" / "教务处"
    if not web_dir.is_dir():
        return []
    out: list[WebNotice] = []
    for meta_path in sorted(web_dir.glob("*/*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        notice_dir = meta_path.parent
        column = notice_dir.parent.name               # 栏目中文名
        title = str(meta.get("title") or notice_dir.name)
        body = ""
        text_md = notice_dir / "text.md"
        if text_md.is_file():
            try:
                body = text_md.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                body = ""
        text = _truncate(f"【{column}】{title}\n{body}")
        ts = _parse_ts(str(meta.get("date") or ""), meta_path.stat().st_mtime)
        out.append(WebNotice(
            key=f"monitor:{meta.get('notice_id') or notice_dir.name}",
            group_id="web-jwc",
            group_name="教务处（jwc.seu.edu.cn）",
            title=title,
            text=text,
            url=str(meta.get("url") or ""),
            ts=ts,
            sender="东南大学教务处",
        ))
    return out
