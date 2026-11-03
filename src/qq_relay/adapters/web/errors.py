"""采集异常 → 自然语言映射（后台监控源表格展示用）。

原则：**UI 只说人话，原始堆栈留在控制台日志**。
- base.py 的 poller 用 friendly_error(e) 写 stats["last_error"]；
- admin.py 的手动扫描接口同样走 friendly_error，避免抛原始 traceback。

覆盖：DNS/连接/超时/TLS/HTTP 状态码/登录页 HTML/JSON 解析/本地文件缺失/
账号未配置/CAS 验证码，以及项目自定义错误（LectureError/LaborError…）。
"""

from __future__ import annotations

import re

_HTML_HINT = ("<!doctype", "<html", "<head", "x-ua-compatible")


def _chain(exc: BaseException) -> list[BaseException]:
    """展开 __cause__ / __context__ 链（去重、限深防环）。"""
    out: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen and len(out) < 6:
        seen.add(id(cur))
        out.append(cur)
        cur = cur.__cause__ or cur.__context__
    return out


def _texts(exc: BaseException) -> tuple[list[str], list[str]]:
    """返回（类名列表, 消息列表）。"""
    names, msgs = [], []
    for e in _chain(exc):
        names.append(type(e).__name__)
        try:
            msgs.append(str(e))
        except Exception:
            msgs.append("")
    return names, msgs


def friendly_error(exc: BaseException) -> str:
    """把采集/运行期异常翻译成一句可读的中文说明。"""
    names, msgs = _texts(exc)
    text = " | ".join(m for m in msgs if m)
    low = text.lower()
    joined_names = " ".join(names).lower()

    # ── 1. DNS / 网络不可达（如不在校园网） ────────────────────────────
    if ("getaddrinfo" in low or "name or service not known" in low
            or "nodename nor servname" in low or "11001" in low
            or "gaierror" in joined_names):
        return ("无法解析域名（DNS 失败）：当前网络可能不在校园网/VPN 内，"
                "或网络已断开。请连上校园网后重试。")
    if "connection refused" in low or "10061" in low:
        return "连接被拒绝：目标服务未开放或需要校内网络（VPN/校园网）。"
    if "connection reset" in low or "connection aborted" in low:
        return "连接被站点重置：可能被反爬拦截或网络不稳定，稍后重试。"

    # ── 2. 超时 ────────────────────────────────────────────────────────
    if "timeout" in joined_names or "timed out" in low or "超时" in text:
        return "请求超时：站点响应过慢或网络不稳定，请稍后重试（或调大扫描间隔）。"

    # ── 3. TLS / 证书 ──────────────────────────────────────────────────
    if "ssl" in joined_names or "certificate" in low or "证书" in text:
        return "HTTPS 证书校验失败：网络可能被代理劫持，或系统根证书异常。"

    # ── 4. HTTP 状态码 ────────────────────────────────────────────────
    m = re.search(r"\bHTTP\s*(\d{3})\b", text)
    if not m and "http" in low:          # 仅在 HTTP 语境下兜底匹配裸状态码
        m = re.search(r"\b(4\d\d|5\d\d)\b", text)
    if m:
        code = int(m.group(1))
        if code == 401:
            return "访问被拒绝（HTTP 401）：登录会话已失效，请重新登录后重试。"
        if code == 403:
            return "访问被拒绝（HTTP 403）：无权限或触发反爬，可能需要校园网/重新登录。"
        if code == 404:
            return "接口不存在（HTTP 404）：站点地址可能已变更。"
        if code == 429:
            return "请求过于频繁（HTTP 429）：已被站点限流，请调大扫描间隔。"
        if 500 <= code <= 599:
            return f"站点服务器错误（HTTP {code}）：对方服务暂时不可用，请稍后重试。"

    # ── 5. 返回网页而非 JSON / 登录页 / 反爬 ───────────────────────────
    if ("非 json" in low or "not json" in low
            or any(h in low for h in _HTML_HINT)):
        return ("站点返回的是网页而不是数据接口：通常是登录会话失效（被跳到登录页）、"
                "站点要求校园网访问，或接口改版/触发反爬验证。"
                "请重新登录并确认在校园网内后重试。")

    # ── 6. 项目自定义错误（保留原本就友好的中文，补齐上下文） ─────────
    if "labor_username" in low or "未配置 labor" in low:
        return "未配置劳动教育平台账号：请在 .env 填 LABOR_USERNAME / LABOR_PASSWORD。"
    if "cas 登录失败" in low or "cas登录失败" in low:
        return ("统一身份认证（CAS）登录失败：账号或密码错误，"
                "或需要验证码/短信二次验证。")
    if "验证码" in text or "need_manual" in low:
        return "登录需要人工验证（验证码/短信）：请先在浏览器完成登录并更新 cookie。"
    if "获取 cas 公钥失败" in low:
        return "CAS 服务不可用：可能不在校园网，或统一认证服务临时维护。"
    if "会话无效" in text or "会话过期" in text:
        return "登录会话已失效：请重新登录并更新 cookie 后重试。"

    # ── 7. JSON 解析 / 本地文件 / 配置 ────────────────────────────────
    if "jsondecodeerror" in joined_names or "expecting value" in low:
        return "返回数据格式异常：接口内容不是合法 JSON（可能被登录页/反爬页面替换）。"
    if "filenotfound" in joined_names or "no such file" in low:
        name = getattr(exc, "filename", "") or ""
        return f"本地文件不存在：{name or '配置或数据目录'}。请检查路径配置。"
    if "yaml" in joined_names or "yaml" in low:
        return "配置文件格式错误：请检查对应 .yml 的缩进与字段。"

    # ── 8. 兜底：去掉 HTML 噪音后截断 ─────────────────────────────────
    clean = re.sub(r"<[^>]{0,200}>", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return f"{type(exc).__name__}：采集失败（无错误详情，详见控制台日志）。"
    return clean[:160] + ("…" if len(clean) > 160 else "")
