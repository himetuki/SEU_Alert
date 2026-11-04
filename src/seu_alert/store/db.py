"""SQLite 存取：WAL 单文件。

用法：
    python -m seu_alert.store.db        # 初始化 / 校验 schema
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from ..config import Settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DB_NAME = "seu_alert.db"


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
    await _migrate(conn)


# 幂等列迁移：CREATE TABLE IF NOT EXISTS 不会给老表加列，这里补（ADR-023 起）
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    # 表名: [(列名, 列定义), ...]
    "users": [("pushplus_token", "TEXT")],
    "items": [("verified", "INTEGER NOT NULL DEFAULT 0"),
              ("reminded_json", "TEXT NOT NULL DEFAULT '[]'")],
}


async def _migrate(conn: aiosqlite.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        cols = await (await conn.execute(f"PRAGMA table_info({table})")).fetchall()
        existing = {c["name"] for c in cols}
        for column, decl in columns:
            if column not in existing:
                await conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                await conn.commit()
                print(f"[db] 迁移: {table}.{column} 已补齐")


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
