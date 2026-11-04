# -*- coding: utf-8 -*-
"""金标准校准 harness（P2 测量仪器）。

    .venv\\Scripts\\python scripts\\run_goldset.py --file data/goldset.jsonl

对金标准集逐条跑「预筛 + 分类器」，产出 data/goldset-report.md：
留/不留准确率、9 类 P/R/F1、混淆矩阵、urg 偏差、deadline 一致率、
预筛漏检（该留的被挡在模型前）。P2 起分类器可切 `--classifier tree`。

金标准集怎么填见 data/goldset.README.md。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from seu_alert.config import CATS  # noqa: E402
from seu_alert.contracts import RawEvent  # noqa: E402
from seu_alert.pipeline.classifier_stub import classify_stub  # noqa: E402
from seu_alert.pipeline.prefilter import Deduper, Prefilter, Stage  # noqa: E402

DROP = "__DROP__"


@dataclass
class GoldRow:
    id: str
    text: str
    source: str
    cat: str
    cat2: str
    urg: int
    has_ddl: bool
    deadline: str | None


def load_goldset(path: Path) -> tuple[list[GoldRow], list[str]]:
    rows: list[GoldRow] = []
    errors: list[str] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError as e:
            errors.append(f"第 {i} 行 JSON 解析失败: {e}")
            continue
        for field in ("id", "text", "cat"):
            if not d.get(field):
                errors.append(f"第 {i} 行缺字段 {field}")
                break
        else:
            cat = str(d["cat"])
            if cat not in CATS:
                errors.append(f"第 {i} 行 cat 非法: {cat}（可选 {CATS}）")
                continue
            rows.append(GoldRow(
                id=str(d["id"]), text=str(d["text"]),
                source=str(d.get("source") or ""),
                cat=cat, cat2=str(d.get("cat2") or cat),
                urg=int(d.get("urg") or 0),
                has_ddl=bool(d.get("has_ddl")),
                deadline=(str(d["deadline"]) if d.get("deadline") else None),
            ))
    return rows, errors


def get_classifier(name: str):
    if name == "stub":
        return classify_stub
    if name == "tree":
        try:
            from seu_alert.pipeline.tree import TreeClassifier  # P2 落地后启用
        except ImportError as e:
            raise SystemExit(
                "tree 分类器尚未实现（P2）；现在请用 --classifier stub") from e
        return TreeClassifier()
    raise SystemExit(f"未知分类器: {name}")


def evaluate(rows: list[GoldRow], classifier, prefilter: Prefilter | None = None) -> dict:
    pf = prefilter or Prefilter()
    deduper = Deduper()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    classes = sorted({r.cat for r in rows})
    keep_tp = keep_fp = keep_fn = keep_tn = 0
    prefilter_miss: list[str] = []          # 该留被预筛挡
    prefilter_leak: list[str] = []          # 闲聊漏过预筛
    urg_exact = urg_within1 = urg_n = 0
    ddl_total = ddl_hit = 0
    ddl_miss: list[str] = []
    for r in rows:
        ev = RawEvent(source="goldset", group_id="gold", group_name="金标准",
                      sender_id="gold", sender_card="gold", msg_id=r.id,
                      text=r.text, ts=0)
        d = pf.process(ev, None, deduper)
        gold_keep = r.cat != "chat"
        if not d.passed:
            pred = DROP
            if gold_keep:
                keep_fn += 1
                prefilter_miss.append(f"{r.id}@{d.stage.value}")
            else:
                keep_tn += 1
            confusion[r.cat][pred] += 1
            continue
        deduper.register(d.content_hash, r.id)
        item = classifier(ev, f"gs-{r.id}", None)
        pred = item.cat
        pred_keep = pred != "chat"
        if gold_keep and pred_keep:
            keep_tp += 1
        elif (not gold_keep) and pred_keep:
            keep_fp += 1
            prefilter_leak.append(r.id)
        elif gold_keep and not pred_keep:
            keep_fn += 1
        else:
            keep_tn += 1
        confusion[r.cat][pred] += 1
        if gold_keep:
            urg_n += 1
            if item.urg == r.urg:
                urg_exact += 1
            if abs(item.urg - r.urg) <= 1:
                urg_within1 += 1
        if r.deadline:
            ddl_total += 1
            if (item.deadline or "") == r.deadline:
                ddl_hit += 1
            else:
                ddl_miss.append(f"{r.id}: 期望{r.deadline} 实得{item.deadline}")
    # per-class P/R/F1（预测为某类的才算，DROP 单列）
    metrics: dict[str, dict[str, float]] = {}
    for c in classes:
        tp = confusion[c].get(c, 0)
        support = sum(confusion[c].values())
        predicted = sum(confusion[g].get(c, 0) for g in classes)
        p = tp / predicted if predicted else 0.0
        rec = tp / support if support else 0.0
        f1 = 2 * p * rec / (p + rec) if (p + rec) else 0.0
        metrics[c] = {"precision": p, "recall": rec, "f1": f1, "support": support}
    keep_total = keep_tp + keep_fp + keep_fn + keep_tn
    return {
        "n": len(rows),
        "classes": classes,
        "confusion": {g: dict(v) for g, v in confusion.items()},
        "metrics": metrics,
        "keep": {"tp": keep_tp, "fp": keep_fp, "fn": keep_fn, "tn": keep_tn,
                 "accuracy": (keep_tp + keep_tn) / keep_total if keep_total else 0.0},
        "prefilter_miss": prefilter_miss,
        "prefilter_leak": prefilter_leak,
        "urg": {"n": urg_n, "exact": urg_exact, "within1": urg_within1},
        "deadline": {"total": ddl_total, "hit": ddl_hit, "miss": ddl_miss},
    }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def format_report(m: dict, classifier_name: str, src: str) -> str:
    L: list[str] = ["# 金标准校准报告", "",
                    f"- 样本：{m['n']} 条 · 分类器：`{classifier_name}` · 来源：`{src}`",
                    f"- 留/不留准确率：**{_pct(m['keep']['accuracy'])}**"
                    f"（该留且留对 {m['keep']['tp']}，该留被丢 {m['keep']['fn']}，"
                    f"该丢且丢对 {m['keep']['tn']}，闲聊漏过 {m['keep']['fp']}）", ""]
    if m["prefilter_miss"]:
        L += [f"**预筛漏检（该留的被挡在模型前，{len(m['prefilter_miss'])} 条）**："
              + "、".join(m["prefilter_miss"][:20]), ""]
    L += ["## 分类指标", "", "| 类别 | Precision | Recall | F1 | 支持数 |",
          "|---|---|---|---|---|"]
    for c in sorted(m["metrics"], key=lambda x: -m["metrics"][x]["support"]):
        v = m["metrics"][c]
        L.append(f"| {c} | {_pct(v['precision'])} | {_pct(v['recall'])} | "
                 f"{_pct(v['f1'])} | {int(v['support'])} |")
    L += ["", "## 混淆矩阵（行=金标准，列=预测）", "",
          "| gold\\pred | " + " | ".join(m["classes"] + [DROP]) + " |",
          "|" + "---|" * (len(m["classes"]) + 2)]
    for g in m["classes"]:
        row = [str(m["confusion"].get(g, {}).get(p, 0) or "")
               for p in m["classes"] + [DROP]]
        L.append(f"| **{g}** | " + " | ".join(row) + " |")
    u = m["urg"]
    L += ["", "## 紧急度 urg", "",
          f"- 完全一致 {_pct(u['exact'] / u['n'] if u['n'] else 0)}"
          f"（{u['exact']}/{u['n']}）· ±1 以内 {_pct(u['within1'] / u['n'] if u['n'] else 0)}", ""]
    d = m["deadline"]
    if d["total"]:
        L += ["## deadline 提取", "",
              f"- 与金标准一致 {_pct(d['hit'] / d['total'])}（{d['hit']}/{d['total']}）", ""]
        if d["miss"]:
            L += ["不一致明细："] + [f"- {x}" for x in d["miss"][:20]] + [""]
    L += ["## 通过线（acceptance.md）", "",
          "- B1 根调用 cat 准确率 ≥ 80%（按本表 F1 宏平均看）",
          "- 预筛漏检中 homework/exam/research 三类 = 0（宁漏勿误的底线）", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="金标准校准 harness")
    ap.add_argument("--file", default="data/goldset.jsonl")
    ap.add_argument("--classifier", default="stub", choices=["stub", "tree"])
    ap.add_argument("--out", default="data/goldset-report.md")
    args = ap.parse_args()
    path = Path(args.file)
    if not path.is_file():
        raise SystemExit(f"找不到金标准集: {path}（模板见 data/goldset.template.jsonl，"
                         "填法见 data/goldset.README.md）")
    rows, errors = load_goldset(path)
    if errors:
        print("[goldset] 格式错误：")
        for e in errors[:20]:
            print("  -", e)
        return 2
    if not rows:
        raise SystemExit("金标准集为空")
    classifier = get_classifier(args.classifier)
    m = evaluate(rows, classifier)
    report = format_report(m, args.classifier, str(path))
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"[goldset] {m['n']} 条 · 留/不留准确率 {_pct(m['keep']['accuracy'])} "
          f"· 预筛漏检 {len(m['prefilter_miss'])} 条 · "
          f"deadline 一致 {m['deadline']['hit']}/{m['deadline']['total']}")
    print(f"[goldset] 报告 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
