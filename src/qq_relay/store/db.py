"""SQLite 存取：WAL 单文件。

用法：
    python -m qq_relay.store.db        # 初始化 / 校验 schema
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from ..config import Settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DB_NAME = "qq-relay.db"


def db_path(settings: Settings) -> Path:
    return settings.data_dir / DB_NAME


async def connect(settings: Settings) -> aiosqlite.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(db_path(settings))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def init_schema(conn: aiosqlite.Connection) -> None:
    await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    await conn.commit()


async def main() -> int:
    s = Settings.from_env()
    s.ensure_dirs()
    conn = await connect(s)
    try:
        await init_schema(conn)
        rows = await (await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )).fetchall()
        print(f"[db] schema 就绪: {db_path(s)}")
        print(f"[db] 共 {len(rows)} 张表: {', '.join(r['name'] for r in rows)}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
