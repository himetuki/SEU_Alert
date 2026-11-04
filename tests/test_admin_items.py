"""后台信息流读取回归：aiosqlite 连接不能跨事件循环复用。

历史 bug：items() 缓存连接，第二次调用时连接绑定在已关闭的 loop 上，
线程异常 → join(15s) 超时 → 接口空返回、页面 15 秒才刷新一次。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from seu_alert.admin import AdminContext
from seu_alert.contracts import ClassifiedEvent
from seu_alert.store import db as store_db
from seu_alert.store import queries


def test_items_across_fresh_event_loops(tmp_path):
    settings = SimpleNamespace(data_dir=tmp_path)

    async def setup():
        conn = await store_db.connect(settings)
        await store_db.init_schema(conn)
        await queries.insert_item(conn, ClassifiedEvent(
            event_id="e1", groups=["g1"], cat="notice", cat2="notice",
            is_info=1.0, urg=2, action="know", has_ddl=False,
            raw_text="标题一行\n正文", created_at=1790000000))
        await conn.close()

    asyncio.run(setup())
    ctx = AdminContext(SimpleNamespace(settings=settings), {}, None)

    first = ctx.items()
    second = ctx.items()          # 第二次必须仍能读，且不等待 15s 超时
    assert len(first) == 1 and len(second) == 1
    assert first[0]["title"] == "标题一行"
    assert first[0]["groups"] == ["g1"]