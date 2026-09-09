"""OpenAI-compatible chat-completions provider."""

import json
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Sequence

import httpx

from zhaoxi.core.message import Message
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.text_tool_calls import normalize_text_tool_calls
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
        thinking_settings_path: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = client
        self.thinking_settings_path = thinking_settings_path
        self.thinking_enabled = None
        if thinking_settings_path:
            try:
                value = json.loads(Path(thinking_settings_path).read_text(encoding='utf-8')).get('thinking_enabled')
                if isinstance(value, bool):
                    self.thinking_enabled = value
            except (OSError, ValueError):
                pass

    @property
    def supports_thinking(self):
        return urlparse(self.base_url).hostname == 'api.deepseek.com'

    def set_thinking(self, enabled):
        if not self.supports_thinking:
            raise ValueError('当前模型接口尚未支持思考开关')
        if self.thinking_settings_path:
            path = Path(self.thinking_settings_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps({'thinking_enabled': enabled}), encoding='utf-8')
            temp.replace(path)
        self.thinking_enabled = enabled


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
        if self.supports_thinking:
            if self.thinking_enabled is not None:
                payload['thinking'] = {'type': 'enabled' if self.thinking_enabled else 'disabled'}
            for original, outgoing in zip(messages, payload['messages']):
                if original.tool_calls and original.metadata.get('reasoning_content') is not None:
                    outgoing['reasoning_content'] = original.metadata['reasoning_content']
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
            content, text_calls = normalize_text_tool_calls(
                message.get("content"), id_prefix=f"text-{data.get('id') or 'response'}"
            )
            if not calls:
                calls = text_calls
            return ModelResponse(
                content=content,
                tool_calls=calls,
                finish_reason=choice.get("finish_reason"),
                usage=data.get("usage", {}),
                raw_metadata={"id": data.get("id"), "model": data.get("model"),
                              **({"reasoning_content": message["reasoning_content"]} if isinstance(message.get("reasoning_content"), str) else {})},
            )
        except ProviderError:
            raise
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip().replace("\n", " ")[:500]
            status = exc.response.status_code
            raise ProviderError(
                f"模型请求失败：HTTP {status} {detail or exc.response.reason_phrase}",
                code=f"provider_http_{status}",
                retryable=status in {408, 429, 502, 503, 504},
            ) from exc
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            retryable = isinstance(exc, httpx.HTTPError)
            raise ProviderError(
                f"模型请求失败：{exc}",
                code="provider_transport_error" if retryable else "provider_response_invalid",
                retryable=retryable,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()
