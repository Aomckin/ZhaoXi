"""Evidence expansion, raw boundaries, visual inputs and scoped runtime tools."""
import json
from datetime import UTC,datetime,timedelta
from types import SimpleNamespace
import pytest
from conftest import FakeProvider
from test_provenance import event
import base64
from io import BytesIO
from PIL import Image
_image=BytesIO();Image.new("RGB",(4,4),"red").save(_image,format="PNG")
PIC="data:image/png;base64,"+base64.b64encode(_image.getvalue()).decode()
from zhaoxi.cognitive_stream import ExperienceStream,AttentionRetriever,CognitiveIngress
from zhaoxi.cognitive_stream.models import CognitiveEventType,EventPart
from zhaoxi.cognitive_stream.social_trace import SocialTraceReader
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext,set_current_turn,reset_current_turn
from zhaoxi.cognitive_stream.timeline import cognitive_timeline
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role
from zhaoxi.models.types import ModelResponse,ToolCall
from zhaoxi.perception.digest import digest,make_batch
from zhaoxi.perception.models import ObservationStatus
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.tools.builtin.social_context import ReadSocialContextTool
from zhaoxi_ext.qq_napcat.codec import decode
from zhaoxi_ext.qq_napcat.plugin import QQNapCatPlugin
import asyncio
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.perception.runtime import PerceptionRuntime
from zhaoxi.reliability import MetricRegistry


def qq_event(message_id, *, text="hi", kind="private", image=None):
    parts=[{"type":"text","data":{"text":text}}] if text else []
    if image:parts.append({"type":"image","data":{"file":image}})
    return {"post_type":"message","message_type":kind,"group_id":123,"user_id":8,
        "message_id":message_id,"sender":{"nickname":"A"},"message":parts}


def make_runtime(tmp_path, generate):
    settings=Settings(_env_file=None,perception_db_path=str(tmp_path/"perception.db"),session_db_path=str(tmp_path/"sessions.db"),perception_image_temp_dir=str(tmp_path/"images"))
    async def wrapped(messages,tools=None,**kwargs):return await generate(messages,tools)
    builder=ContextBuilder("朝汐")
    agent=ZhaoxiAgent(provider=SimpleNamespace(generate=wrapped),registry=ToolRegistry(override_path=tmp_path/"tools.json"),context_builder=builder)
    agent.metrics=MetricRegistry();agent.conversation_lock=asyncio.Lock()
    agent.session_store=SQLiteSessionStore(settings.session_db_path)
    agent.experience_stream=ExperienceStream(tmp_path/"events.db")
    agent.cognitive_ingress=CognitiveIngress(agent.experience_stream)
    agent.attention_retriever=AttentionRetriever(agent.experience_stream)
    builder.attention_retriever=agent.attention_retriever
    return PerceptionRuntime(settings,agent),agent


def raw(stream,text="原话",ref="qq:group:A:1",**kwargs):
    e=event(kind="group",conversation="A",actor="THIRD_PARTY",content=text,source_refs=[ref],**kwargs)
    return stream.append(e)


def snapshot(stream,refs,**kwargs):
    e=event(kind="group",conversation="A",actor="SELF",event_type=CognitiveEventType.SOCIAL_SNAPSHOT,
        content="[s1] 一句概括",parent_refs=refs,source_refs=["snapshot:one"],
        metadata={"conversation_kind":"group","source_plugin":"napcat","social_statements":[{"statement_id":"s1","text":"一句概括","raw_refs":refs[:1]}]},**kwargs)
    return stream.append(e)


async def test_digest_statement_evidence_and_unknown_id_fallback():
    item=decode(qq_event(1,text="周五聚餐",kind="group"),self_id="42")
    provider=FakeProvider([ModelResponse(tool_calls=[ToolCall(id="d",name="record_social_digest",arguments={"summary":"不支持的独立概括","confidence":.8,"statements":[{"text":"群友提到周五聚餐","evidence_observation_ids":[item.observation_id]}]})])])
    result=await digest(make_batch([item]),[item],provider)
    assert result.summary=="[s1] 群友提到周五聚餐" and result.statements[0].evidence_observation_ids==[item.observation_id]
    bad=FakeProvider([ModelResponse(tool_calls=[ToolCall(id="bad",name="record_social_digest",arguments={"summary":"编造","confidence":1,"statements":[{"text":"编造","evidence_observation_ids":["invented"]}]})])])
    fallback=await digest(make_batch([item]),[item],bad)
    assert "周五聚餐" in fallback.summary and "编造" not in fallback.summary and fallback.confidence==.2


def test_recursive_snapshot_unit_statement_and_missing(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream);b=raw(stream,"第二句","qq:group:A:2")
    summary=snapshot(stream,[a.source_refs[0],b.source_refs[0]])
    rows=cognitive_timeline(stream);message=next(m for m in rows if m.message_id==summary.event_id)
    reader=SocialTraceReader(stream)
    result=reader.read(message.metadata["timeline_unit_id"],statement_id="s1")
    assert [r["content"] for r in result["records"]]==[a.content] and result["granularity"]=="statement"
    resolved=stream.resolve_timeline_unit(message.metadata["timeline_unit_id"])
    assert len(resolved["social_trace"]["records"])==2
    assert reader.read(summary.event_id,statement_id="unknown")["status"]=="statement_not_found"
    with stream._connect() as db:db.execute("DELETE FROM events WHERE event_id=?",(a.event_id,))
    result=reader.read(summary.event_id)
    assert result["status"]=="partial" and a.source_refs[0] in result["missing_refs"]


def test_group_boundary_and_non_social_denied(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream)
    reader=SocialTraceReader(stream)
    turn=CognitiveTurnContext(trigger_event=event(kind="group",conversation="B"),output_channel="qq",audience="public")
    assert reader.read(a.event_id,turn=turn)["status"]=="forbidden"
    other=stream.append(event())
    assert reader.read(other.event_id)["status"]=="forbidden"
    turn=CognitiveTurnContext(trigger_event=event(kind="group",conversation="A"),output_channel="qq",audience="public")
    assert reader.read(a.event_id,turn=turn)["status"]=="complete"
    turn.trigger_event.metadata["source_plugin"]="different"
    assert reader.read(a.event_id,turn=turn)["status"]=="forbidden"


def test_long_raw_text_pagination_does_not_lose_tail(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream,"头"*250+"尾")
    reader=SocialTraceReader(stream)
    first=reader.read(a.event_id,max_chars=200)
    assert first["next_offset"]==0 and first["next_text_offset"]==200
    second=reader.read(a.event_id,text_offset=200,max_chars=200)
    assert first["records"][0]["content"]+second["records"][0]["content"]==a.content
    assert second["status"]=="complete" and second["next_offset"] is None


def test_merged_direct_keeps_individual_time_text_and_ids(tmp_path):
    first=decode(qq_event(1,text="第一条",kind="group"),self_id="42",owner_id="8")
    second=decode(qq_event(2,text="第二条",kind="group"),self_id="42",owner_id="8")
    second.occurred_at=first.occurred_at+timedelta(seconds=2)
    merged=QQNapCatPlugin._merge_direct([first,second])
    stream=ExperienceStream(tmp_path/"events.db");e=CognitiveIngress(stream).observation(merged,session_id="qq/group/123")
    reader=SocialTraceReader(stream);result=reader.read(e.event_id)
    assert [r["content"] for r in result["records"]]==["第一条","第二条"]
    assert result["records"][1]["provenance"]["origin_occurred_at"]==second.occurred_at.isoformat().replace("+00:00","Z")
    assert reader.read(first.raw_ref)["records"][0]["raw_ref"]==first.raw_ref
    assert all(r["raw_payload_available"] and r["original_kind"]=="message" for r in result["records"])
    legacy=raw(stream,"老合并",ref="qq:group:A:legacy",metadata={"conversation_kind":"group","source_plugin":"napcat"})
    legacy=legacy.model_copy(update={"source_refs":["legacy1","legacy2"]})
    assert SocialTraceReader.originals(legacy)[0]["original_kind"]=="merged_legacy"


def test_live_summary_protects_evidence_then_expiry_releases_it(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");now=datetime.now(UTC)
    a=raw(stream,received_at=now-timedelta(days=31))
    summary=snapshot(stream,a.source_refs,received_at=now-timedelta(days=29))
    assert stream.clear_expired(now)==0 and stream.get(a.event_id)
    assert stream.clear_expired(now+timedelta(days=3))==2
    assert stream.get(summary.event_id) is None and stream.get(a.event_id) is None


async def test_perception_cleanup_protects_live_snapshot(tmp_path):
    store=PerceptionStore(tmp_path/"perception.db");item=decode(qq_event(1,kind="group"),self_id="42")
    item.occurred_at=item.received_at=datetime.now(UTC)-timedelta(days=8)
    store.insert(item,ObservationStatus.BUFFERED);batch=make_batch([item]);snap=await digest(batch,[item]);store.commit_batch(batch,snap)
    assert store.clear_expired(168,protected_refs=[item.raw_ref,"snapshot:"+snap.snapshot_id])==0
    assert len(store.recent_all_snapshots())==1
    assert store.clear_expired(168)==1 and not store.recent_all_snapshots()


def test_fast_and_router_keep_external_summary(tmp_path):
    from zhaoxi.core.fast_chat import FastChatRuntime
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream);s=snapshot(stream,a.source_refs)
    trigger=CognitiveIngress(stream).desktop("群里怎么说的？")
    builder=ContextBuilder("朝汐");builder.attention_retriever=AttentionRetriever(stream)
    agent=SimpleNamespace(context_builder=builder,experience_stream=stream,attention_retriever=builder.attention_retriever,conversation=Conversation())
    token=set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages=FastChatRuntime(agent)._messages(trigger.content,output_channel="desktop",audience="owner",expression_policy="")
        assert any(m.role is Role.EXTERNAL and "SocialTrace" in m.content for m in messages)
        coordinator=SimpleNamespace(agent=agent)
        assert "一句概括" in CognitiveCoordinator._recent_routing_context(coordinator)
    finally:reset_current_turn(token)


async def test_group_agent_can_expand_evidence_and_see_cached_image(tmp_path):
    seen=[]
    async def generate(messages,tools):
        seen.append((messages,tools))
        assert {x["function"]["name"] for x in tools or []} <= {"read_social_context"}
        if not any(m.role is Role.TOOL for m in messages):
            return ModelResponse(tool_calls=[ToolCall(id="read",name="read_social_context",arguments={"reference":source.event_id,"include_images":True})])
        assert any(m.images and '"timeline_scope":"attention"' in m.content for m in messages), [(m.role.value,len(m.images),(m.content or "")[:500]) for m in messages if m.role is not Role.SYSTEM]
        return ModelResponse(content="原消息附有一张图片。")
    runtime,agent=make_runtime(tmp_path,generate)
    obs=decode(qq_event(1,text="原群消息",kind="group",image=PIC),self_id="42")
    source=agent.cognitive_ingress.observation(obs,session_id="qq/group/123")
    agent.registry.register(ReadSocialContextTool(agent.experience_stream))
    trigger=agent.cognitive_ingress.observation(decode(qq_event(2,text="展开原图",kind="group"),self_id="42"),session_id="qq/group/123")
    result=await agent.run_channel_reply(trigger.content,trigger_event=trigger,audience="public")
    assert result.content=="原消息附有一张图片。" and len(seen)==2


async def test_ambient_image_cache_and_snapshot_planner_context(tmp_path):
    from unittest.mock import AsyncMock
    seen=[]
    async def generate(messages,tools):
        seen.append(messages)
        return ModelResponse(content='{"reply":false}')
    runtime,agent=make_runtime(tmp_path,generate)
    runtime.images.resolve=AsyncMock(return_value=PIC)
    item=decode(qq_event(1,text="一张图",kind="group",image="https://expired.invalid/pic.png"),self_id="42")
    await runtime.ingest(item)
    image_parts=[p for p in agent.experience_stream.recent()[0].parts if p.type=="image"]
    assert len(image_parts)==1 and image_parts[0].url==PIC
    await runtime.flush(force=True)
    await runtime.process_pending_snapshot()
    assert any(m.role is Role.EXTERNAL and "[s1]" in m.content and "SocialTrace" in m.content for m in seen[-1])


async def test_tool_output_preserves_structured_pagination_with_small_budget(tmp_path):
    from zhaoxi.tools.builtin.social_context import ReadSocialContextInput
    stream=ExperienceStream(tmp_path/"events.db");e=raw(stream,"字"*20000)
    tool=ReadSocialContextTool(stream,max_output_chars=3000)
    result=await tool.execute(ReadSocialContextInput(reference=e.event_id,max_chars=16000))
    assert len(json.dumps(result.data,ensure_ascii=False))<=3000
    assert result.success and result.data["status"]=="partial" and result.data["next_text_offset"]>0
    assert "preview" not in result.data


def test_legacy_snapshot_does_not_claim_sentence_level_evidence(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream)
    old=event(kind="group",conversation="A",actor="SELF",event_type=CognitiveEventType.SOCIAL_SNAPSHOT,content="旧摘要",parent_refs=a.source_refs)
    stream.append(old);m=next(m for m in cognitive_timeline(stream) if m.message_id==old.event_id)
    result=SocialTraceReader(stream).read(m.metadata["timeline_unit_id"])
    assert result["granularity"]=="batch" and result["statements"]==[]
    assert SocialTraceReader(stream).read(m.metadata["timeline_unit_id"],statement_id="s1")["status"]=="statement_not_found"


def test_original_wire_text_is_not_limited_by_normalized_codec_cap(tmp_path):
    text="原"*20001
    obs=decode(qq_event(1,text=text,kind="group"),self_id="42")
    assert len(obs.content)==20000
    stream=ExperienceStream(tmp_path/"events.db");e=CognitiveIngress(stream).observation(obs,session_id="qq/group/123")
    reader=SocialTraceReader(stream)
    result=reader.read(e.event_id,text_offset=20000)
    assert result["records"][0]["content"]=="原" and result["records"][0]["text_length"]==20001


async def test_group_reply_cannot_execute_other_tool(tmp_path):
    from zhaoxi.errors import AgentLoopError
    from zhaoxi.tools.builtin.calculator import CalculatorTool
    async def generate(messages,tools):
        return ModelResponse(tool_calls=[ToolCall(id="escape",name="calculator",arguments={"expression":"1+1"})])
    runtime,agent=make_runtime(tmp_path,generate);agent.registry.register(CalculatorTool())
    trigger=agent.cognitive_ingress.observation(decode(qq_event(2,kind="group"),self_id="42"),session_id="qq/group/123")
    with pytest.raises(AgentLoopError,match="受限回复不能调用工具"):
        await agent.run_channel_reply(trigger.content,trigger_event=trigger,audience="public")


def test_turn_unit_expands_incoming_evidence_without_returning_tool_transcript(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream)
    tool=stream.append(event(event_type=CognitiveEventType.TOOL_OBSERVATION,kind="group",conversation="A",actor="SELF",privacy_level="PRIVATE",content="私有工具结果"))
    stream.save_timeline_unit("turn:test",json.dumps({"source_event_ids":[a.event_id,tool.event_id]}))
    result=SocialTraceReader(stream).read("turn:test")
    assert result["status"]=="complete" and [r["content"] for r in result["records"]]==[a.content]
    assert SocialTraceReader(stream).read(tool.event_id)["status"]=="forbidden"


def test_live_timeline_unit_pins_expired_summary_and_raw_until_cache_expiry(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db");now=datetime.now(UTC)
    a=raw(stream,received_at=now-timedelta(days=40))
    summary=snapshot(stream,a.source_refs,received_at=now-timedelta(days=35))
    stream.save_timeline_unit("cached-unit",json.dumps({"source_event_ids":[summary.event_id]}))
    assert stream.clear_expired(now)==0
    assert SocialTraceReader(stream).read("cached-unit")["records"][0]["content"]==a.content
    with stream._connect() as db:
        db.execute("UPDATE timeline_units SET updated_at=?",((now-timedelta(days=31)).isoformat(),))
    assert stream.clear_expired(now)==2 and stream.load_timeline_unit("cached-unit") is None


def test_missing_cached_image_is_reported_without_fetching_remote_url(tmp_path):
    from zhaoxi.core.image_thumbnails import ImageThumbnailCache
    stream=ExperienceStream(tmp_path/"events.db")
    a=raw(stream,parts=[EventPart(type="image",url="https://expired.invalid/pic.png")])
    reader=SocialTraceReader(stream);result=reader.read(a.event_id)
    assert result["records"][0]["image_status"]=="unavailable"
    assert reader.image_messages(result,ImageThumbnailCache(tmp_path/"thumbs"))==[]


def test_missing_media_blob_keeps_original_text_available(tmp_path,monkeypatch):
    stream=ExperienceStream(tmp_path/"events.db");a=raw(stream,"缓存丢失也保留原文",parts=[EventPart(type="image",url=PIC)])
    def missing(_):raise FileNotFoundError("missing cached blob")
    monkeypatch.setattr(stream.media,"decode",missing)
    reader=SocialTraceReader(stream);result=reader.read(a.event_id)
    assert result["status"]=="complete" and result["records"][0]["content"]==a.content
    assert result["records"][0]["image_status"]=="unavailable"
    from zhaoxi.core.image_thumbnails import ImageThumbnailCache
    assert reader.image_messages(result,ImageThumbnailCache())==[]


def test_unknown_external_conversation_does_not_grant_read_access(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db")
    a=raw(stream,session_id=None,conversation_id=None)
    turn=CognitiveTurnContext(trigger_event=event(kind="group",session_id=None,conversation_id=None),output_channel="qq",audience="public")
    assert SocialTraceReader(stream).read(a.event_id,turn=turn)["status"]=="forbidden"


async def test_disabled_social_read_is_not_exposed_or_executed(tmp_path):
    from zhaoxi.errors import AgentLoopError
    async def generate(messages,tools):
        assert not tools
        return ModelResponse(tool_calls=[ToolCall(id="disabled",name="read_social_context",arguments={"reference":"anything"})])
    runtime,agent=make_runtime(tmp_path,generate)
    agent.registry.register(ReadSocialContextTool(agent.experience_stream))
    agent.registry.update_tools(name="read_social_context",enabled=False)
    trigger=agent.cognitive_ingress.observation(decode(qq_event(2,kind="group"),self_id="42"),session_id="qq/group/123")
    with pytest.raises(AgentLoopError,match="受限回复不能调用工具"):
        await agent.run_channel_reply(trigger.content,trigger_event=trigger,audience="public")


@pytest.mark.parametrize("channel,actor,audience,allowed", [
    ("web", "OWNER", "owner", True),
    ("cli", "OWNER", "owner", True),
    ("voice", "OWNER", "owner", True),
    ("web", "THIRD_PARTY", "owner", False),
    ("web", "OWNER", "public", False),
    ("qq", "OWNER", "owner", False),
])
async def test_local_owner_social_tool_access(tmp_path, channel, actor, audience, allowed):
    from zhaoxi.tools.builtin.social_context import ReadSocialContextInput

    stream=ExperienceStream(tmp_path/"events.db")
    source=raw(stream, "群友的原话")
    summary=snapshot(stream, source.source_refs)
    trigger=CognitiveIngress(stream).desktop("回查群聊", channel=channel)
    trigger=trigger.model_copy(update={"actor_role":actor})
    token=set_current_turn(CognitiveTurnContext(
        trigger_event=trigger, output_channel=channel, audience=audience))
    try:
        tool=ReadSocialContextTool(stream)
        result=await tool.execute(ReadSocialContextInput(reference=summary.event_id))
        assert result.success is allowed
        if allowed:
            assert result.data["records"][0]["content"]==source.content
            private=stream.append(event(privacy_level="OWNER_PRIVATE"))
            assert not (await tool.execute(ReadSocialContextInput(reference=private.event_id))).success
            mismatched=trigger.model_copy(update={"channel":"qq"})
            assert tool.reader.read(summary.event_id, turn=CognitiveTurnContext(
                trigger_event=mismatched, output_channel=channel, audience=audience))["status"]=="forbidden"
        else:
            assert result.error=="forbidden" and result.data["records"]==[]
    finally:
        reset_current_turn(token)


@pytest.mark.parametrize("reference", ["missing-evidence", "qq/group/A", "missing-snapshot-evidence"])
async def test_empty_social_evidence_is_not_found(tmp_path, reference):
    from zhaoxi.tools.builtin.social_context import ReadSocialContextInput

    stream=ExperienceStream(tmp_path/"events.db")
    source=raw(stream)
    if reference=="missing-snapshot-evidence":
        reference=snapshot(stream, source.source_refs).event_id
        with stream._connect() as db:
            db.execute("DELETE FROM events WHERE event_id=?", (source.event_id,))
    result=await ReadSocialContextTool(stream).execute(ReadSocialContextInput(reference=reference))
    assert not result.success and result.error=="not_found"
    assert result.data["status"]=="not_found" and result.data["records"]==[]
    assert result.data["total_records"]==0 and result.data["missing_refs"]
