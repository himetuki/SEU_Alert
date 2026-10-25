"""P0 冒烟：起 OneBot 反向 WS 服务，打印群消息事件并落原始日志。

用法：
    python -m qq_relay.smoke                 # 默认 60 秒
    python -m qq_relay.smoke --seconds 300   # 自定义时长
    python -m qq_relay.smoke --forever       # 一直跑（Ctrl-C 退出）

出口判据（验收 A1）：能看到 NapCat 连入、群消息逐条到达、延迟可观测。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import time

from .adapters.onebot import OneBotServer
from .config import Settings


def _fmt(ev) -> str:
    lat = time.time() - ev.ts
    at = " [@全体]" if ev.at_all else ""
    text = ev.text if len(ev.text) <= 60 else ev.text[:57] + "..."
    return (
        f"[{time.strftime('%H:%M:%S')}] +{lat:5.1f}s "
        f"群={ev.group_name or ev.group_id}({ev.group_id}) "
        f"发送者={ev.sender_card or ev.sender_id}({ev.sender_id}){at}\n"
        f"    {text}"
    )


async def run(seconds: int | None) -> int:
    s = Settings.from_env()
    s.ensure_dirs()
    log_path = s.log_dir / f"smoke-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_file = log_path.open("a", encoding="utf-8")

    def on_event(payload: dict) -> None:
        log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        log_file.flush()

    srv = OneBotServer(s.onebot_host, s.onebot_port, s.onebot_token, on_event=on_event)
    await srv.start()
    print(f"[smoke] 反向 WS 监听 ws://{s.onebot_host}:{s.onebot_port}（token={'已设置' if s.onebot_token else '未设置'}）")
    print(f"[smoke] 等 NapCat 连入…… 原始日志: {log_path}")
    if seconds:
        print(f"[smoke] {seconds} 秒后自动退出")
    else:
        print("[smoke] 持续运行，Ctrl-C 退出")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, ValueError):
            pass  # Windows 上 SIGTERM 可能不可用

    async def consume() -> None:
        async for ev in srv.events():
            print(_fmt(ev), flush=True)

    consumer = asyncio.create_task(consume())
    try:
        if seconds:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        else:
            await stop.wait()
    except asyncio.TimeoutError:
        pass
    finally:
        consumer.cancel()
        await srv.stop()
        log_file.close()

    print(
        f"[smoke] 结束：连接 {srv.stats['connected']} 次，事件 {srv.stats['events']} 条，"
        f"群消息 {srv.stats['group_msgs']} 条 → {log_path}"
    )
    return 0 if srv.stats["group_msgs"] > 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="P0 OneBot 冒烟")
    ap.add_argument("--seconds", type=int, default=60, help="运行秒数，默认 60")
    ap.add_argument("--forever", action="store_true", help="忽略 --seconds，持续运行")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(None if args.forever else args.seconds)))


if __name__ == "__main__":
    main()
