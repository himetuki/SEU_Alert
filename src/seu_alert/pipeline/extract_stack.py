"""投稿提取栈（ADR-023）。

投稿（图片/口语/混乱格式）进入分类树之前，先变成干净的 RawEvent.text：
    图片 →[vision OCR]→ 文本 →[big 整理]→ 规范文本
                                    ↓ 失败/未配
                              [small 备用] → 规范文本
                                    ↓ 失败
                              原文 + low_conf（进人工复核）

结构化分类仍由 JEV 分类树负责；本层只做"图→文、口语→规范文本"。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .llm import ChatClient, ChatError
from .ocr import OcrError

VISION_SYSTEM = (
    "你是校园通知 OCR 转录助手。把图片中的文字完整、按原顺序转录为简体中文纯文本。"
    "不要总结、不要翻译、不要添加图片中不存在的内容。只输出转录文本。"
)
NORMALIZE_SYSTEM = (
    "你是校园通知整理助手。用户投喂的原始文本可能是口语、截图转录或聊天记录。"
    "请整理成一条规范的通知文本：保留课程名、事项、截止时间、提交平台、来源等全部事实信息，"
    "去除语气词、表情、寒暄和与通知无关的内容。不要编造任何信息。只输出整理后的文本。"
)


@dataclass(frozen=True)
class ExtractResult:
    text: str
    chain_used: tuple[str, ...]
    low_conf: bool
    note: str = ""


class SubmissionExtractor:
    def __init__(self, vision: Optional[ChatClient] = None,
                 big: Optional[ChatClient] = None,
                 small: Optional[ChatClient] = None,
                 ocr=None,
                 chain: tuple[str, ...] = ("vision", "big", "small")) -> None:
        self.vision = vision
        self.big = big
        self.small = small
        self.ocr = ocr                    # 专用 OCR 协议 provider（ocr.py）
        self.chain = tuple(chain)

    async def _image_to_text(self, image_b64: str, used: list[str]) -> str:
        """图片 → 文本：先专用 OCR 协议（ocr），后视觉模型（vision，Chat Completion）。"""
        # 1) 专用 OCR 协议（讯飞等；星火认知模型走 Chat Completion 时不需要这层）
        if "ocr" in self.chain and self.ocr is not None and getattr(self.ocr, "enabled", False):
            try:
                text = (await self.ocr.image_to_text(image_b64)).strip()
                if text:
                    used.append("ocr")
                    return text
            except OcrError:
                pass                         # 落到 vision
        # 2) 视觉模型（Chat Completion 协议看图）
        if "vision" in self.chain and self.vision and self.vision.enabled:
            try:
                r = await self.vision.complete(VISION_SYSTEM,
                                               "请转录这张图片中的全部文字。",
                                               image_b64=image_b64)
                if r.text.strip():
                    used.append("vision")
                    return r.text.strip()
            except ChatError:
                pass
        return ""

    async def extract(self, text: Optional[str] = None,
                      image_b64: Optional[str] = None) -> ExtractResult:
        used: list[str] = []
        cur = (text or "").strip()

        # 图片 → 文本（专用 OCR / 视觉模型，均为 Chat Completion 兼容或专用协议）
        if image_b64 and not cur:
            cur = await self._image_to_text(image_b64, used)

        if not cur:
            return ExtractResult(text="", chain_used=tuple(used), low_conf=True,
                                 note="无可用文本：图片转录失败且无文字投稿")

        # 2) 大模型整理（可选层）
        if "big" in self.chain and self.big and self.big.enabled:
            try:
                r = await self.big.complete(NORMALIZE_SYSTEM, cur)
                if r.text.strip():
                    cur = r.text.strip()
                    used.append("big")
            except ChatError:
                pass

        # 3) 小模型备用（大模型未生效时才需要）
        if ("big" not in used and "small" in self.chain
                and self.small and self.small.enabled):
            try:
                r = await self.small.complete(NORMALIZE_SYSTEM, cur)
                if r.text.strip():
                    cur = r.text.strip()
                    used.append("small")
            except ChatError:
                pass

        normalized = "big" in used or "small" in used
        return ExtractResult(text=cur, chain_used=tuple(used),
                             low_conf=not normalized,
                             note="" if normalized else "未经模型整理，低置信进复核")
