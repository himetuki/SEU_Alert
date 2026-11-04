"""装配 + 启动（ADR-023 版）：多出口分发 + 投稿提取栈 + 临期提醒调度。

    .venv\\Scripts\\python -m seu_alert.main [--seconds N] [--forever]
    .venv\\Scripts\\python -m seu_alert.submit --text/--image/--course ...   # 本地投稿

DELIVER_MODE 逗号组合：file（测试期留档）| pushplus（微信强推送）| qq（内部测试）。
QQ 私聊为内部测试通道，不专门维护适配（ADR-023）。
"""

from __future__ import annotations

import argparse
import asyncio
import signal
from dataclasses import dataclass, field
from typing import Optional

from .adapters.onebot import OneBotServer
from .adapters.user_report import SubmissionIntake
from .adapters.web import SCANNERS, WebPoller, WebSource
from .botcmd import handle_private
from .config import (
    ConfigError,
    Settings,
    load_groups,
    load_subscriptions,
    load_web_sources,
)
from .deliver.file import FileDeliverer
from .deliver.multi import MultiDeliverer
from .deliver.pushplus import PushPlusDeliverer
from .deliver.qq import QqDeliverer
from .pipeline.extract_stack import SubmissionExtractor
from .pipeline.llm import ChatClient
from .pipeline.ocr import build_ocr_provider
from .pipeline.reminder import ReminderScheduler
from .pipeline.runner import Runner
from .store import db as store_db
from .store import queries


def build_extractor(s: Settings) -> SubmissionExtractor:
    """投稿提取栈：OCR/视觉（图→文）→ 大模型（可选）→ 小模型（备用）。"""
    vision = (ChatClient(s.vision_base_url, s.vision_api_key, s.vision_model)
              if s.vision_model else None)
    big = (ChatClient(s.big_base_url, s.big_api_key, s.big_model)
           if s.big_model else None)
    small = (ChatClient(s.small_base_url, s.small_api_key, s.small_model,
                        suppress_reasoning=True)
             if s.small_model else None)
    ocr = None
    if s.ocr_provider != "none":
        try:
            ocr = build_ocr_provider(s.ocr_provider, s.ocr_base_url,
                                     s.ocr_api_key, s.ocr_api_secret,
                                     s.ocr_engine_id)
        except Exception as e:
            print(f"[main] OCR provider 初始化失败（按未配置处理）: {e!r}")
    return SubmissionExtractor(vision=vision, big=big, small=small, ocr=ocr,
                               chain=s.submit_extract_chain)


@dataclass
class Runtime:
    settings: Settings
    groups: object
    subs: object
    conn: object
    runner: Runner
    intake: SubmissionIntake
    scheduler: ReminderScheduler
    server: Optional[OneBotServer]
    pollers: dict = field(default_factory=dict)      # source_id → WebPoller（ADR-026 后台用）


async def build_runtime(s: Settings, with_server: bool = True) -> Runtime:
    s.ensure_dirs()
    if s.classifier != "stub":
        raise ConfigError("当前仅支持 CLASSIFIER=stub（JEV 分类树 P2 接入）")

    groups = load_groups(s.config_dir / "groups.yml")
    subs = load_subscriptions(s.config_dir / "subscriptions.yml")
    conn = await store_db.connect(s)
    await store_db.init_schema(conn)
    group_names = {gid: g.name for gid, g in groups.groups.items()}

    server = OneBotServer(s.onebot_host, s.onebot_port, s.onebot_token) if with_server else None

    # ---- 分发出口（可组合）----
    deliverers = {}
    for mode in Settings.parse_deliver_modes(s.deliver_mode):
        if mode == "file":
            deliverers["file"] = FileDeliverer(s.outbox_dir, group_names=group_names)
        elif mode == "pushplus":
            deliverers["pushplus"] = PushPlusDeliverer(
                default_token=s.pushplus_token, topic=s.pushplus_topic,
                token_of=lambda qq: queries.user_pushplus_token(conn, qq),
                group_names=group_names)
        elif mode == "qq":
            deliverers["qq"] = QqDeliverer(server, group_names=group_names)
    deliverer = deliverers[next(iter(deliverers))] if len(deliverers) == 1 \
        else MultiDeliverer(deliverers)

    # ---- 提醒调度 +  runner ----
    scheduler = ReminderScheduler(conn, deliverer, offsets=s.reminder_offsets,
                                  interval=s.reminder_interval)
    runner = Runner(s, groups, subs, deliverer, conn,
                    reminder_hook=scheduler.schedule_for)
    await runner.restore_dedup()

    intake = SubmissionIntake(extractor=build_extractor(s),
                              on_notice=lambda ev: runner.handle_event(ev),
                              db=conn)
    return Runtime(settings=s, groups=groups, subs=subs, conn=conn,
                   runner=runner, intake=intake, scheduler=scheduler,
                   server=server, pollers={})


async def spawn_web_pollers(runtime: Runtime) -> dict:
    """为所有 web 源创建轮询器并常驻运行；返回 {source_id: WebPoller}。"""
    pollers: dict = {}
    for src in load_web_sources(runtime.settings.config_dir / "web-sources.yml").sources:
        if not src.enabled:
            print(f"[web:{src.id}] 已停用（web-sources.yml enabled: false），跳过")
            continue
        seen = await queries.load_web_seen(runtime.conn, src.id)
        poller = WebPoller(
            source=WebSource(id=src.id, kind=src.kind, name=src.name,
                             root=src.root, interval=src.interval),
            scanner=SCANNERS[src.kind],
            seen=seen,
            on_notice=lambda ev: runtime.runner.handle_event(ev),
            mark_seen=lambda key, sid=src.id: queries.mark_web_seen(
                runtime.conn, sid, key),
        )
        pollers[src.id] = poller
        asyncio.create_task(poller.run_forever())
    runtime.pollers = pollers
    return pollers


async def amain(seconds: int | None) -> int:
    s = Settings.from_env()
    rt = await build_runtime(s, with_server=True)
    runner, server = rt.runner, rt.server

    await spawn_web_pollers(rt)
    web_cfg = load_web_sources(s.config_dir / "web-sources.yml")

    await server.start()
    modes = " + ".join(Settings.parse_deliver_modes(s.deliver_mode))
    print(f"[main] 反向 WS 监听 ws://{s.onebot_host}:{s.onebot_port}，等 NapCat 连入")
    print(f"[main] 分发出口=[{modes}]；分类器=stub；提醒档位={s.reminder_offsets}h")
    print(f"[main] 画像群 {len(rt.groups.groups)} 个 · 订阅用户 {len(rt.subs.subs)} 个 · "
          f"web 源 {len(web_cfg.sources)} 个 · 提取链={s.submit_extract_chain}")

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
            except Exception as e:
                print(f"[main] 事件处理失败: {e!r}")

    async def consume_private() -> None:
        async for pm in server.private_messages():
            try:
                reply = await handle_private(pm.user_id, pm.text, rt.groups,
                                             rt.subs,
                                             s.config_dir / "subscriptions.yml",
                                             rt.conn)
                if reply:
                    await server.call_action(
                        "send_private_msg",
                        {"user_id": int(pm.user_id), "message": reply})
            except Exception as e:
                print(f"[main] 私聊处理失败: {e!r}")

    async def watchdog() -> None:
        warned = False
        while not stop.is_set():
            await asyncio.sleep(30)
            if server.stats["connected"] == 0 and not warned:
                print("[watchdog] NapCat 未连接——检查反向 WS 配置与登录态")
                warned = True
            elif server.stats["connected"] > 0 and warned:
                print("[watchdog] NapCat 已连入")
                warned = False

    tasks = [asyncio.create_task(c) for c in
             (consume_group(), consume_private(), watchdog(),
              rt.scheduler.run_forever())]
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
        await rt.conn.close()
        print(f"[main] 结束：{runner.stats}；连接统计 {server.stats}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="seu_alert 主管道（ADR-023）")
    ap.add_argument("--seconds", type=int, default=0, help="运行秒数，0=持续")
    ap.add_argument("--forever", action="store_true", help="持续运行（默认）")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(
        amain(None if (args.forever or not args.seconds) else args.seconds)))


if __name__ == "__main__":
    main()
