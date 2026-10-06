"""Retry authorization is local, explicit and bound to the current provenance."""
from dataclasses import replace
import pytest
from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
from zhaoxi.core.tool_retry import ToolRetryContext, is_explicit_retry, local_retry_scope


@pytest.mark.parametrize("text", ["不要再试一次", "只是引用‘再试一次’", "再试一次，发给别人", "再试一次，换个文件", "继续", "小金毛"])
def test_retry_rejects_ambiguous_negated_quoted_and_expanded_requests(text):
    assert not is_explicit_retry(text)


@pytest.mark.parametrize("change", [{"actor_id": "other-owner"}, {"actor_role": "EXTERNAL"},
                                   {"channel": "another-channel"}, {"session_id": "other-session"},
                                   {"conversation_id": "other-conversation"}])
def test_current_turn_identity_and_scope_must_match(change):
    event = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE, source="desktop", channel="web",
        session_id="local", actor_role="OWNER", actor_id="owner", content="请读取隔离记录")
    token = set_current_turn(CognitiveTurnContext(trigger_event=event, output_channel="web"))
    try:
        retry = ToolRetryContext.capture("previous", event.content)
        assert retry and retry.matches("再试一次")
    finally:
        reset_current_turn(token)
    token = set_current_turn(CognitiveTurnContext(trigger_event=event.model_copy(update=change), output_channel="web"))
    try:
        assert not retry.matches("再试一次")
    finally:
        reset_current_turn(token)


def test_retry_requires_known_scope_and_expires_without_durable_history():
    assert ToolRetryContext.capture("request", "请查询") is None
    with local_retry_scope("web", "local"):
        retry = ToolRetryContext.capture("request", "请查询")
        assert retry.matches("请再试一下吧")
        assert not replace(retry, created_at=retry.created_at - 301).matches("再试一次")
        assert ToolRetryContext.capture("request", "x" * 4001) is None
    assert not retry.matches("再试一次")


def test_public_turn_cannot_use_local_gateway_fallback():
    event = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE, source="desktop", channel="web",
        session_id="local", actor_role="OWNER", actor_id="owner", content="再试一次")
    with local_retry_scope("web", "local"):
        retry = ToolRetryContext.capture("previous", "请读取记录")
        token = set_current_turn(CognitiveTurnContext(trigger_event=event, output_channel="web", audience="public"))
        try:
            assert not retry.matches("再试一次")
            assert ToolRetryContext.capture("public", "请读取记录") is None
        finally:
            reset_current_turn(token)
