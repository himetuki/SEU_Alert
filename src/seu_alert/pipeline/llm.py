"""Chat Completion 客户端（ADR-023：大模型/小模型/视觉模型统一走此协议）。

纪律：
- **neohorse-1-9b 等模型禁止携带任何思考参数**（ADR-017：带了就 400），
  `suppress_reasoning=True` 时请求体绝不出现 reasoning 字段；
- 非流式 JSON；返回文本 + usage（token 用量由调用方落 model_calls 表）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    latency_ms: int
    in_tokens: int = 0
    out_tokens: int = 0
    raw: Optional[dict] = None


class ChatError(Exception):
    def __init__(self, message: str, status: int = 0, trace_id: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.trace_id = trace_id


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str, *,
                 suppress_reasoning: bool = True, timeout: float = 60.0,
                 client: Optional[httpx.AsyncClient] = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.suppress_reasoning = suppress_reasoning
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.model)

    async def _ac(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def complete(self, system: str, user: str,
                       image_b64: Optional[str] = None) -> ChatResult:
        """一次 Chat Completion；image_b64 为 PNG base64（不带 data: 前缀）。"""
        if not self.enabled:
            raise ChatError(f"客户端未配置（model={self.model!r}）")
        content: Any = user
        if image_b64:
            content = [
                {"type": "text", "text": user},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "stream": False,
        }
        # suppress_reasoning=True → 绝不发送任何 reasoning 字段（ADR-017）
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = await self._ac()
        t0 = time.monotonic()
        try:
            resp = await client.post(f"{self.base_url}/v1/chat/completions",
                                     json=body, headers=headers)
        except (httpx.HTTPError, UnicodeError, ValueError) as e:
            # UnicodeError：密钥含非 ASCII（如未替换的占位符）时 httpx 构 header 会抛
            raise ChatError(f"请求失败: {e!r}") from e
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code != 200:
            trace = ""
            try:
                trace = str(resp.json().get("traceId", ""))
            except Exception:
                pass
            raise ChatError(f"HTTP {resp.status_code}: {resp.text[:200]}",
                            resp.status_code, trace)
        data = resp.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ChatError(f"响应结构异常: {str(data)[:200]}") from e
        usage = data.get("usage") or {}
        return ChatResult(text=text.strip(), model=self.model,
                          latency_ms=latency,
                          in_tokens=int(usage.get("prompt_tokens") or 0),
                          out_tokens=int(usage.get("completion_tokens") or 0),
                          raw=data)
