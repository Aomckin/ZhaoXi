"""Create a short, safe spoken copy without changing the visible reply."""

from __future__ import annotations

import re


_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`([^`]+)`")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_RAW_JSON = re.compile(r"^\s*[\[{].*[\]}]\s*$", re.DOTALL)


def sanitize_for_speech(text: str, *, max_chars: int = 1200) -> str:
    if not text or _RAW_JSON.match(text):
        return ""
    value = _CODE_BLOCK.sub(" 回复中包含代码，请查看屏幕。 ", text)
    value = _MARKDOWN_LINK.sub(r"\1（链接）", value)
    value = _URL.sub("链接", value)
    value = _INLINE_CODE.sub(r"\1", value)
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
    value = re.sub(r"(?m)^\s*[-*+]\s+", "", value)
    value = re.sub(r"[*_~>]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > max_chars:
        value = value[: max_chars - 8].rstrip() + "。内容较长，请查看屏幕。"
    return value

