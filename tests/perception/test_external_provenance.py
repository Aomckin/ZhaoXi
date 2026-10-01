"""Real Perception/Planner/Agent pipeline smoke with an isolated fake provider."""
from test_v131 import make_runtime,qq_event
from zhaoxi_ext.qq_napcat.codec import decode
from zhaoxi.models.types import ModelResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext,set_current_turn,reset_current_turn
from zhaoxi.cognitive_stream.models import CognitiveEventType
import pytest


@pytest.mark.parametrize("kind",["private","group"])
async def test_external_owner_trigger_reaches_planner_and_agent_with_source(tmp_path,kind):
    seen=[]
    async def generate(messages,tools):
        seen.append(messages)
        return ModelResponse(content='{"reply":true}' if "外部认知 Planner" in messages[0].content else "收到")
    runtime,agent=make_runtime(tmp_path,generate)
    item=decode(qq_event(901,text="晚上继续改朝汐。",kind=kind),self_id="42",owner_id="8")
    if kind=="group":item=item.model_copy(update={"directed_to_zhaoxi":True})
    assert await runtime.ingest(item)=="收到"
    for messages in seen:
        current=next(m for m in messages if m.metadata.get("timeline_scope")=="current_trigger")
        assert current.role is Role.USER and "QQ" in current.content and "当前输入" in current.content
        assert current.metadata["origin_conversation_kind"]==kind
    await runtime.reply_sent(item,"收到",1)
    reply=next(e for e in agent.experience_stream.recent(8) if e.event_type==CognitiveEventType.ASSISTANT_REPLY)
    assert reply.conversation_id==item.conversation_id and reply.metadata["conversation_kind"]==kind
    assert reply.metadata["source_plugin"]==item.source_plugin
    trigger=agent.cognitive_ingress.desktop("继续吧")
    view=Conversation();view.add_user(trigger.content)
    token=set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:messages=agent.context_builder.build(view)
    finally:reset_current_turn(token)
    received=next(m for m in messages if m.metadata.get("origin_actor_role")=="OWNER" and m.metadata.get("origin_channel")=="qq")
    assert received.role is Role.USER and "QQ" in received.content and received.metadata["cross_context"]
    assert any(m.role is Role.ASSISTANT and m.metadata.get("origin_channel")=="qq" and m.metadata["origin_conversation_id"]==item.conversation_id for m in messages)
    if getattr(agent,"maintenance_gateway",None):await agent.maintenance_gateway.maintenance_queue().shutdown()


async def test_adjacent_historical_picture_is_not_new_trigger_image(tmp_path):
    seen=[]
    async def generate(messages,tools):
        seen.append(messages)
        return ModelResponse(content='{"reply":true}' if "外部认知 Planner" in messages[0].content else "收到")
    runtime,agent=make_runtime(tmp_path,generate)
    # The resolver is deliberately isolated; this checks the runtime's reuse branch.
    from unittest.mock import AsyncMock
    picture="data:image/png;base64,YWJj"
    runtime._images=AsyncMock(return_value=[picture])
    first=decode(qq_event(910,text="",image=picture),self_id="42",owner_id="8")
    await runtime.ingest(first)
    original=next(e for e in agent.experience_stream.recent(10) if e.event_type==CognitiveEventType.EXTERNAL_MESSAGE)
    seen.clear()
    followup=decode(qq_event(911,text="刚才这张图呢？"),self_id="42",owner_id="8")
    assert await runtime.ingest(followup)=="收到"
    current=next(m for m in seen[0] if m.metadata.get("timeline_scope")=="current_trigger")
    assert current.metadata["image_timeline_scope"]=="recent" and current.metadata["image_origin_event_id"]==original.event_id
    assert '\"timeline_scope\":\"recent\"' in current.content and "历史图片" in current.content
    if getattr(agent,"maintenance_gateway",None):await agent.maintenance_gateway.maintenance_queue().shutdown()
