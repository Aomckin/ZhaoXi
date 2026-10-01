"""External Provenance patch: Cases A-J and review safeguards."""
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from conftest import FakeProvider
from zhaoxi.cognitive_stream import AttentionRetriever, ExperienceStream
from zhaoxi.cognitive_stream.ingress import CognitiveIngress
from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType, EventPart
from zhaoxi.cognitive_stream.provenance import (Provenance, context_relation, from_event,
    is_cross_context, project_current_trigger, render_for_context, render_messages)
from zhaoxi.cognitive_stream.timeline import project_event
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.fast_chat import FastChatRuntime
from zhaoxi.core.message import Role
from zhaoxi.models.types import ModelResponse

PIC = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG9sAAAAASUVORK5CYII="

def event(channel="qq", kind="private", conversation="owner", actor="OWNER", **kwargs):
    data = dict(event_type=CognitiveEventType.EXTERNAL_MESSAGE if channel!="desktop" else CognitiveEventType.USER_MESSAGE,
        source=channel, channel=channel, session_id=f"{channel}/{kind}/{conversation}" if channel!="desktop" else "local",
        conversation_id=conversation if channel!="desktop" else None, actor_role=actor, actor_id="owner" if actor=="OWNER" else "friend",
        actor_name="暗苟" if actor=="OWNER" else "用户A", trust_level="TRUSTED" if actor=="OWNER" else "UNVERIFIED",
        privacy_level="OWNER_PRIVATE" if actor=="OWNER" and kind=="private" else "SOCIAL",
        content="晚上继续改朝汐。", metadata={"conversation_kind":kind if channel!="desktop" else None, "source_plugin":"napcat" if channel=="qq" else None})
    data.update(kwargs)
    return CognitiveEvent(**data)


def project_history(e, scope="recent"):
    m=project_event(e);m.metadata["timeline_scope"]=scope;return m


# Phase 1 gate: same channel cannot hide a different group.
def test_cross_group_keeps_conversation_scope():
    left=from_event(event(kind="group",conversation="A"));right=from_event(event(kind="group",conversation="B"))
    assert is_cross_context(left,right)
    assert "会话 A" in render_for_context(project_history(event(kind="group",conversation="A")),right).content


@pytest.mark.parametrize("field",["channel","session_id","conversation_id","conversation_kind","source_plugin"])
def test_known_boundary_includes_plugin(field):
    a=Provenance(channel="qq",session_id="same",conversation_id="A",conversation_kind="group",source_plugin="one")
    assert is_cross_context(a,replace(a,**{field:"different"}))
    assert not is_cross_context(a,a)


@pytest.mark.parametrize("missing",["conversation_id","session_id","source_plugin"])
def test_unknown_does_not_trigger_cross_context(missing):
    p=Provenance(channel="qq",session_id="same",conversation_id="A",source_plugin="one")
    current=replace(p,**{missing:None})
    assert context_relation(p,current)=="unknown" and not is_cross_context(p,current)
    m=render_for_context(project_event(event()),Provenance(channel="qq"))
    assert m.metadata["context_relation"]=="unknown" and not m.content.startswith("[来源:")


def test_same_desktop_history_has_no_source_noise():
    e=event(channel="desktop");m=render_for_context(project_history(e),from_event(e))
    assert m.role is Role.USER and m.content==e.content and m.metadata["context_relation"]=="same"


@pytest.mark.parametrize("kind",["private","group"])
def test_cross_channel_owner_message_keeps_source(kind):
    e=event(kind=kind);m=render_for_context(project_history(e),Provenance(channel="desktop",session_id="local"))
    assert m.role is Role.USER and m.content.startswith("[来源: QQ")
    assert ("私聊" if kind=="private" else "群聊") in m.content
    assert m.metadata["origin_actor_role"]=="OWNER" and m.metadata["origin_source_plugin"]=="napcat"


def test_cross_session_same_channel_keeps_source():
    e=event();other=replace(from_event(e),session_id="qq/private/other")
    assert render_for_context(project_history(e),other).metadata["cross_context"]


def test_private_to_group_keeps_source():
    e=event();m=render_for_context(project_history(e),from_event(event(kind="group")))
    assert m.metadata["cross_context"] and "私聊" in m.content


def test_external_actor_never_becomes_owner_turn():
    e=event(kind="group",actor="THIRD_PARTY",content="暗苟今天没来。")
    m=render_for_context(project_history(e),Provenance(channel="desktop"))
    assert m.role is Role.EXTERNAL and "第三方发言" in m.content and "用户A" in m.content


def test_social_snapshot_stays_external():
    e=event(kind="group",event_type=CognitiveEventType.SOCIAL_SNAPSHOT,actor_role="OWNER",content="我最近很焦虑。")
    m=render_for_context(project_history(e),Provenance(channel="desktop"))
    assert m.role is Role.EXTERNAL and "非 Owner 直接发言" in m.content


def test_historical_image_keeps_provenance():
    e=event(kind="group",parts=[EventPart(type="image",url=PIC)])
    m=render_for_context(project_history(e,"attention"),Provenance(channel="desktop"))
    assert m.images==[PIC] and '"timeline_scope":"attention"' in m.to_provider_dict()["content"][0]["text"]
    assert "历史图片" in m.content and m.metadata["origin_event_id"]==e.event_id


def test_current_trigger_image_not_mislabeled():
    e=event(parts=[EventPart(type="image",url=PIC)])
    m=render_for_context(project_current_trigger(e,[PIC]),from_event(e))
    assert m.metadata["timeline_scope"]=="current_trigger" and "历史图片" not in m.content
    assert '"timeline_scope":"current_trigger"' in m.to_provider_dict()["content"][0]["text"]


def test_truth_layer_wins_over_stale_projection(tmp_path):
    stream=ExperienceStream(tmp_path/"stream.db");e=event(conversation="old");stream.append(e);m=project_history(e)
    revised=e.model_copy(update={"conversation_id":"corrected","session_id":"qq/private/corrected"})
    with stream._connect() as db:db.execute("UPDATE events SET payload=? WHERE event_id=?",(stream.media.dumps(revised.model_dump(mode="json")),e.event_id))
    rendered=render_for_context(m,Provenance(channel="desktop"),stream)
    assert rendered.metadata["origin_conversation_id"]=="corrected" and rendered.metadata["provenance_resolution"]=="experience_stream"
    assert m.metadata["provenance_snapshot"]["origin_conversation_id"]=="old" and "来源" not in m.content
    with stream._connect() as db:db.execute("DELETE FROM events WHERE event_id=?",(e.event_id,))
    fallback=render_for_context(m,Provenance(channel="desktop"),stream)
    assert fallback.metadata["origin_conversation_id"]=="old" and fallback.metadata["provenance_resolution"]=="snapshot"


def test_contiguous_source_header_is_not_repeated():
    a=event();b=event(content="这周都在改项目。")
    rows=render_messages([project_history(a),project_history(b)],Provenance(channel="desktop"))
    assert "\n".join(m.content for m in rows).count("[来源:")==1
    assert rows[1].content==b.content and rows[1].metadata["inherited_source_label"]
    other=project_history(event(conversation="other"))
    assert "\n".join(m.content for m in render_messages([project_history(a),other],Provenance(channel="desktop"))).count("[来源:")==2


def test_shadow_debug_and_model_source_are_query_independent(tmp_path):
    stream=ExperienceStream(tmp_path/"stream.db");e=event(occurred_at=datetime.now(UTC)-timedelta(minutes=1));stream.append(e)
    trigger=event(channel="desktop",content="继续吧");stream.append(trigger)
    builder=ContextBuilder("朝汐");builder.attention_retriever=AttentionRetriever(stream)
    view=Conversation();view.add_user(trigger.content)
    token=set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:rows=builder.build(view)
    finally:reset_current_turn(token)
    assert "QQ 私聊" in rows[1].content and rows[-1].content==trigger.content
    assert builder.last_cognitive_context["legacy_shadow"][0]["text"]==e.content
    assert builder.last_cognitive_context["provenance_items"][0]["cross_context"]


def test_fast_keeps_provenance_and_current_anchor(tmp_path):
    stream=ExperienceStream(tmp_path/"stream.db");past=event();stream.append(past)
    trigger=event(channel="desktop",content="继续吧");stream.append(trigger)
    builder=ContextBuilder("朝汐");agent=SimpleNamespace(context_builder=builder,experience_stream=stream,conversation=Conversation())
    token=set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:rows=FastChatRuntime(agent)._messages(trigger.content,output_channel="desktop",audience="owner",expression_policy="")
    finally:reset_current_turn(token)
    assert "QQ 私聊" in rows[1].content and rows[-1].metadata["timeline_scope"]=="current_trigger"
    assert rows[-1].message_id==trigger.event_id


async def test_owner_external_memory_keeps_evidence_source(tmp_path):
    from zhaoxi.cognitive.memory_decision import AutoMemory
    from zhaoxi.memory import MemoryService,SQLiteMemoryRepository
    from zhaoxi.memory.models import MemoryQuery
    provider=FakeProvider([ModelResponse(content='{"candidates":[{"content":"这两天都在准备面试。","kind":"state","importance":0.6}]}')])
    service=MemoryService(SQLiteMemoryRepository(tmp_path/"memory.db"))
    auto=AutoMemory(provider,service);e=event(content="这两天都在准备面试。")
    result=await auto.process_event(e)
    assert result.applied_count==1
    record=(await service.repository.list_records(MemoryQuery()))[0]
    assert record.source_event_id==e.event_id and record.metadata["origin_channel"]=="qq"
    assert record.metadata["evidence_provenance"][0]["origin_session_id"]==e.session_id
    assert not (await auto.process_event(event(actor="THIRD_PARTY"))).applied_count


async def test_current_cognition_keeps_evidence_source(tmp_path):
    from zhaoxi.current_cognition import CurrentCognitionMaintainer,CurrentCognitionService,CurrentCognitionStore
    stream=ExperienceStream(tmp_path/"stream.db");e=event(content="这两天都在准备面试。");stream.append(e)
    stream.append(event(actor="THIRD_PARTY",content="暗苟最近很焦虑。"))
    response=json.dumps({"decision":"UPDATE","evidence_message_ids":[e.event_id],"thread_ops":[{"action":"upsert","key":"interview","title":"面试","summary":e.content}]})
    provider=FakeProvider([ModelResponse(content=response)])
    service=CurrentCognitionService(CurrentCognitionStore(tmp_path/"current.db"))
    assert await CurrentCognitionMaintainer(service,provider).maintain_events(stream)=="UPDATE"
    ref=service.state().threads[0].source_refs[0]
    assert ref.event_id==e.event_id and ref.provenance["origin_channel"]=="qq" and ref.provenance["origin_conversation_kind"]=="private"
    payload=json.loads(provider.calls[0][-1].content)
    assert len(payload["new_messages"])==1 and payload["new_messages"][0]["provenance"]["origin_source_plugin"]=="napcat"


def test_empty_scope_is_unknown():
    p=Provenance(channel="qq",conversation_id="A")
    assert context_relation(p,Provenance(channel="qq",conversation_id=""))=="unknown"


def test_truth_actor_and_historical_picture_time_win(tmp_path):
    stream=ExperienceStream(tmp_path/"truth.db")
    picture=event(event_id="picture",occurred_at=datetime(2026,10,1,1,tzinfo=UTC),parts=[EventPart(type="image",url=PIC)])
    stream.append(picture)
    follow=event(event_id="follow",occurred_at=picture.occurred_at+timedelta(seconds=20),metadata={**picture.metadata,"image_timeline_scope":"recent","image_origin_event_id":picture.event_id})
    stream.append(follow)
    m=render_for_context(project_current_trigger(follow,[PIC]),from_event(follow),stream)
    image=json.loads(m.content.split("[ImageProvenance ",1)[1].split("]",1)[0])
    assert image["origin_event_id"]==picture.event_id and image["occurred_at"]==picture.occurred_at.isoformat()
    stale=project_history(follow)
    revised=follow.model_copy(update={"actor_role":"THIRD_PARTY"})
    with stream._connect() as db:db.execute("UPDATE events SET payload=? WHERE event_id=?",(stream.media.dumps(revised.model_dump(mode="json")),follow.event_id))
    assert render_for_context(stale,Provenance(channel="desktop"),stream).role is Role.EXTERNAL


def test_grouped_golden_prompt():
    first=event(event_id="first",occurred_at=datetime(2026,10,1,1,tzinfo=UTC),kind="group",conversation="A",content="第一条")
    second=event(event_id="second",occurred_at=first.occurred_at+timedelta(seconds=1),kind="group",conversation="A",content="第二条")
    expected="[来源: QQ 群聊 · 会话 A · session qq/group/A · 暗苟 · Owner 本人 · plugin napcat · 2026-10-01T01:00:00+00:00 · 历史上下文]\n第一条\n第二条"
    rows=render_messages([project_history(first),project_history(second)],Provenance(channel="desktop"))
    assert "\n".join(m.to_provider_dict()["content"] for m in rows)==expected


def test_internal_image_and_source_labels_do_not_leak_to_reply():
    from zhaoxi.core.message import strip_echoed_timeline_header
    draft='[来源: QQ] [历史图片]\n[ImageProvenance {"timeline_scope":"recent"}]\n[发言者: A · user]\n那张图来自群聊。'
    assert strip_echoed_timeline_header(draft)=="那张图来自群聊。"


async def test_gateway_maintenance_retains_source_and_separates_plugins(tmp_path):
    from zhaoxi.interfaces.gateway import InterfaceGateway
    stream=ExperienceStream(tmp_path/"events.db")
    first=event(event_id="one",content="第一条");second=event(event_id="two",metadata={"conversation_kind":"private","source_plugin":"other"},content="第二条")
    stream.append(first);stream.append(second)
    seen=[]
    agent=SimpleNamespace(experience_stream=stream,conversation=Conversation(),
        current_cognition_maintainer=SimpleNamespace(service=SimpleNamespace(state=lambda:SimpleNamespace(last_processed_message_id=None))))
    gateway=InterfaceGateway(agent)
    gateway.maintenance_queue=lambda:SimpleNamespace(enqueue=lambda *args,**kwargs:seen.append((args,kwargs)))
    gateway.enqueue_external_maintenance(first,"");gateway.enqueue_external_maintenance(second,"")
    assert seen[0][1]["batch_key"]!=seen[1][1]["batch_key"]
    refs=seen[0][0][1]["messages"]
    assert refs[0]["metadata"]["origin_event_id"]==first.event_id and refs[0]["metadata"]["origin_source_plugin"]=="napcat"
    gateway._enqueue_maintenance("desktop-turn",SimpleNamespace(content="",permission_confirmation=None),SimpleNamespace(response_status="succeeded",record_interval=lambda *args:None))
    assert seen[-1][0][1]["messages"][0]["metadata"]["origin_channel"]=="qq"


async def test_cognition_source_rendering_is_deterministic(tmp_path):
    from zhaoxi.current_cognition import CurrentCognitionMaintainer,CurrentCognitionService,CurrentCognitionStore
    stream=ExperienceStream(tmp_path/"events.db");e=event(content="这两天都在准备面试。");stream.append(e)
    response=json.dumps({"decision":"UPDATE","evidence_message_ids":[e.event_id],"overview":{"action":"replace","value":e.content},"thread_ops":[{"action":"upsert","key":"interview","title":"面试","summary":e.content}]})
    service=CurrentCognitionService(CurrentCognitionStore(tmp_path/"current.db"))
    await CurrentCognitionMaintainer(service,FakeProvider([ModelResponse(content=response)])).maintain_events(stream)
    assert "QQ 私聊" in service.render_for_fast_chat() and service.state().overview_source_refs[0].provenance["origin_event_id"]==e.event_id
    token=set_current_turn(CognitiveTurnContext(trigger_event=e))
    try:assert "[来源:" not in service.render_for_fast_chat()
    finally:reset_current_turn(token)


@pytest.mark.parametrize("case",list("ABCDEFGHIJ"))
def test_cases_a_to_j_shadow_diff_golden(case):
    from pathlib import Path
    from zhaoxi.cognitive_stream.provenance import shadow_legacy
    data=json.loads((Path(__file__).parents[1]/"fixtures/provenance_cases_v143.json").read_text(encoding="utf-8"))
    row=next(item for item in data["cases"] if item["case"]==case)
    e=CognitiveEvent.model_validate(row["event"]);m=project_history(e,row["scope"])
    rendered=render_for_context(m,Provenance(**row["current"]))
    assert rendered.role.value==row["expected_role"] and rendered.metadata["cross_context"]==row["expected_cross"]
    assert (m.content or "") in rendered.content
    assert rendered.content==row["rendered"] and shadow_legacy([m],"继续吧")[0]["text"]==row["legacy"]
    if case in {"G","H"}:assert '"timeline_scope":"'+row["scope"]+'"' in rendered.content
