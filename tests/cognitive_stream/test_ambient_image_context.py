"""Ambient group pixels are opt-in on the desk; real image requests stay usable."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from zhaoxi.cognitive_stream import ExperienceStream, AttentionRetriever
from zhaoxi.cognitive_stream.models import EventPart
from zhaoxi.cognitive_stream.timeline import cognitive_timeline
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.fast_chat import FastChatRuntime
from zhaoxi.core.message import Message, Role
from zhaoxi.core.references import set_references, reset_references
from test_provenance import event, PIC


@pytest.mark.parametrize("channel", ["desktop", "web", "qq"])
def test_ambient_group_images_are_descriptions_on_desk_only(tmp_path, channel):
    stream = ExperienceStream(tmp_path / "experience.db")
    when = datetime.now(UTC) - timedelta(minutes=5)
    group = stream.append(event(kind="group", parts=[EventPart(type="image",url=PIC)], occurred_at=when))
    private = stream.append(event(kind="private", parts=[EventPart(type="image",url=PIC)], occurred_at=when))
    local = stream.append(event(channel="desktop",parts=[EventPart(type="image",url=PIC)],occurred_at=when))
    messages = cognitive_timeline(stream,output_channel=channel,audience="owner")
    by_id = {m.message_id:m for m in messages}
    if channel in {"desktop","web"}:
        assert not by_id[group.event_id].images
        assert by_id[group.event_id].metadata["ambient_images_omitted"] == 1
        assert "QQ 群聊历史附图 1 张" in by_id[group.event_id].content
    else:
        assert by_id[group.event_id].images == [PIC]
    assert by_id[private.event_id].images == [PIC]
    if channel != "qq": assert by_id[local.event_id].images == [PIC]
    assert stream.get(group.event_id).parts[0].url == PIC


@pytest.mark.parametrize("fast", [False, True])
def test_owner_group_history_does_not_enter_ordinary_desk_chat(tmp_path, fast):
    stream = ExperienceStream(tmp_path / "experience.db")
    for i in range(8):
        stream.append(event(kind="group", content=f"group photo {i}",parts=[EventPart(type="image",url=PIC)],
                            occurred_at=datetime.now(UTC)-timedelta(minutes=10-i)))
    trigger = stream.append(event(channel="desktop",content="摸狗头",occurred_at=datetime.now(UTC)))
    conv = Conversation();conv.add_user(trigger.content)
    builder = ContextBuilder("persona");builder.attention_retriever=AttentionRetriever(stream)
    token = set_current_turn(CognitiveTurnContext(trigger,request_id="isolated-ambient"))
    try:
        if fast:
            runtime = FastChatRuntime(SimpleNamespace(context_builder=builder,experience_stream=stream,
                attention_retriever=builder.attention_retriever,conversation=conv))
            messages=runtime._recent_owner_conversation(trigger.content,output_channel="desktop",audience="owner")
        else:
            messages=builder.build(conv)
        assert not any(m.images for m in messages)
        assert sum(m.metadata.get("ambient_images_omitted",0) for m in messages) == (7 if fast else 8)
        assert any("group photo" in m.content for m in messages if m.content)
    finally: reset_current_turn(token)


def test_new_image_and_explicit_social_retrieval_still_reach_model(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    trigger=stream.append(event(channel="desktop",content="看新图",parts=[EventPart(type="image",url=PIC)]))
    conv=Conversation();conv.add_user(trigger.content,images=[PIC])
    conv.add(Message(message_id="social-image:explicit",role=Role.EXTERNAL,content="explicit retrieval",
        images=[PIC],source="qq",metadata={"origin_channel":"qq","origin_conversation_kind":"group",
        "timeline_scope":"attention","image_timeline_scope":"attention"}))
    builder=ContextBuilder("persona");builder.attention_retriever=AttentionRetriever(stream)
    token=set_current_turn(CognitiveTurnContext(trigger,request_id="isolated-explicit",images=(PIC,)))
    try:
        messages=builder.build(conv)
        assert any(m.message_id==trigger.event_id and m.images for m in messages)
        assert any(m.message_id=="social-image:explicit" and m.images for m in messages)
    finally:reset_current_turn(token)


def test_explicit_reference_keeps_image_outside_ambient_timeline(tmp_path):
    stream=ExperienceStream(tmp_path/"experience.db")
    old=stream.append(event(kind="group",parts=[EventPart(type="image",url=PIC)]))
    builder=ContextBuilder("persona");builder.attention_retriever=AttentionRetriever(stream)
    conv=Conversation();conv.add_user("看我引用的图片")
    token=set_references({"items":[{"view":{"message_id":old.event_id},"content":"original ref",
                                 "images":[PIC],"event_id":old.event_id}]})
    try:
        messages=builder.build(conv)
        assert sum(len(m.images) for m in messages)==1
    finally:reset_references(token)
