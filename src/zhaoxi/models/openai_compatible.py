"""OpenAI-compatible chat-completions provider."""

import json
from typing import Any, Sequence

import httpx

from zhaoxi.core.message import Message
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse, ToolCall


class OpenAICompatibleProvider(ModelProvider):
    """Call an OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client

    async def generate(
        self,
        messages: Sequence[Message],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_provider_dict() for message in messages],
            "temperature": kwargs.get("temperature", self.temperature),
        }
        max_tokens = kwargs.get("max_tokens", self.max_tokens)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        tool_choice = kwargs.get("tool_choice")
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        response_format = kwargs.get("response_format")
        if response_format is not None:
            payload["response_format"] = response_format

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            calls = []
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                raw_arguments = function.get("arguments", "{}")
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"模型返回了无效的工具参数 JSON：{exc}") from exc
                calls.append(ToolCall(id=call["id"], name=function["name"], arguments=arguments))
            return ModelResponse(
                content=message.get("content"),
                tool_calls=calls,
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage", {}),
                raw_metadata={"id": data.get("id"), "model": data.get("model")},
            )
        except ProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip().replace("\n", " ")[:500]
            raise ProviderError(
                f"模型请求失败：HTTP {exc.response.status_code} {detail or exc.response.reason_phrase}"
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"模型请求失败：{exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
