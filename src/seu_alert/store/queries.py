"""SQLite 存取助手（P1）：事件 / item / 分发 / 过滤日志 / 去重映射恢复。

连接与 schema 初始化见 store/db.py；这里是管道用的读写函数。
"""

from __future__ import annotations

import json
import time
from typing import Optional

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
            verified, reminded_json, raw_text, model_calls_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (item.event_id, json.dumps(item.groups, ensure_ascii=False), item.cat,
         item.cat2, item.is_info, item.urg, item.action, int(item.has_ddl),
         item.course, item.scope, item.channel, item.stage, item.deadline,
         item.deadline_src, int(item.low_conf), int(item.verified),
         item.reminded_json, item.raw_text,
         json.dumps(item.model_calls, ensure_ascii=False),
         item.created_at or int(time.time())),
    )
    await conn.commit()


async def get_item(conn: aiosqlite.Connection, event_id: str) -> Optional[aiosqlite.Row]:
    return await (await conn.execute(
        "SELECT * FROM items WHERE event_id=?", (event_id,)
    )).fetchone()


async def row_to_item(row: aiosqlite.Row) -> ClassifiedEvent:
    keys = row.keys()
    return ClassifiedEvent(
        event_id=row["event_id"],
        groups=json.loads(row["groups_json"]),
        cat=row["cat"], cat2=row["cat2"], is_info=row["is_info"], urg=row["urg"],
        action=row["action"], has_ddl=bool(row["has_ddl"]), course=row["course"],
        scope=row["scope"], channel=row["channel"], stage=row["stage"],
        deadline=row["deadline"], deadline_src=row["deadline_src"],
        low_conf=bool(row["low_conf"]),
        verified=(row["verified"] if "verified" in keys else 0),
        reminded_json=(row["reminded_json"] if "reminded_json" in keys else "[]"),
        raw_text=row["raw_text"],
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


# ---------------- 投稿 / 提醒 / 核验（ADR-023）----------------


async def insert_submission(conn: aiosqlite.Connection, *, submission_id: str,
                            user: str, course: str | None, group_id: str,
                            raw_text: str, image_path: str | None,
                            extracted_text: str, chain_used: str,
                            low_conf: bool, raw_event_id: str) -> None:
    await conn.execute(
        """INSERT INTO submissions
           (submission_id, user, course, group_id, raw_text, image_path,
            extracted_text, chain_used, low_conf, raw_event_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (submission_id, user, course, group_id, raw_text, image_path,
         extracted_text, chain_used, int(low_conf), raw_event_id,
         int(time.time())),
    )
    await conn.commit()


async def insert_reminder(conn: aiosqlite.Connection, event_id: str,
                          user_qq: str, fire_at: int, kind: str) -> bool:
    """插入提醒行；已存在返回 False（去重）。"""
    cur = await conn.execute(
        "INSERT OR IGNORE INTO reminders (event_id, user_qq, fire_at, kind) VALUES (?,?,?,?)",
        (event_id, user_qq, fire_at, kind),
    )
    await conn.commit()
    return cur.rowcount > 0


async def due_reminders(conn: aiosqlite.Connection, now_ts: int,
                        limit: int = 100) -> list:
    return await (await conn.execute(
        """SELECT * FROM reminders
           WHERE sent_at IS NULL AND fire_at<=? ORDER BY fire_at LIMIT ?""",
        (now_ts, limit),
    )).fetchall()


async def mark_reminder_sent(conn: aiosqlite.Connection, reminder_id: int,
                             path: str) -> None:
    await conn.execute(
        "UPDATE reminders SET sent_at=?, path=? WHERE reminder_id=?",
        (int(time.time()), path, reminder_id),
    )
    await conn.commit()


async def add_vote(conn: aiosqlite.Connection, event_id: str, user_qq: str,
                   kind: str, note: str = "") -> bool:
    if kind not in ("confirm", "report"):
        raise ValueError(f"vote.kind 非法: {kind!r}")
    cur = await conn.execute(
        "INSERT OR IGNORE INTO votes (event_id, user_qq, kind, note, created_at) VALUES (?,?,?,?,?)",
        (event_id, user_qq, kind, note, int(time.time())),
    )
    await conn.commit()
    return cur.rowcount > 0


async def vote_counts(conn: aiosqlite.Connection, event_id: str) -> dict[str, int]:
    rows = await (await conn.execute(
        "SELECT kind, COUNT(*) AS n FROM votes WHERE event_id=? GROUP BY kind",
        (event_id,),
    )).fetchall()
    return {r["kind"]: r["n"] for r in rows}


async def upsert_user(conn: aiosqlite.Connection, user_qq: str,
                      pushplus_token: str | None = None) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO users (user_qq, joined_at) VALUES (?,?)",
        (user_qq, int(time.time())),
    )
    if pushplus_token is not None:
        await conn.execute(
            "UPDATE users SET pushplus_token=? WHERE user_qq=?",
            (pushplus_token, user_qq),
        )
    await conn.commit()


async def user_pushplus_token(conn: aiosqlite.Connection, user_qq: str) -> str:
    row = await (await conn.execute(
        "SELECT pushplus_token FROM users WHERE user_qq=?", (user_qq,)
    )).fetchone()
    return (row["pushplus_token"] or "") if row else ""


async def set_item_verified(conn: aiosqlite.Connection, event_id: str,
                            verified: int) -> None:
    await conn.execute("UPDATE items SET verified=? WHERE event_id=?",
                       (int(verified), event_id))
    await conn.commit()


async def latest_delivery_event(conn: aiosqlite.Connection,
                                user_qq: str) -> Optional[str]:
    """该用户最近一次分发对应的事件 id（/confirm 不带参数时用）。"""
    row = await (await conn.execute(
        "SELECT event_id FROM deliveries WHERE user_qq=? ORDER BY created_at DESC LIMIT 1",
        (user_qq,),
    )).fetchone()
    return row["event_id"] if row else None
