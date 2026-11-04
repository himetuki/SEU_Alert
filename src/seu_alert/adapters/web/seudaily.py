"""SEUdaily 网页库扫描。

目录约定：
    <root>/metadata/<sha256>.json     # {url,name,path,sha256,source{id,name},notice{id,title,url},sectionId}
    <root>/files/<host>/<section>/<notice_id>/<sha256>.md   # 正文（# 标题 / 来源：url / 正文 / ## 附件）

注意：metadata 没有发布日期字段，ts 用 metadata 文件 mtime（抓取时间）。
站点 id 取 host 首段（cse.seu.edu.cn → web-cse），与 SEU-Monitor 的 web-jwc 同一套命名。
"""

from __future__ import annotations

import json
from pathlib import Path

from .base import WebNotice, _truncate


def _site_group_id(source: dict) -> str:
    host = str((source or {}).get("id") or "unknown")
    short = host.split(".")[0] if host else "unknown"
    return f"web-{short}"


def _md_path(root: Path, meta: dict) -> Path | None:
    sha = str(meta.get("sha256") or "")
    source = meta.get("source") or {}
    section = str(meta.get("sectionId") or "")
    notice = meta.get("notice") or {}
    notice_id = str(notice.get("id") or "")
    if sha and section and notice_id:
        candidate = (root / "files" / str(source.get("id") or "")
                     / section / notice_id / f"{sha}.md")
        if candidate.is_file():
            return candidate
    raw = meta.get("path")                      # 兼容绝对路径（本机 SEUdaily 直接产出）
    if raw:
        p = Path(raw)
        if p.is_file():
            return p
    return None


def scan(root: Path) -> list[WebNotice]:
    root = Path(root)
    meta_dir = root / "metadata"
    if not meta_dir.is_dir():
        return []
    out: list[WebNotice] = []
    for meta_path in sorted(meta_dir.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            continue
        notice = meta.get("notice") or {}
        source = meta.get("source") or {}
        section = str(meta.get("sectionId") or "")
        title = str(notice.get("title") or meta.get("name") or meta_path.stem)
        body = ""
        md = _md_path(root, meta)
        if md is not None:
            try:
                body = md.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                body = ""
        text = _truncate(f"【{section}】{title}\n{body}")
        out.append(WebNotice(
            key=f"seudaily:{meta.get('sha256') or meta_path.stem}",
            group_id=_site_group_id(source),
            group_name=str(source.get("name") or _site_group_id(source)),
            title=title,
            text=text,
            url=str(notice.get("url") or meta.get("sourceUrl") or ""),
            ts=int(meta_path.stat().st_mtime),
            sender=str(source.get("name") or ""),
        ))
    return out
