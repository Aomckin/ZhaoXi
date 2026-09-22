import json

import httpx

from zhaoxi.core.message import Message, Role
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.types import ToolCall


async def test_thinking_mode_drives_payload_and_persists(tmp_path):
    payloads = []

    async def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]
        })

    path = tmp_path / "settings.json"
    args = dict(
        base_url="https://example.test/v1",
        api_key="test",
        model="deepseek/deepseek-v4-flash",
        thinking_settings_path=str(path),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAICompatibleProvider(client=client, **args)
        tool_message = Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="t", name="tool")],
            metadata={"reasoning_content": "private reasoning"},
        )

        assert provider.thinking_enabled is None
        await provider.generate([tool_message])
        assert "thinking" not in payloads[-1]
        assert "reasoning_content" not in payloads[-1]["messages"][0]

        provider.set_thinking(True)
        await provider.generate(
            [tool_message],
            [{"type": "function", "function": {"name": "current_time", "parameters": {}}}],
            tool_choice={"type": "function", "function": {"name": "current_time"}},
        )
        assert payloads[-1]["thinking"] == {"type": "enabled"}
        assert payloads[-1]["messages"][0]["reasoning_content"] == "private reasoning"
        assert "tools" in payloads[-1]
        assert "tool_choice" not in payloads[-1]

        provider = OpenAICompatibleProvider(client=client, **args)
        assert provider.thinking_enabled is True

        provider.set_thinking(False)
        await provider.generate([tool_message], tool_choice="required")
        assert payloads[-1]["thinking"] == {"type": "disabled"}
        assert payloads[-1]["messages"][0]["reasoning_content"] == "private reasoning"
        assert payloads[-1]["tool_choice"] == "required"

        provider.set_thinking(None)
        assert json.loads(path.read_text(encoding="utf-8")) == {"thinking_enabled": None}
        await provider.generate([tool_message])
        assert "thinking" not in payloads[-1]
        assert "reasoning_content" not in payloads[-1]["messages"][0]

        provider = OpenAICompatibleProvider(client=client, **args)
        assert provider.thinking_enabled is None


def test_thinking_setting_is_not_limited_to_known_hosts(tmp_path):
    provider = OpenAICompatibleProvider(
        base_url="https://api.commandcode.ai/provider/v1",
        api_key="test",
        model="deepseek/deepseek-v4-flash",
        thinking_settings_path=str(tmp_path / "settings.json"),
    )
    provider.set_thinking(True)
    assert provider.thinking_enabled is True
