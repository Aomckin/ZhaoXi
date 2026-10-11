"""Original-message references across transport, model context, history and retries."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.core.references import current_references, reference_prompt, reference_image_messages, set_references, reset_references
from zhaoxi.errors import AgentLoopError
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import UnifiedMessage
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.web.app import create_app

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII="


class CaptureAgent:
    def __init__(self):
        self.conversation = Conversation()
        self.proactive = self.proactive_scheduler = self.proactive_state = None
        self.tool_executor = SimpleNamespace(gateway=SimpleNamespace(store=SimpleNamespace(pending={})))
        self._pending_permissions = {}
        self.planner = self.workflow = None
        self.calls = []
        self.fail = False

    async def run_natural(self, content, *, images=None):
        self.conversation.add_user(content, images=images)
        self.calls.append(ContextBuilder("你是朝汐。").build(self.conversation))
        if self.fail:
            raise AgentLoopError("fixture failure")
        self.conversation.add_assistant("我明白你在回应哪条消息了。")
        return AgentResponse(content="我明白你在回应哪条消息了。", request_id="fixture", steps=1)


def request(target, **kwargs):
    return UnifiedMessage(channel="desktop", content="这件事", references=[{"message_id": target}], **kwargs)


def test_http_resolves_original_and_persists_link_without_copying_body():
    agent = CaptureAgent()
    source = agent.conversation.add_assistant("下午去会议室 A201。")
    with TestClient(create_app(agent=agent)) as client:
        payload = {"message": "真的吗？", "message_id": "client-user", "request_id": "stable",
                   "references": [{"message_id": source.message_id, "text": "伪造的原文"}]}
        first = client.post("/api/chat", json=payload)
        assert first.status_code == 200, first.text
        assert client.post("/api/chat", json=payload).json() == first.json()
        history = client.get("/api/session").json()["messages"]
        user = next(m for m in history if m["message_id"] == "client-user")
        assert user["content"] == "真的吗？" and user["images"] == []
        assert user["references"][0]["message_id"] == source.message_id
        assert user["references"][0]["text"] == source.content
        assert "伪造的原文" not in str(agent.calls)
        assert source.content in agent.calls[0][0].content
        assert len(agent.calls) == 1
        conflict = client.post("/api/chat", json={**payload, "request_id": "different"})
        assert conflict.status_code == 422
        assert conflict.headers["X-Zhaoxi-Error-Code"] == "message_id_conflict"


async def test_merged_part_points_at_exact_original_and_reuses_its_image():
    agent = CaptureAgent()
    source = agent.conversation.add_user("第一段\n\n第二段", images=[PNG])
    source.metadata["display_parts"] = [
        {"text": "第一段", "image_count": 0, "timestamp": "2026-10-11T01:00:00Z"},
        {"text": "第二段", "image_count": 1, "timestamp": "2026-10-11T01:01:00Z"},
    ]
    gateway = InterfaceGateway(agent)
    await gateway.chat(UnifiedMessage(channel="desktop", content="这张图", display_parts=[
        {"text": "这张图", "image_count": 0, "timestamp": "2026-10-11T01:02:00Z",
         "reference": {"message_id": source.message_id, "part_index": 1}}]))
    user = agent.conversation.messages[-2]
    assert user.content == "这张图" and user.images == []
    view = user.metadata["references"][0]
    assert (view["text"], view["part_index"], view["image_count"]) == ("第二段", 1, 1)
    assert view["timestamp"] == "2026-10-11T01:01:00Z"
    assert sum(m.images.count(PNG) for m in agent.calls[0]) == 1
    assert current_references() is None
    # Original-image handles still resolve to the original, never to a copied new upload.
    state = await gateway._resolve_references(UnifiedMessage(channel="web", content="继续", references=[view]))
    token = set_references(state)
    try:
        handles = {}
        reference_image_messages(handles)
        assert handles == {f"<conversation-image:{source.message_id}:1>": PNG}
    finally:
        reset_references(token)


async def test_old_history_resolves_after_restart_and_cannot_cross_sessions(tmp_path):
    agent = CaptureAgent()
    store = SQLiteSessionStore(tmp_path / "sessions.db", max_messages=2)
    agent.conversation = Conversation(max_messages=2)
    session = Session(conversation=agent.conversation)
    source = agent.conversation.add_user("窗口外的旧原消息", images=[PNG])
    agent.conversation.add_assistant("知道了")
    store.save_sync(session)
    agent.conversation.add_user("较新的消息")
    agent.conversation.add_assistant("新的回复")
    store.save_sync(session)
    foreign = Session()
    other = foreign.conversation.add_user("另一个会话的秘密")
    store.save_sync(foreign)
    restarted = store.get_sync(session.id)
    agent.conversation = restarted.conversation
    agent.session_record, agent.session_store = restarted, store
    assert all(m.message_id != source.message_id for m in agent.conversation.messages)
    assert not agent.conversation.evicted
    gateway = InterfaceGateway(agent)
    await gateway.chat(request(source.message_id))
    assert source.content in agent.calls[0][0].content
    saved = store.get_sync(session.id).conversation.messages[-2]
    assert saved.metadata["references"][0]["message_id"] == source.message_id
    assert saved.content == "这件事" and saved.images == []
    assert await store.history_message(session.id, other.message_id) is None
    with pytest.raises(AgentLoopError, match="原消息已不可用"):
        await gateway.chat(request(other.message_id))
    assert len(agent.calls) == 1


@pytest.mark.parametrize("target_kind", ["missing", "internal", "invalid_part"])
async def test_invalid_reference_rejected_before_accepting_input(target_kind):
    agent = CaptureAgent()
    source = agent.conversation.add_assistant("原消息", visibility="internal" if target_kind == "internal" else "conversation")
    target = {"message_id": "missing" if target_kind == "missing" else source.message_id}
    if target_kind == "invalid_part":
        target["part_index"] = 3
    with pytest.raises(AgentLoopError):
        await InterfaceGateway(agent).chat(UnifiedMessage(channel="web", content="回复", references=[target]))
    assert not agent.calls and len(agent.conversation.messages) == 1
    assert current_references() is None


async def test_regenerate_retains_reference_identity_and_does_not_duplicate_user():
    agent = CaptureAgent()
    source = agent.conversation.add_assistant("引用原消息")
    gateway = InterfaceGateway(agent)
    first = await gateway.chat(request(source.message_id))
    user = agent.conversation.messages[-2].model_copy(deep=True)
    await gateway.regenerate(first.message_id, request_id="retry-reference")
    assert agent.conversation.messages[-2] == user
    assert sum(m.role is Role.USER for m in agent.conversation.messages) == 1
    assert source.content in agent.calls[-1][0].content
    assert current_references() is None


async def test_failed_reply_retains_reference_and_resets_scope():
    agent = CaptureAgent()
    source = agent.conversation.add_assistant("原消息")
    agent.fail = True
    gateway = InterfaceGateway(agent)
    with pytest.raises(AgentLoopError):
        await gateway.chat(request(source.message_id))
    assert agent.conversation.messages[-1].metadata["references"][0]["message_id"] == source.message_id
    assert current_references() is None
    agent.fail = False
    await gateway.chat(UnifiedMessage(channel="web", content="新话题"))
    assert not agent.conversation.messages[-2].metadata.get("references")
    assert "本轮用户引用的原消息" not in agent.calls[-1][0].content
    assert "这条历史消息引用的原消息摘要" in str(agent.calls[-1])


async def test_cognitive_stream_keeps_reference_in_later_context(tmp_path):
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    from zhaoxi.cognitive_stream.store import ExperienceStream
    from zhaoxi.cognitive_stream.timeline import project_event
    from zhaoxi.core.references import with_reference_summary
    agent = CaptureAgent()
    agent.experience_stream = ExperienceStream(tmp_path / "experience.db")
    agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    source = agent.conversation.add_assistant("周末去公园")
    await InterfaceGateway(agent).chat(request(source.message_id))
    user = agent.conversation.messages[-2]
    event = agent.experience_stream.get(user.metadata["event_id"])
    assert event.content == "这件事"
    assert event.metadata["references"] == user.metadata["references"]
    assert source.content in with_reference_summary(project_event(event)).content


def test_reference_prompt_has_total_text_budget():
    token = set_references({"items": [{"view": {"message_id": str(i)}, "content": "甲" * 6000} for i in range(20)]})
    try:
        assert reference_prompt().count("甲") == 6000
    finally:
        reset_references(token)


async def test_registered_emoji_reference_reuses_local_media_and_handles_deleted_file(tmp_path):
    import base64
    agent = CaptureAgent()
    path = tmp_path / "emoji.png"
    path.write_bytes(base64.b64decode(PNG.split(",", 1)[1]))
    agent.emoji_manager = SimpleNamespace(image_path=lambda identity: path if identity == "known" and path.exists() else None)
    source = agent.conversation.add_assistant_image("/api/expression/emoji/known", source="emoji", emoji_id="known")
    gateway = InterfaceGateway(agent)
    state = await gateway._resolve_references(request(source.message_id))
    assert state["items"][0]["images"] == [PNG]
    path.unlink()
    state = await gateway._resolve_references(request(source.message_id))
    assert state["items"][0]["images"] == []
    assert state["items"][0]["view"]["image_count"] == 1


def test_cognitive_image_projection_is_not_sent_twice():
    source = Message(message_id="ui-source", role=Role.USER, content="原图", images=[PNG], metadata={"event_id": "stream-source"})
    state = {"items": [{"view": {"message_id": source.message_id}, "content": source.content,
                        "images": source.images, "event_id": "stream-source"}]}
    conversation = Conversation([source.model_copy(update={"message_id": "stream-source"}),
                                 Message(role=Role.USER, content="解释引用的图")])
    token = set_references(state)
    try:
        handles = {}
        messages = ContextBuilder("朝汐").build(conversation, tool_image_references=handles)
        assert sum(m.images.count(PNG) for m in messages) == 1
        assert handles == {"<conversation-image:ui-source:1>": PNG}
    finally:
        reset_references(token)


async def test_background_worker_does_not_inherit_foreground_reference():
    from zhaoxi.interfaces.maintenance import PostTurnMaintenanceQueue
    seen = []
    async def maintain(payload, phase):
        seen.append(current_references())
        return {}
    queue = PostTurnMaintenanceQueue(":memory:", maintain, phases=("check",))
    state = {"items": [{"view": {"message_id": "source"}, "content": "只在前台的引用", "images": [PNG]}]}
    token = set_references(state)
    try:
        queue.enqueue("test", {})
        assert current_references() is state
        await queue.worker
        assert seen == [None]
    finally:
        reset_references(token)
        queue.db.close()
