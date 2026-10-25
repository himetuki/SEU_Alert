"""测试期文件分发：data/outbox/<用户QQ>/ 一个文件夹代表一个用户（ADR-021）。

- 即时分发：<时间戳>_<cat>_<事件短id>.txt
- Digest：   digest-<YYYYMMDD>.txt（追加）
- 真实 QQ 推送（deliver/qq.py）后置，复用同一 render_push 模板。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .base import Deliverer, render_push
from ..contracts import ClassifiedEvent

_USER_NOTE = "_说明.txt"


class FileDeliverer:
    def __init__(self, outbox_dir: Path) -> None:
        self.outbox_dir = Path(outbox_dir)

    def _ensure_user_dir(self, user_dir: Path) -> None:
        user_dir.mkdir(parents=True, exist_ok=True)
        note = user_dir / _USER_NOTE
        if not note.exists():
            note.write_text(
                "此文件夹对应一位用户的推送收件箱（测试期文件分发，非真实 QQ 推送）。\n"
                "每条推送一个 txt；digest-<日期>.txt 为当日汇总。\n",
                encoding="utf-8",
            )

    async def deliver(self, user_qq: str, item: ClassifiedEvent, kind: str) -> str:
        user_dir = self.outbox_dir / str(user_qq)
        self._ensure_user_dir(user_dir)
        text = render_push(item)
        if kind == "digest":
            path = user_dir / f"digest-{datetime.now():%Y%m%d}.txt"
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 46}\n{text}\n")
        else:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            base = f"{ts}_{item.cat}_{item.event_id[:8]}"
            path = user_dir / f"{base}.txt"
            n = 2                      # 同一秒内多条 → 追加序号，绝不互相覆盖
            while path.exists():
                path = user_dir / f"{base}-{n}.txt"
                n += 1
            path.write_text(text + "\n", encoding="utf-8")
        return str(path)


__all__ = ["FileDeliverer", "Deliverer"]
