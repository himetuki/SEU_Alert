"""SQLite 存取助手（P1）：事件 / item / 分发 / 过滤日志 / 去重映射恢复。

连接与 schema 初始化见 store/db.py；这里是管道用的读写函数。
"""

from __future__ import annotations

import json
import time
from typing import Optional, Sequence

import aiosqlite

from ..contracts import ClassifiedEvent, RawEvent


async def insert_event(conn: aiosqlite.Connection, ev: RawEvent,
                       event_id: str, content_hash: str) -> None:
    await conn.execute(
        """INSERT OR IGNORE INTO events
           (event_id, source, group_id, group_name, sender_id, sender_card,
            msg_id, text, ts, at_all, content_hash, received_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, ev.source, ev.group_id, ev.group_name, ev.sender_id,
         ev.sender_card, ev.msg_id, ev.text, ev.ts, int(ev.at_all),
         content_hash, int(time.time())),
    )
    await conn.commit()


async def load_dedup_pairs(conn: aiosqlite.Connection) -> list[tuple[str, str]]:
    """hash → event_id 全量映射（启动时恢复去重状态）。"""
    rows = await (await conn.execute(
        "SELECT content_hash, event_id FROM events"
    )).fetchall()
    return [(r["content_hash"], r["event_id"]) for r in rows]


async def insert_item(conn: aiosqlite.Connection, item: ClassifiedEvent) -> None:
    await conn.execute(
        """INSERT OR REPLACE INTO items
           (event_id, groups_json, cat, cat2, is_info, urg, action, has_ddl,
            course, scope, channel, stage, deadline, deadline_src, low_conf,
            raw_text, model_calls_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item.event_id, json.dumps(item.groups, ensure_ascii=False), item.cat,
         item.cat2, item.is_info, item.urg, item.action, int(item.has_ddl),
         item.course, item.scope, item.channel, item.stage, item.deadline,
         item.deadline_src, int(item.low_conf), item.raw_text,
         json.dumps(item.model_calls, ensure_ascii=False),
         item.created_at or int(time.time())),
    )
    await conn.commit()


async def get_item(conn: aiosqlite.Connection, event_id: str) -> Optional[aiosqlite.Row]:
    return await (await conn.execute(
        "SELECT * FROM items WHERE event_id=?", (event_id,)
    )).fetchone()


async def row_to_item(row: aiosqlite.Row) -> ClassifiedEvent:
    return ClassifiedEvent(
        event_id=row["event_id"],
        groups=json.loads(row["groups_json"]),
        cat=row["cat"], cat2=row["cat2"], is_info=row["is_info"], urg=row["urg"],
        action=row["action"], has_ddl=bool(row["has_ddl"]), course=row["course"],
        scope=row["scope"], channel=row["channel"], stage=row["stage"],
        deadline=row["deadline"], deadline_src=row["deadline_src"],
        low_conf=bool(row["low_conf"]), raw_text=row["raw_text"],
        model_calls=json.loads(row["model_calls_json"] or "[]"),
        created_at=row["created_at"],
    )


async def add_item_group(conn: aiosqlite.Connection, event_id: str,
                         group_id: str) -> list[str]:
    """fan-in：把新来源群追加进 item.groups，返回更新后的群列表。"""
    row = await get_item(conn, event_id)
    if row is None:
        return []
    groups: list[str] = json.loads(row["groups_json"])
    if group_id not in groups:
        groups.append(group_id)
        await conn.execute(
            "UPDATE items SET groups_json=? WHERE event_id=?",
            (json.dumps(groups, ensure_ascii=False), event_id),
        )
        await conn.commit()
    return groups


async def insert_delivery(conn: aiosqlite.Connection, user_qq: str,
                          event_id: str, mode: str, path: str, kind: str,
                          urg: int) -> None:
    await conn.execute(
        """INSERT INTO deliveries
           (delivery_id, user_qq, event_id, mode, path, kind, urg, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (f"{user_qq}:{event_id}:{kind}", user_qq, event_id, mode, path,
         kind, urg, int(time.time())),
    )
    await conn.commit()


async def delivered_event_users(conn: aiosqlite.Connection,
                                event_id: str) -> set[str]:
    """该事件已分发过的用户（fan-in 时分发只补新命中的用户）。"""
    rows = await (await conn.execute(
        "SELECT DISTINCT user_qq FROM deliveries WHERE event_id=?", (event_id,)
    )).fetchall()
    return {r["user_qq"] for r in rows}


async def log_filtered(conn: aiosqlite.Connection, event_id: str | None,
                       stage: str, reason: str, detail: str = "") -> None:
    await conn.execute(
        """INSERT INTO filtered_log (event_id, stage, reason, detail, created_at)
           VALUES (?,?,?,?,?)""",
        (event_id, stage, reason, detail, int(time.time())),
    )
    await conn.commit()


async def insert_label(conn: aiosqlite.Connection, event_id: str | None,
                       source: str, cat: str | None = None,
                       note: str = "") -> None:
    await conn.execute(
        """INSERT INTO labels (event_id, source, cat, note, created_at)
           VALUES (?,?,?,?,?)""",
        (event_id, source, cat, note, int(time.time())),
    )
    await conn.commit()


async def recent_filtered_counts(conn: aiosqlite.Connection,
                                 since_ts: int) -> dict[str, int]:
    rows = await (await conn.execute(
        "SELECT stage, COUNT(*) AS n FROM filtered_log WHERE created_at>=? GROUP BY stage",
        (since_ts,),
    )).fetchall()
    return {r["stage"]: r["n"] for r in rows}


async def load_web_seen(conn: aiosqlite.Connection, source_id: str) -> set[str]:
    rows = await (await conn.execute(
        "SELECT notice_key FROM web_seen WHERE source_id=?", (source_id,)
    )).fetchall()
    return {r["notice_key"] for r in rows}


async def mark_web_seen(conn: aiosqlite.Connection, source_id: str,
                        notice_key: str) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO web_seen (source_id, notice_key, first_seen) VALUES (?,?,?)",
        (source_id, notice_key, int(time.time())),
    )
    await conn.commit()
