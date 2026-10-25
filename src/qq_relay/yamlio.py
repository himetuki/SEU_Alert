"""YAML 原子写：tmp + rename，杜绝写一半的文件被读到。

P1 由 botcmd 直接使用；P3 起全部收敛进单一配置管理器（ADR-018）。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def atomic_write_yaml(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    os.replace(tmp, path)               # 同分区原子替换
