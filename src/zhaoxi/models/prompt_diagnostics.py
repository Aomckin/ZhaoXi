"""Length-only diagnostics for model inputs; never logs prompt content."""

from __future__ import annotations

import json
import logging
from math import ceil
from typing import Any, Sequence

from zhaoxi.core.message import Message, Role


logger = logging.getLogger("PROMPT")


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str))


def collect_prompt_diagnostics(
    messages: Sequence[Message], tools: list[dict[str, Any]] | None, *, model: str,
    tool_router: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return length-only accounting for the exact messages/tools input."""
    provider_messages = payload["messages"] if payload is not None else [message.to_provider_dict() for message in messages]
    components: list[tuple[str, int]] = []
    for index, message in enumerate(messages):
        if message.role == Role.SYSTEM:
            recorded = message.metadata.get("prompt_components")
            if isinstance(recorded, list):
                for item in recorded:
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        components.append((item["name"], int(item.get("chars", 0))))
            else:
                components.append(("system_prompt", len(message.content or "")))
        else:
            components.append((f"conversation_history.{index}.{message.role.value}", _json_chars(provider_messages[index])))

    for index, schema in enumerate(tools or []):
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = function.get("name") if isinstance(function, dict) else None
        components.append((f"tool_schema.{name or index}", _json_chars(schema)))

    input_payload = payload if payload is not None else {"messages": provider_messages}
    if payload is None and tools:
        input_payload["tools"] = tools
    total_chars = _json_chars(input_payload)
    measured_chars = sum(size for _, size in components)
    components.append(("request.json_envelope", max(0, total_chars - measured_chars)))
    categories = {name: 0 for name in (
        "system_prompt", "recent_messages", "memory_snapshot", "retrieved_memory",
        "tool_schema", "tool_result", "planner_state", "other",
    )}
    for name, chars in components:
        category = (
            "memory_snapshot" if name in {"runtime.agenda", "runtime.short_term_memory"} else
            "retrieved_memory" if name == "memory.recall" else
            "planner_state" if name == "extra.planner_context" else
            "tool_schema" if name.startswith("tool_schema.") else
            "tool_result" if name.startswith("conversation_history.") and name.endswith(".tool") else
            "recent_messages" if name.startswith("conversation_history.") else
            "other" if name == "request.json_envelope" else "system_prompt"
        )
        categories[category] += chars
    image_urls = [part.get("image_url", {}).get("url", "")
                  for message in provider_messages if isinstance(message, dict)
                  for part in (message.get("content") if isinstance(message.get("content"), list) else [])
                  if isinstance(part, dict) and part.get("type") == "image_url"]
    image_payload_chars = sum(len(url) for url in image_urls if isinstance(url, str))
    categories["recent_messages"] = max(0, categories["recent_messages"] - image_payload_chars)
    estimated = {name: ceil(chars / 4) for name, chars in categories.items()}
    return {
        "model": model,
        "input_chars": total_chars,
        "messages_chars": _json_chars(provider_messages),
        "tools_chars": _json_chars(tools or []),
        "tool_router": tool_router,
        "context_tokens_estimate": {**estimated, "image_tokens": None,
                                    "image_count": len(image_urls),
                                    "image_payload_chars": image_payload_chars,
                                    "total_text_tokens": sum(estimated.values())},
        "components": [
            {"name": name, "chars": size, "percent": round(size * 100 / total_chars, 2) if total_chars else 0}
            for name, size in components
        ],
    }


def log_prompt_diagnostics(
    messages: Sequence[Message], tools: list[dict[str, Any]] | None, *, model: str,
    tool_router: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Log component sizes only when DEBUG logging is enabled."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    report = collect_prompt_diagnostics(messages, tools, model=model, tool_router=tool_router, payload=payload)
    logger.debug(
        "model=%s input_chars=%d messages_chars=%d tools_chars=%d tool_router=%s components=%s",
        model,
        report["input_chars"],
        report["messages_chars"],
        report["tools_chars"],
        json.dumps(report["tool_router"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(report["components"], ensure_ascii=False, separators=(",", ":")),
    )


def log_prompt_usage(usage: dict[str, Any], *, model: str) -> None:
    """Record provider token accounting without assuming every API supplies it."""
    if not logger.isEnabledFor(logging.DEBUG):
        return
    prompt_tokens = usage.get("prompt_tokens")
    if prompt_tokens is None:
        prompt_tokens = usage.get("input_tokens")
    logger.debug(
        "model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        model,
        prompt_tokens if prompt_tokens is not None else "unavailable",
        usage.get("completion_tokens", usage.get("output_tokens", "unavailable")),
        usage.get("total_tokens", "unavailable"),
    )
