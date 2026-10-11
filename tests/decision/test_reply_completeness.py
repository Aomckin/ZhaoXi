"""Incomplete provider envelopes must never become successful partial replies."""
import json
import httpx
import pytest
from zhaoxi.core.message import Message, Role
from zhaoxi.decision.reply import REPLY_FORMAT, decode_main_reply
from zhaoxi.errors import AgentLoopError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.types import ModelResponse


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "test-model"])
@pytest.mark.parametrize("payload_content", [{"reply":"This comparison is", "continuation":"unfinished"}, {"type":"json_object"}])
async def test_stop_with_missing_required_field_is_rejected_at_provider_boundary(model, payload_content):
    async def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"]["type"] == ("json_object" if "deepseek" in model else "json_schema")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(payload_content)}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(base_url="https://example.test/v1", api_key="test", model=model, client=client)
        response = await provider.generate([Message(role=Role.USER, content="Check this")], response_format=REPLY_FORMAT)
    assert response.raw_metadata["main_reply_contract"] is True
    with pytest.raises(AgentLoopError) as failure:
        decode_main_reply(response)
    assert failure.value.code == "invalid_reply_protocol"


@pytest.mark.parametrize("raw", [
    '{"reply":"Half a sentence"}',
    '{"reply":"Half a sentence","awareness":null}',
    '{"reply":"Half a sentence","awareness":{"mode":"NONE"},"continuation":"hidden"}',
    '{"reply":"Half a sentence","awareness":',
])
def test_incomplete_contract_not_saved_even_with_stop(raw):
    with pytest.raises(AgentLoopError):
        decode_main_reply(ModelResponse(content=raw, finish_reason="stop", raw_metadata={"main_reply_contract": True}))


@pytest.mark.parametrize("reason", ["length", "max_tokens", "content_filter"])
@pytest.mark.parametrize("raw", ["Half a sentence", '{"reply":"Half a sentence","awareness":{"mode":"NONE"}}'])
def test_provider_incomplete_finish_rejected_even_for_valid_json(reason, raw):
    with pytest.raises(AgentLoopError):
        decode_main_reply(ModelResponse(content=raw, finish_reason=reason))


def test_complete_short_reply_is_valid_without_length_heuristics():
    response = ModelResponse(content='{"reply":"OK","awareness":{"mode":"NONE"}}', finish_reason="stop", raw_metadata={"main_reply_contract": True})
    assert decode_main_reply(response).content == "OK"


@pytest.mark.parametrize("raw", ['{"reply":"唔，日程留好了。"}',
    '{"reply":"唔，日程留好了。","awareness":null}', '唔，日程留好了。'])
def test_repair_body_delivered_without_requiring_or_recording_auxiliary_metadata(raw):
    from zhaoxi.decision.reply import decode_reply_repair
    result = decode_reply_repair(ModelResponse(content=raw, finish_reason="stop", raw_metadata={"main_reply_contract":True}))
    assert result.content == "唔，日程留好了。"
    assert result.raw_metadata["main_reply_protocol"]["awareness"] == "not_requested"
    assert "decision-awareness" not in result.content


@pytest.mark.parametrize("raw", ['{"reply":"未完', '{"reply":"完整","continuation":"未完"}',
    '{"operation":"write","arguments":{}}', '{"reply":"<decision-awareness>secret</decision-awareness>"}',
    '{"reply":"<tool_call>secret</tool_call>"}'])
def test_repair_cannot_leak_truncated_envelope_or_internal_protocol(raw):
    from zhaoxi.decision.reply import decode_reply_repair
    with pytest.raises(AgentLoopError):
        decode_reply_repair(ModelResponse(content=raw, finish_reason="stop"))


@pytest.mark.parametrize("raw", [
    '{"type":"json_object"}', '{}', '{"value":42}', '[]', '[1,2]',
    'null', '42', 'true', '"config echo"',
    '```json\n{"type":"json_object"}\n```', '[{"type":"json_object"}',
])
@pytest.mark.parametrize("fast", [False, True])
def test_missing_reply_shape_cannot_use_literal_json_fallback_under_contract(raw, fast):
    with pytest.raises(AgentLoopError) as failure:
        decode_main_reply(ModelResponse(content=raw, finish_reason="stop",
                          raw_metadata={"main_reply_contract": True}), fast=fast)
    assert failure.value.code == "invalid_reply_protocol"


def test_requested_json_can_still_be_quoted_inside_valid_reply():
    body = '{"type":"json_object"}'
    raw = json.dumps({"reply": body, "awareness": {"mode": "NONE"}})
    response = decode_main_reply(ModelResponse(content=raw, finish_reason="stop",
                                raw_metadata={"main_reply_contract": True}))
    assert response.content == body
