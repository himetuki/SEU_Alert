"""装配 + 启动（P1）：OneBot 反向 WS → Runner → 文件分发。

    .venv\\Scripts\\python -m qq_relay.main [--seconds N] [--forever]

测试期零真实推送（ADR-021）：DELIVER_MODE=file 时所有分发写
data/outbox/<用户QQ>/；qq 模式在 P5 之后启用。
"""

from __future__ import annotations

import argparse
import asyncio
import signal

from .adapters.onebot import OneBotServer
from .botcmd import handle_private
from .config import (
    ConfigError,
    Settings,
    load_groups,
    load_subscriptions,
)
from .deliver.file import FileDeliverer
from .pipeline.runner import Runner
from .store import db as store_db


async def amain(seconds: int | None) -> int:
    s = Settings.from_env()
    s.ensure_dirs()

    if s.deliver_mode != "file":
        raise ConfigError("P1 测试期仅支持 DELIVER_MODE=file（qq 分发后置，ADR-021）")
    if s.classifier != "stub":
        raise ConfigError("P1 仅支持 CLASSIFIER=stub（JEV 分类树 P2 接入）")

    groups = load_groups(s.config_dir / "groups.yml")
    subs = load_subscriptions(s.config_dir / "subscriptions.yml")
    subs_path = s.config_dir / "subscriptions.yml"

    conn = await store_db.connect(s)
    await store_db.init_schema(conn)

    runner = Runner(s, groups, subs, FileDeliverer(s.outbox_dir), conn)
    await runner.restore_dedup()

    server = OneBotServer(s.onebot_host, s.onebot_port, s.onebot_token)
    await server.start()
    print(f"[main] 反向 WS 监听 ws://{s.onebot_host}:{s.onebot_port}，等 NapCat 连入")
    print(f"[main] 分发模式=file → {s.outbox_dir}/<用户QQ>/；分类器=stub")
    print(f"[main] 已加载画像群 {len(groups.groups)} 个，订阅用户 {len(subs.subs)} 个")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            pass

    async def consume_group() -> None:
        async for ev in server.events():
            try:
                await runner.handle_event(ev)
            except Exception as e:                # 单条事件不许拖垮管道
                print(f"[main] 事件处理失败: {e!r}")

    async def consume_private() -> None:
        async for pm in server.private_messages():
            try:
                reply = await handle_private(pm.user_id, pm.text, groups, subs,
                                             subs_path, conn)
                if reply:
                    await server.call_action(
                        "send_private_msg",
                        {"user_id": int(pm.user_id), "message": reply})
            except Exception as e:
                print(f"[main] 私聊处理失败: {e!r}")

    async def watchdog() -> None:
        """看门狗 stub（P5 完善）：NapCat 未连接 / 掉线时告警。"""
        warned = False
        while not stop.is_set():
            await asyncio.sleep(30)
            if server.stats["connected"] == 0 and not warned:
                print("[watchdog] NapCat 未连接——检查反向 WS 配置与登录态")
                warned = True
            elif server.stats["connected"] > 0 and warned:
                print("[watchdog] NapCat 已连入")
                warned = False

    tasks = [asyncio.create_task(c) for c in (consume_group(), consume_private(), watchdog())]
    try:
        if seconds:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        else:
            await stop.wait()
    except asyncio.TimeoutError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await server.stop()
        await conn.close()
        print(f"[main] 结束：{runner.stats}；连接统计 {server.stats}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="qq-relay P1 主管道")
    ap.add_argument("--seconds", type=int, default=0, help="运行秒数，0=持续")
    ap.add_argument("--forever", action="store_true", help="持续运行（默认）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(amain(None if (args.forever or not args.seconds) else args.seconds)))


if __name__ == "__main__":
    main()
