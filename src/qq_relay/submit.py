"""本地投稿 CLI（ADR-023）：文字/图片 → 提取栈 → 分类管道 → 分发出口。

    .venv\\Scripts\\python -m qq_relay.submit --text "高等数学作业 11月15日截止"
    .venv\\Scripts\\python -m qq_relay.submit --image shots\\notice.png --course 高等数学
    .venv\\Scripts\\python -m qq_relay.submit --text "..." --user 100001 --group 123456789

供内部测试与后续公众号/前端回调复用（HTTP 入口接入时调用同一 intake）。
"""

from __future__ import annotations

import argparse
import asyncio

from .config import Settings
from .main import build_runtime


async def amain(args) -> int:
    s = Settings.from_env()
    rt = await build_runtime(s, with_server=False)
    try:
        sub = await rt.intake.submit(
            user=args.user, text=args.text, image_path=args.image,
            course=args.course, group_id=args.group)
        print(f"[submit] 投稿 {sub.submission_id}")
        print(f"[submit] 提取链: {sub.chain_used or '（无模型介入）'} "
              f"low_conf={sub.low_conf}")
        print(f"[submit] 提取文本: {sub.extracted_text[:300]}")
        print(f"[submit] Runner 统计: {rt.runner.stats}")
        print(f"[submit] 分发出口: {s.deliver_mode} → 见 outbox / PushPlus")
    finally:
        await rt.conn.close()
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="本地投稿（ADR-023）")
    ap.add_argument("--text", help="通知文字（与 --image 二选一）")
    ap.add_argument("--image", help="通知截图路径（png/jpg）")
    ap.add_argument("--course", help="课程名（决定合成群 course:<课程名>）")
    ap.add_argument("--group", help="直接指定 group_id（优先于 course）")
    ap.add_argument("--user", default="internal", help="投稿者标识")
    args = ap.parse_args()
    if not args.text and not args.image:
        ap.error("必须提供 --text 或 --image")
    raise SystemExit(asyncio.run(amain(args)))


if __name__ == "__main__":
    main()
