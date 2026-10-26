"""CAS 无浏览器登录（auth.seu.edu.cn）——劳动教育与人文讲座监控共用。

流程移植自两个已验证项目（同一套 CAS）：
- SEU-Labor-Course-Pusher `login.rs`
- seu-lecture-cli `core/auth.py`

探测验证码 → 取 RSA 公钥加密密码 → casLogin → 票据兑换。
需要短信/验证码时返回 "need_manual:…"，由调用方决定跳过本轮并告警。
"""

from __future__ import annotations

import base64
from typing import Optional

import httpx

NEED_CAPTCHA = "https://auth.seu.edu.cn/auth/casback/needCaptcha"
CHIPER_KEY = "https://auth.seu.edu.cn/auth/casback/getChiperKey"
LOGIN_URL = "https://auth.seu.edu.cn/auth/casback/casLogin"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class CasError(Exception):
    pass


def rsa_encrypt_password(public_key_pem: str, password: str) -> str:
    """CAS 密码加密：RSA PKCS#1 v1.5 → base64。公钥为 PEM（可无头，自动补）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pem = public_key_pem.strip()
    if "BEGIN PUBLIC KEY" not in pem:
        pem = ("-----BEGIN PUBLIC KEY-----\n"
               + "\n".join(pem[i:i + 64] for i in range(0, len(pem), 64))
               + "\n-----END PUBLIC KEY-----")
    key = serialization.load_pem_public_key(pem.encode("utf-8"))
    if not hasattr(key, "encrypt"):
        raise CasError("CAS 公钥不是 RSA 公钥")
    ct = key.encrypt(password.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ct).decode("ascii")


async def cas_auto_login(client: httpx.AsyncClient, username: str,
                         password: str, service: str) -> str:
    """执行 CAS 登录并把 cookie 写进 client。返回 "" 成功；"need_manual:…" 需人工；
    失败抛 CasError。调用方需已设置 follow_redirects=True。"""
    if not (username and password):
        raise CasError("未配置账号密码，也未提供 cookie")
    # 0) 探测验证码 / 短信
    r = await client.get(NEED_CAPTCHA, headers={"User-Agent": UA})
    cap = r.json() if r.status_code == 200 else {}
    if cap.get("needStage2Validation"):
        return "need_manual:服务端要求短信二次验证"
    info = str(cap.get("info") or "")
    if not cap.get("success") or ("验证码" in info and "不需要" not in info):
        return f"need_manual:登录需要验证码（{info}）"
    # 1) RSA 公钥 → 加密密码
    r = await client.post(CHIPER_KEY, json={}, headers={"User-Agent": UA})
    key = r.json() if r.status_code == 200 else {}
    pem = str(key.get("publicKey") or "")
    if not key.get("success") or not pem:
        raise CasError("获取 CAS 公钥失败")
    enc = rsa_encrypt_password(pem, password)
    # 2) 提交登录
    r = await client.post(LOGIN_URL, json={
        "service": service, "username": username, "password": enc,
        "captcha": "", "rememberMe": False, "loginType": "account",
        "wxBinded": False, "mobilePhoneNum": "",
        "fingerPrint": "stable_qq_relay",
    }, headers={"User-Agent": UA})
    data = r.json() if r.status_code == 200 else {}
    if not data.get("success"):
        raise CasError(f"CAS 登录失败: {str(data)[:200]}")
    # 3) 票据兑换（重定向链由 follow_redirects 自动完成）
    ticket = (data.get("data") or {}).get("ticket") \
        or (data.get("data") or {}).get("st") or ""
    if ticket:
        await client.get(f"{service}?ticket={ticket}",
                         headers={"User-Agent": UA}, follow_redirects=True)
    return ""


def apply_cookies(client: httpx.AsyncClient, cookies: dict) -> None:
    for k, v in (cookies or {}).items():
        client.cookies.set(k, v)


def parse_cookie_env(raw: str) -> dict[str, str]:
    """LABOR_COOKIES / SEU_LECTURE_COOKIES 解析：JSON dict / JSON list / "k=v; k=v"。"""
    import json

    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            return {str(c["name"]): str(c["value"]) for c in data}
    except (ValueError, KeyError, TypeError):
        pass
    out = {}
    for part in raw.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out
