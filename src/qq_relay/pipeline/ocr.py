"""专用 OCR 协议 provider（ADR-023）。

与 vision（Chat Completion 看图）并列的"图片 → 文本"层。用户决策：
OCR 用**自有协议接口**（部分 OCR 如讯飞星火也提供 Chat Completion 形态，
那种情况走 llm.ChatClient 即可，不需要本模块）。

- `http`：通用 HTTP OCR——POST endpoint，`Authorization: Bearer <key>`，
  请求 {"image": "<base64>"}，约定响应 {"text": "..."}（兼容 {"words_result": [...]}）。
- `xunfei`：讯飞开放平台印刷文字识别（标准 API，HMAC-SHA256 签名）。
  需要 APIKey + APISecret + engine_id（默认 sf8e6aca1 通用印刷）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from email.utils import formatdate
from typing import Optional

import httpx


class OcrError(Exception):
    pass


class HttpOcrProvider:
    """通用 HTTP OCR（约定式 JSON 响应）。"""

    def __init__(self, endpoint: str, api_key: str = "",
                 client: Optional[httpx.AsyncClient] = None,
                 timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    async def _ac(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    @staticmethod
    def _parse(data: dict) -> str:
        if isinstance(data.get("text"), str) and data["text"].strip():
            return data["text"].strip()
        words = data.get("words_result")
        if isinstance(words, list):
            return "\n".join(str(w.get("words", "")) for w in words if isinstance(w, dict)).strip()
        raise OcrError(f"无法解析的 OCR 响应: {str(data)[:200]}")

    async def image_to_text(self, image_b64: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        client = await self._ac()
        try:
            resp = await client.post(self.endpoint,
                                     json={"image": image_b64}, headers=headers)
        except httpx.HTTPError as e:
            raise OcrError(f"网络错误: {e!r}") from e
        if resp.status_code != 200:
            raise OcrError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return self._parse(resp.json())
        except ValueError as e:
            raise OcrError(f"响应非 JSON: {resp.text[:200]}") from e


def xunfei_auth_header(api_key: str, api_secret: str, host: str,
                       path: str, date_rfc1123: str) -> str:
    """讯飞开放平台标准签名（HMAC-SHA256）。纯函数，可单测。

    signature_origin = "host: {host}\\ndate: {date}\\nGET {path} HTTP/1.1"
    authorization   = base64('api_key="...", algorithm="hmac-sha256",
                              headers="host date request-line", signature="..."')
    """
    signature_origin = (f"host: {host}\ndate: {date_rfc1123}\n"
                        f"GET {path} HTTP/1.1")
    signature_sha = hmac.new(api_secret.encode("utf-8"),
                             signature_origin.encode("utf-8"),
                             digestmod=hashlib.sha256).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"')
    return base64.b64encode(authorization_origin.encode("utf-8")).decode("utf-8")


class XunfeiOcrProvider:
    """讯飞印刷文字识别（专用协议；星火认知大模型本身走 Chat Completion，不在本类）。"""

    def __init__(self, api_key: str, api_secret: str,
                 engine_id: str = "sf8e6aca1",
                 host: str = "api.xf-yun.com",
                 client: Optional[httpx.AsyncClient] = None,
                 timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.engine_id = engine_id
        self.host = host
        self.timeout = timeout
        self._client = client

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.api_secret and self.engine_id)

    @property
    def path(self) -> str:
        return f"/v1/private/{self.engine_id}"

    async def _ac(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def image_to_text(self, image_b64: str) -> str:
        date_rfc1123 = formatdate(time.time(), usegmt=True)
        headers = {
            "Content-Type": "application/json",
            "Host": self.host,
            "Date": date_rfc1123,
            "Authorization": xunfei_auth_header(
                self.api_key, self.api_secret, self.host, self.path, date_rfc1123),
        }
        client = await self._ac()
        try:
            resp = await client.post(
                f"https://{self.host}{self.path}",
                json={"image": image_b64}, headers=headers)
        except httpx.HTTPError as e:
            raise OcrError(f"网络错误: {e!r}") from e
        if resp.status_code != 200:
            raise OcrError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if str(data.get("code")) != "0":
            raise OcrError(f"讯飞 OCR 业务错误: code={data.get('code')} "
                           f"desc={data.get('desc')}")
        # 成功响应：data.data.block[0].line[0].word[0].content
        try:
            blocks = data["data"]["block"]
            lines: list[str] = []
            for b in blocks:
                for line in b.get("line", []):
                    words = "".join(str(w.get("content", ""))
                                    for w in line.get("word", []))
                    if words:
                        lines.append(words)
            text = "\n".join(lines).strip()
        except (KeyError, TypeError, AttributeError) as e:
            raise OcrError(f"响应结构异常: {str(data)[:200]}") from e
        if not text:
            raise OcrError("OCR 结果为空")
        return text


def build_ocr_provider(provider: str, endpoint: str, api_key: str,
                       api_secret: str = "", engine_id: str = "sf8e6aca1"):
    if provider == "http":
        return HttpOcrProvider(endpoint, api_key)
    if provider == "xunfei":
        return XunfeiOcrProvider(api_key, api_secret, engine_id)
    raise OcrError(f"未知 OCR provider: {provider!r}（可选 http|xunfei）")
