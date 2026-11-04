"""结构化配置读写（后台「配置」页）。

设计目标：**行级编辑**，尽量保留原文件注释与排版；写入走 tmp + rename 原子替换。
覆盖：
- `.env`：KEY=VALUE 行替换/追加（保留行尾注释）
- `web-sources.yml`：按源 id 更新 `enabled` / `interval`（保留注释）
- `wechat-mp.yml` / `seu-lectures.yml`：顶层标量键替换/追加
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_ENV_LINE = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<sp>\s*)="
    r"(?P<value>[^#\r\n]*?)(?P<tail>\s*#.*)?$")
_QUOTES = ("'", '"')


def _atomic_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_env(path: Path) -> dict[str, str]:
    """读 .env（不导出到进程环境）。忽略注释与空行，去引号。"""
    p = Path(path)
    out: dict[str, str] = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        key, value = s.split("=", 1)
        key = key.strip()
        value = re.sub(r"\s+#.*$", "", value).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in _QUOTES:
            value = value[1:-1]
        out[key] = value
    return out


def update_env(path: Path, updates: dict[str, str]) -> None:
    """按行更新 .env；保留注释、顺序与行尾注释，缺失键追加到末尾。"""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and m.group("key") in updates:
            key = m.group("key")
            seen.add(key)
            indent = m.group("indent")
            tail = m.group("tail") or ""
            out.append(f"{indent}{key}={updates[key]}{('  ' + tail.strip()) if tail else ''}")
        else:
            out.append(line)
    missing = [k for k in updates if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.append("# ---- 后台配置页更新 ----")
        out.extend(f"{k}={updates[k]}" for k in missing)
    _atomic_text(p, "\n".join(out).rstrip("\n") + "\n")


def read_yaml(path: Path) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def update_simple_yaml(path: Path, updates: dict[str, object]) -> None:
    """更新顶层标量键（如 extract_layer / interval / keyword），保留其余行。"""
    p = Path(path)
    lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*:"
                     r"(?P<value>[^#]*?)(?P<tail>\s*#.*)?$", line)
        if m and m.group("key") in updates:
            key = m.group("key")
            seen.add(key)
            tail = m.group("tail") or ""
            out.append(f"{m.group('indent')}{key}: {_yaml_scalar(updates[key])}"
                       f"{('  ' + tail.strip()) if tail else ''}")
        else:
            out.append(line)
    missing = [k for k in updates if k not in seen]
    if missing:
        out.extend(f"{k}: {_yaml_scalar(updates[k])}" for k in missing)
    _atomic_text(p, "\n".join(out).rstrip("\n") + "\n")


_WS_ID = re.compile(r"^(?P<indent>\s*)-\s+id:\s*(?P<id>[^\s#]+)")


def update_web_sources(path: Path, changes: dict[str, dict]) -> None:
    """按源 id 更新 enabled/interval；找不到字段时插入到 id 行下方。"""
    p = Path(path)
    if not p.is_file() or not changes:
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    blocks: list[tuple[int, str, str]] = []      # (start, indent, id)
    for i, line in enumerate(lines):
        m = _WS_ID.match(line)
        if m:
            blocks.append((i, m.group("indent"), m.group("id")))
    # 从后往前改，避免插入导致前面的索引失效
    for start, indent, sid in reversed(blocks):
        conf = changes.get(sid)
        if not conf:
            continue
        end = len(lines)
        for nxt, _, _ in blocks:
            if nxt > start:
                end = nxt
                break
        field_indent = indent + "  "
        for field in ("enabled", "interval"):
            if field not in conf:
                continue
            target = None
            for i in range(start + 1, end):
                if re.match(rf"^\s*{field}\s*:", lines[i]):
                    target = i
                    break
            if target is not None:
                tail = ""
                m = re.search(r"(\s*#.*)$", lines[target])
                if m:
                    tail = "  " + m.group(1).strip()
                lines[target] = f"{field_indent}{field}: {_yaml_scalar(conf[field])}{tail}"
            else:
                lines.insert(start + 1, f"{field_indent}{field}: {_yaml_scalar(conf[field])}")
                end += 1
    _atomic_text(p, "\n".join(lines).rstrip("\n") + "\n")


def _yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
