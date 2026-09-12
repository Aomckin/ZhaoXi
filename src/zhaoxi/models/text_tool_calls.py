"""Normalize supported textual tool-call protocols at the provider boundary."""

import html
import json
import re
from typing import Any

from zhaoxi.errors import ProviderError
from zhaoxi.models.types import ToolCall


_PIPE = r"[|｜]"
_PREFIX = rf"{_PIPE}\s*(?:{_PIPE}\s*)?DSML\s*{_PIPE}(?:\s*{_PIPE})?\s*"
_MARKER_RE = re.compile(rf"<\s*/?\s*{_PREFIX}", re.IGNORECASE)
_BLOCK_RE = re.compile(
    rf"<\s*{_PREFIX}tool_calls\s*>(.*?)<\s*/\s*{_PREFIX}tool_calls\s*>",
    re.IGNORECASE | re.DOTALL,
)
_INVOKE_RE = re.compile(
    rf"<\s*{_PREFIX}invoke\b(?P<attrs>[^>]*)>(?P<body>.*?)"
    rf"<\s*/\s*{_PREFIX}invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAMETER_RE = re.compile(
    rf"<\s*{_PREFIX}parameter\b(?P<attrs>[^>]*)>(?P<value>.*?)"
    rf"<\s*/\s*{_PREFIX}parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTRIBUTE_RE = re.compile(
    r"([A-Za-z_][\w.-]*)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|“([^”]*)”|”([^“]*)“)",
    re.DOTALL,
)
_QWEN_MARKER_RE = re.compile(
    r"<\s*/?\s*tool_call\b[^>]*>|<\s*function\s*=",
    re.IGNORECASE,
)
_QWEN_BLOCK_RE = re.compile(
    r"<\s*tool_call\s*>(.*?)<\s*/\s*tool_call\s*>",
    re.IGNORECASE | re.DOTALL,
)
_QWEN_FUNCTION_RE = re.compile(
    r"<\s*function\s*=\s*(?P<name>[A-Za-z_][\w.-]*)\s*>(?P<body>.*?)"
    r"<\s*/\s*function\s*>",
    re.IGNORECASE | re.DOTALL,
)
_QWEN_PARAMETER_RE = re.compile(
    r"<\s*parameter\s*=\s*(?P<name>[A-Za-z_][\w.-]*)\s*>(?P<value>.*?)"
    r"<\s*/\s*parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)


def normalize_text_tool_calls(
    content: str | None, *, id_prefix: str = "text-call"
) -> tuple[str | None, list[ToolCall]]:
    """Extract supported textual calls and remove all protocol text from content.

    Native provider tool calls are handled separately and take precedence. Text
    without a known marker is returned unchanged. Once a marker is present,
    malformed protocol is rejected so it can never reach the UI.
    """
    if not content:
        return content, []

    if _QWEN_MARKER_RE.search(content):
        cleaned, calls = _normalize_qwen_tool_calls(content, id_prefix=id_prefix)
        if cleaned and _MARKER_RE.search(cleaned):
            raise ProviderError("模型返回了混合的文本工具调用协议。")
        return cleaned, calls
    if not _MARKER_RE.search(content):
        return content, []

    calls: list[ToolCall] = []
    blocks = list(_BLOCK_RE.finditer(content))
    if not blocks:
        raise ProviderError("模型返回了无法解析的文本工具调用协议。")

    for block in blocks:
        block_body = block.group(1)
        invokes = list(_INVOKE_RE.finditer(block_body))
        if not invokes or _INVOKE_RE.sub("", block_body).strip():
            raise ProviderError("模型返回了无法解析的文本工具调用协议。")
        for invoke in invokes:
            invoke_attrs = _parse_attributes(invoke.group("attrs"))
            name = invoke_attrs.get("name", "").strip()
            if not name:
                raise ProviderError("模型返回的文本工具调用缺少工具名称。")

            arguments: dict[str, Any] = {}
            invoke_body = invoke.group("body")
            parameters = list(_PARAMETER_RE.finditer(invoke_body))
            if _PARAMETER_RE.sub("", invoke_body).strip():
                raise ProviderError("模型返回了无法解析的文本工具参数。")
            for parameter in parameters:
                attrs = _parse_attributes(parameter.group("attrs"))
                parameter_name = attrs.get("name", "").strip()
                if not parameter_name or parameter_name in arguments:
                    raise ProviderError("模型返回的文本工具参数名称无效或重复。")
                arguments[parameter_name] = _parse_parameter_value(
                    html.unescape(parameter.group("value").strip()), attrs
                )

            calls.append(ToolCall(
                id=f"{id_prefix}-{len(calls) + 1}",
                name=html.unescape(name),
                arguments=arguments,
            ))

    cleaned = _BLOCK_RE.sub("", content)
    if _MARKER_RE.search(cleaned):
        raise ProviderError("模型返回了无法解析的文本工具调用协议。")
    cleaned = cleaned.strip()
    return cleaned or None, calls


def _normalize_qwen_tool_calls(
    content: str, *, id_prefix: str
) -> tuple[str | None, list[ToolCall]]:
    calls: list[ToolCall] = []
    blocks = list(_QWEN_BLOCK_RE.finditer(content))
    if not blocks:
        raise ProviderError("模型返回了无法解析的文本工具调用协议。")

    for block in blocks:
        block_body = block.group(1)
        functions = list(_QWEN_FUNCTION_RE.finditer(block_body))
        if not functions or _QWEN_FUNCTION_RE.sub("", block_body).strip():
            raise ProviderError("模型返回了无法解析的文本工具调用协议。")
        for function in functions:
            arguments: dict[str, Any] = {}
            function_body = function.group("body")
            parameters = list(_QWEN_PARAMETER_RE.finditer(function_body))
            if _QWEN_PARAMETER_RE.sub("", function_body).strip():
                raise ProviderError("模型返回了无法解析的文本工具参数。")
            for parameter in parameters:
                name = parameter.group("name")
                if name in arguments:
                    raise ProviderError("模型返回的文本工具参数名称无效或重复。")
                arguments[name] = html.unescape(parameter.group("value").strip())
            calls.append(ToolCall(
                id=f"{id_prefix}-{len(calls) + 1}",
                name=function.group("name"),
                arguments=arguments,
            ))

    cleaned = _QWEN_BLOCK_RE.sub("", content)
    if _QWEN_MARKER_RE.search(cleaned):
        raise ProviderError("模型返回了无法解析的文本工具调用协议。")
    cleaned = cleaned.strip()
    return cleaned or None, calls


def _parse_attributes(raw: str) -> dict[str, str]:
    attributes = {
        match.group(1): html.unescape(next(value for value in match.groups()[1:] if value is not None))
        for match in _ATTRIBUTE_RE.finditer(raw)
    }
    if _ATTRIBUTE_RE.sub("", raw).strip():
        raise ProviderError("模型返回了无法解析的文本工具调用属性。")
    return attributes


def _parse_parameter_value(value: str, attrs: dict[str, str]) -> Any:
    kind = attrs.get("type", "").lower()
    if attrs.get("json", "").lower() == "true" or kind == "json":
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderError("模型返回的文本工具参数不是有效 JSON。") from exc
    if attrs.get("boolean", "").lower() == "true" or kind in {"bool", "boolean"}:
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        raise ProviderError("模型返回的文本工具布尔参数无效。")
    if attrs.get("number", "").lower() == "true" or kind in {"int", "integer", "float", "number"}:
        try:
            number = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderError("模型返回的文本工具数字参数无效。") from exc
        if isinstance(number, bool) or not isinstance(number, int | float):
            raise ProviderError("模型返回的文本工具数字参数无效。")
        return number
    return value
