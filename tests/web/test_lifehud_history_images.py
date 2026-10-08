"""Original attachments survive a failed picture turn and an explicit follow-up."""
import base64
from io import BytesIO
from unittest.mock import AsyncMock
import json

import httpx
import pytest
from PIL import Image
from conftest import FakeProvider
from tools.lifehud_tool import LifeHudClient, LifeHudTool
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.errors import ProviderError, AgentLoopError
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.sdk import resolve_image_reference, current_turn_images


def photo(color):
    buffer = BytesIO()
    Image.new("RGB", (700, 600), color).save(buffer, format="PNG")
    raw = buffer.getvalue()
    return "data:image/png;base64," + base64.b64encode(raw).decode(), raw


@pytest.mark.parametrize("confirm", [False, True])
async def test_followup_uploads_selected_history_originals_and_current_in_order(confirm):
    first, raw1 = photo("red")
    second, raw2 = photo("blue")
    current, raw3 = photo("green")
    uploaded, records = [], []
    expected_raw = [raw2, raw1, raw3]
    def handler(request):
        if request.url.path == "/api/images":
            assert expected_raw[len(uploaded)] in request.content
            uploaded.append(request.content)
            return httpx.Response(200, json={"path": f"/uploads/{len(uploaded)}.png"})
        if request.method == "POST":
            records.append(json.loads(request.content))
            return httpx.Response(201, json={"id": "meal"})
        return httpx.Response(200, json={"id": "meal", "images": records[0]["images"]})
    tool = LifeHudTool(LifeHudClient("http://fixture.invalid", transport=httpx.MockTransport(handler)))
    tool.default_confirm_write = confirm
    registry = ToolRegistry()
    registry.register(tool)
    provider = FakeProvider([])
    provider.generate = AsyncMock(side_effect=ProviderError("fixture failure", code="provider_http_400"))
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"), tool_router_mode="all")
    with pytest.raises(AgentLoopError):
        await agent.run("将这两张晚饭照片存入 LifeHUD", images=[first, second])
    old = agent.conversation.messages[-1]
    refs = [f"<conversation-image:{old.message_id}:2>", f"<conversation-image:{old.message_id}:1>", "<current-message-image>"]
    call = ToolCall(id="save", name="lifehud", arguments={"operation": "record", "arguments": {
        "action": "create", "type": "meal", "description": "fixture dinner", "images": refs}})
    agent.provider = FakeProvider([ModelResponse(tool_calls=[call]), ModelResponse(content="已完成。")])
    result = await agent.run("继续完成刚才没存好的饮食记录，连同前面的照片和这张图一起存。", images=[current])
    assert refs[0] in "\n".join(m.content or "" for m in agent.provider.calls[0])
    assert any(m.message_id == old.message_id and m.images[0] != first for m in agent.provider.calls[0])
    if confirm:
        assert result.permission_confirmation is not None and not uploaded
        assert first not in str(result.permission_confirmation.request.arguments)
        # Approval uses the original offered-reference snapshot, even if the
        # earlier timeline photo is trimmed before the user confirms.
        agent.conversation.replace([m for m in agent.conversation.messages if m.message_id != old.message_id])
        result = await agent.approve_permission(result.permission_confirmation.confirmation_id)
    assert result.content == "已完成。"
    assert len(uploaded) == 3 and len(records) == 1
    assert records[0]["images"] == ["/uploads/1.png", "/uploads/2.png", "/uploads/3.png"]
    assert call.arguments["arguments"]["images"] == refs
    assert resolve_image_reference(refs[0]) is None and current_turn_images() == ()


@pytest.mark.parametrize("source,role,metadata,audience", [
    ("qq", Role.USER, {"actor_role": "OWNER", "session_id": "qq/private/8"}, "owner"),
    (None, Role.EXTERNAL, {"actor_role": "EXTERNAL"}, "owner"),
    (None, Role.USER, {"actor_role": "OWNER", "session_id": "other-session"}, "owner"),
    (None, Role.USER, {}, "public"),
])
def test_history_tool_refs_do_not_admit_foreign_or_public_images(source, role, metadata, audience):
    image, _ = photo("red")
    old = Message(role=role, content="old", images=[image], source=source, metadata=metadata)
    current = Message(role=Role.USER, content="continue")
    refs = {}
    messages = ContextBuilder("朝汐").build(Conversation([old, current]), audience=audience, tool_image_references=refs)
    assert refs == {} and not any("<conversation-image:" in (m.content or "") for m in messages)


async def test_unavailable_history_reference_fails_before_upload_or_write():
    from zhaoxi.permission.executor import ToolExecutor
    from zhaoxi.permission.models import InvocationOrigin
    image, _ = photo("red")
    tool = LifeHudTool(LifeHudClient("http://fixture.invalid", transport=httpx.MockTransport(
        lambda request: pytest.fail("No request may occur for missing attachment"))))
    tool.default_confirm_write = False
    registry = ToolRegistry()
    registry.register(tool)
    execution = await ToolExecutor(registry).execute("lifehud", {"operation": "record", "arguments": {
        "type": "meal", "images": ["<current-message-image>", "<conversation-image:missing:1>"]}},
        request_id="missing", origin=InvocationOrigin.AGENT, image_attachments=[image], image_references={})
    assert execution.result.error == "attachment_not_found"
    assert resolve_image_reference("<conversation-image:missing:1>") is None
    assert current_turn_images() == ()



def test_live_cognitive_history_reference_uses_original_event_image(tmp_path):
    from zhaoxi.cognitive_stream import ExperienceStream, AttentionRetriever, CognitiveIngress
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    image, _ = photo("red")
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    conversation = Conversation()
    old = conversation.add_user("原来没存成的晚餐", images=[image])
    old_event = ingress.desktop(old.content, message_id=old.message_id, images=[image], channel="web")
    current = conversation.add_user("继续把前面的照片存入饮食记录")
    trigger = ingress.desktop(current.content, message_id=current.message_id, channel="web")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    refs = {}
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger, output_channel="web"))
    try:
        messages = builder.build(conversation, output_channel="web", tool_image_references=refs)
    finally:
        reset_current_turn(token)
    expected = f"<conversation-image:{old_event.event_id}:1>"
    assert refs[expected] == image
    assert expected in "\n".join(m.content or "" for m in messages)
    assert conversation.messages[0].content == old.content



def test_local_history_is_not_offered_in_a_different_active_session():
    from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    image, _ = photo("red")
    old = Message(role=Role.USER, content="old", images=[image], metadata={"session_id": "local"})
    trigger = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE, source="desktop", channel="web",
        session_id="other-session", actor_role="OWNER", actor_id="owner", content="继续存图")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger, output_channel="web"))
    refs = {}
    try:
        ContextBuilder("朝汐").build(Conversation([old, Message(role=Role.USER, content="继续存图")]),
            output_channel="web", tool_image_references=refs)
    finally:
        reset_current_turn(token)
    assert not refs
