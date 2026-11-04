"""按 config/classification.yml 重分类历史 items（逐条读原文，只改 cat/cat2）。

用法：
    python scripts/reclassify_items.py                    # 预览（默认 dry-run）
    python scripts/reclassify_items.py --apply            # 写回 SQLite
    python scripts/reclassify_items.py --show all         # 打印全部条目
    python scripts/reclassify_items.py --db data/seu_alert.db --config config/classification.yml

只修改 items.cat / items.cat2，不动 raw_text、订阅与分发记录。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from seu_alert.pipeline.classifier_stub import classify_text, load_rules  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按规则配置重分类历史信息流")
    ap.add_argument("--db", default=str(ROOT / "data" / "seu_alert.db"))
    ap.add_argument("--config", default=str(ROOT / "config" / "classification.yml"))
    ap.add_argument("--apply", action="store_true", help="写回数据库（默认只预览）")
    ap.add_argument("--show", default="changed",
                    choices=["changed", "all", "none"], help="打印哪些条目")
    ap.add_argument("--allow-body", action="store_true",
                    help="正文也参与匹配（默认只看标题；网页通知建议只看标题）")
    args = ap.parse_args(argv)

    rs = load_rules(args.config)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT event_id, cat, cat2, raw_text, groups_json, created_at "
        "FROM items ORDER BY created_at DESC").fetchall()

    old_counts: Counter[str] = Counter()
    new_counts: Counter[str] = Counter()
    changes: list[tuple[sqlite3.Row, str, str]] = []
    for r in rows:
        groups = json.loads(r["groups_json"] or "[]")
        gid = groups[0] if groups else ""
        source = "web_crawl" if gid.startswith("web-") else "qq_group"
        allowed = rs.group_cats.get(gid) or rs.source_cats.get(source)
        old = str(r["cat"] or "")
        new, _urg, _action, hits = classify_text(
            r["raw_text"] or "", rs, allow_body=args.allow_body,
            allowed=allowed)
        old_counts[old] += 1
        new_counts[new] += 1
        if new != old:
            changes.append((r, old, new))
            if args.apply:
                conn.execute("UPDATE items SET cat=?, cat2=? WHERE event_id=?",
                             (new, new, r["event_id"]))

    if args.apply:
        conn.commit()

    print(f"共 {len(rows)} 条 | 规则 {len(rs.rules)} 条 | "
          f"{'已写回' if args.apply else '预览（未写库）'} | 变更 {len(changes)} 条")
    print("\n旧分布:", dict(old_counts.most_common()))
    print("新分布:", dict(new_counts.most_common()))

    if args.show != "none":
        shown = rows if args.show == "all" else [c[0] for c in changes]
        old_map = {id(r): (old, new) for r, old, new in changes}
        print("\n条目（旧 → 新）：")
        for r in shown:
            old, new = old_map.get(id(r), (r["cat"], r["cat"]))
            mark = "  " if old == new else "* "
            title = (r["raw_text"] or "").splitlines()[0][:56]
            print(f"{mark}{old:>11} → {new:<11} | {r['event_id'][:8]} | {title}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())