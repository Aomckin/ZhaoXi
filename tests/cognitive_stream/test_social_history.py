"""Legacy evidence lookup and full saved-history search with scoped permissions."""
from datetime import UTC, datetime, timedelta
import json

import pytest
from pydantic import ValidationError
from zhaoxi.cognitive_stream import ExperienceStream, CognitiveIngress
from zhaoxi.cognitive_stream.social_trace import SocialTraceReader
from zhaoxi.cognitive_stream.social_history import SocialHistory
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
from zhaoxi.perception.models import Observation, ObservationStatus, SocialSnapshot, SocialStatement
from zhaoxi.perception.digest import make_batch
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.tools.builtin.social_context import ReadSocialContextInput, ReadSocialContextTool

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)


@pytest.fixture
def history(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    store = PerceptionStore(tmp_path / "perception.db", media_directory=stream.media.root)
    return stream, store, SocialTraceReader(stream, store.path)


def observation(n, text="聚餐", *, group="A", plugin="napcat", kind="group", when=NOW, **kwargs):
    return Observation(source="qq", source_plugin=plugin, source_kind=kind+"_message",
        actor_id="8", actor_name="群友", actor_role="EXTERNAL", conversation_id=group,
        conversation_kind=kind, content=text, raw_ref=f"qq:{kind}:{group}:{n}",
        occurred_at=when, received_at=when, **kwargs)


def save(history, item, *, experience=False, status=ObservationStatus.PROCESSED):
    stream, store, _ = history
    store.insert(item, status)
    if experience:
        return CognitiveIngress(stream).observation(item, session_id=f"qq/{item.conversation_kind}/{item.conversation_id}")


def turn_for(history, *, group="A", plugin="napcat", kind="group"):
    event = SocialHistory.observation_event(observation(9000, group=group, plugin=plugin, kind=kind).model_dump(mode="json"))
    return CognitiveTurnContext(trigger_event=event, output_channel="qq", audience="public")


def test_legacy_lookup_keeps_databases_unchanged(history):
    stream, store, reader = history
    item = observation(1, "只在旧库的原话", plugin=None)
    save(history, item)
    before = (stream.stats(), store.counts())
    result = reader.read(item.raw_ref)
    assert result["status"] == "complete"
    row = result["records"][0]
    assert row["content"] == item.content and row["raw_payload_available"] is False
    assert row["evidence_store"] == "perception"
    assert row["provenance"]["origin_source_plugin"] is None
    assert reader.read(row["event_id"])["records"][0]["content"] == item.content
    assert (stream.stats(), store.counts()) == before


def test_legacy_snapshot_expands_batch_without_inventing_statements(history):
    _, store, reader = history
    items = [observation(i, f"原话{i}", plugin=None) for i in (1,2)]
    for item in items: save(history, item, status=ObservationStatus.BUFFERED)
    batch = make_batch(items)
    snap = SocialSnapshot(batch_id=batch.batch_id, source="qq", conversation_id="A",
        window_start=NOW, window_end=NOW, message_count=2, summary="历史概括", confidence=.5,
        observation_ids=batch.observation_ids, raw_refs=batch.raw_refs)
    store.commit_batch(batch, snap)
    ref = "snapshot:" + snap.snapshot_id
    result = reader.read(ref)
    assert result["status"] == "complete" and result["granularity"] == "batch"
    assert [r["content"] for r in result["records"]] == ["原话1", "原话2"]
    assert reader.read(ref, statement_id="s1")["status"] == "statement_not_found"
    with store._connect() as db: db.execute("DELETE FROM observations WHERE id=?", (items[0].observation_id,))
    result = reader.read(ref)
    assert result["status"] == "partial" and items[0].raw_ref in result["missing_refs"]


def test_legacy_snapshot_reuses_only_real_statement_citations(history):
    _, store, reader = history
    item = observation(1)
    save(history, item, status=ObservationStatus.BUFFERED)
    batch = make_batch([item])
    snap = SocialSnapshot(batch_id=batch.batch_id, source="qq", conversation_id="A",
        window_start=NOW, window_end=NOW, message_count=1, summary="[s1] 聚餐", confidence=.5,
        statements=[SocialStatement(text="聚餐", evidence_observation_ids=[item.observation_id])],
        observation_ids=batch.observation_ids, raw_refs=batch.raw_refs)
    store.commit_batch(batch, snap)
    result = reader.read("snapshot:"+snap.snapshot_id, statement_id="s1")
    assert result["granularity"] == "statement" and result["records"][0]["raw_ref"] == item.raw_ref


def test_search_covers_old_history_deduplicates_and_filters_before_pagination(history):
    _, _, reader = history
    old = observation(1, "早期聚餐", when=NOW-timedelta(days=5))
    save(history, old)
    duplicate = observation(2, "最新聚餐")
    save(history, duplicate, experience=True)
    for i in range(205): save(history, observation(i+10, "聚餐", group="B"), experience=True)
    result = reader.search(query="聚餐", group_id="A", limit=1)
    assert result["total_records"] == 2 and result["next_offset"] == 1
    assert result["records"][0]["raw_ref"] == duplicate.raw_ref
    result = reader.search(query="聚餐", group_id="A", offset=1, limit=1)
    assert result["status"] == "complete" and result["records"][0]["raw_ref"] == old.raw_ref
    assert result["records"][0]["evidence_store"] == "perception"


def test_search_only_matches_original_text_and_literal_keywords(history):
    _, _, reader = history
    save(history, observation(1, "正文", metadata={"debug": "秘密关键词"}))
    save(history, observation(2, "100%_O'Reilly"))
    assert reader.search(query="秘密关键词")["status"] == "not_found"
    assert reader.search(query="100%_O'Reilly")["total_records"] == 1
    assert reader.search(query="%' OR 1=1 --")["status"] == "not_found"


def test_raw_protocol_tail_is_searchable_and_long_text_can_be_resumed(history):
    _, _, reader = history
    full = "前"*21000+"尾部证据"
    item = observation(1, full[:20000], metadata={"raw_message":{"message":[{"type":"text","data":{"text":full}}]}})
    save(history, item)
    result = reader.search(query="尾部证据", max_chars=200)
    row = result["records"][0]
    assert row["raw_payload_available"] and row["match_text_offset"] == 21000
    result = reader.search(query="尾部证据", text_offset=row["match_text_offset"], max_chars=200)
    assert result["records"][0]["content"] == "尾部证据"
    assert result["next_offset"] is None


def test_search_time_bounds_respect_timezones(history):
    _, _, reader = history
    for i in range(3): save(history, observation(i+1, when=NOW+timedelta(hours=i)))
    args = ReadSocialContextInput(group_id="A", since="2026-10-02T21:00:00+08:00", until="2026-10-02T22:00:00+08:00")
    result = reader.search(group_id=args.group_id, since=args.since, until=args.until)
    assert result["total_records"] == 1 and result["records"][0]["raw_ref"].endswith(":2")


@pytest.mark.parametrize("kwargs", [dict(group="B"), dict(plugin="other"), dict(kind="private")])
def test_external_search_scope_cannot_be_widened(history, kwargs):
    reader = history[2]
    save(history, observation(1), experience=True)
    save(history, observation(2, **kwargs))
    turn = turn_for(history)
    result = reader.search(query="聚餐", turn=turn)
    assert result["total_records"] == 1 and result["records"][0]["raw_ref"] == "qq:group:A:1"
    assert reader.read(observation(2, **kwargs).raw_ref, turn=turn)["status"] == "forbidden"
    assert reader.search(group_id="B", turn=turn)["status"] == "forbidden"
    assert reader.search(source_plugin="other", turn=turn)["status"] == "forbidden"


def test_unknown_legacy_plugin_is_local_only_and_private_ignored_are_excluded(history):
    reader = history[2]
    save(history, observation(1, plugin=None))
    save(history, observation(2, kind="private"))
    save(history, observation(3), status=ObservationStatus.IGNORED)
    assert reader.search(group_id="A")["total_records"] == 1
    assert reader.read("qq:private:A:2")["status"] == "forbidden"
    assert reader.read("qq:group:A:3")["status"] == "not_found"
    assert reader.search(group_id="A", turn=turn_for(history))["status"] == "not_found"
    assert reader.search(group_id="A", turn=turn_for(history, plugin=None))["status"] == "forbidden"


def test_merged_originals_are_separately_searchable(history):
    stream, _, reader = history
    items = [observation(1,"第一句"), observation(2,"第二句")]
    merged = items[1].model_copy(update={"content":"第一句\n第二句", "metadata":{
        "merged_refs":[i.raw_ref for i in items], "raw_observations":[i.model_dump(mode="json") for i in items]}})
    save(history, merged, experience=True)
    result = reader.search(query="第二句")
    assert result["total_records"] == 1
    assert result["records"][0]["raw_ref"] == items[1].raw_ref
    assert result["records"][0]["content"] == "第二句"
    assert reader.search(group_id="A")["total_records"] == 2


@pytest.mark.parametrize("arguments", [{}, {"query":" "}, {"group_id":"A","reference":"x"},
    {"query":"x","statement_id":"s1"}, {"group_id":"A","since":"2026-10-02T00:00:00"},
    {"group_id":"A","since":"2026-10-03T00:00:00Z","until":"2026-10-02T00:00:00Z"}])
def test_invalid_search_inputs_are_rejected(arguments):
    with pytest.raises(ValidationError): ReadSocialContextInput(**arguments)


async def test_tool_budget_keeps_search_pagination_and_scope(history):
    stream, store, reader = history
    for i in range(6): save(history, observation(i+1, "长正文"*200, when=NOW+timedelta(seconds=i)))
    tool = ReadSocialContextTool(stream, perception_path=store.path, max_output_chars=3000)
    token = set_current_turn(turn_for(history))
    try:
        collected=[];offset=text_offset=0
        for _ in range(20):
            result = await tool.execute(ReadSocialContextInput(query="长正文", offset=offset, text_offset=text_offset))
            assert result.success and len(json.dumps(result.data,ensure_ascii=False))<=3000
            assert result.data["group_id"] == "A"
            collected.extend(r["raw_ref"] for r in result.data["records"])
            if result.data["next_offset"] is None:break
            offset,text_offset=result.data["next_offset"],result.data["next_text_offset"]
        else:pytest.fail("pagination did not finish")
        assert len(collected)==6 and len(set(collected))==6
    finally: reset_current_turn(token)


def test_no_perception_file_is_created_on_read(history, tmp_path):
    reader = SocialTraceReader(history[0],tmp_path/"absent.db")
    assert reader.read("qq:group:A:1")["status"]=="not_found"
    assert reader.search(group_id="A")["status"]=="not_found"
    assert not (tmp_path/"absent.db").exists()

def test_legacy_images_reach_model_and_missing_blob_keeps_text(history):
    from io import BytesIO
    import base64
    from PIL import Image
    from zhaoxi.core.image_thumbnails import ImageThumbnailCache
    from zhaoxi.perception.models import ObservationPart
    _, store, reader = history
    data=BytesIO();Image.new("RGB",(4,4),"red").save(data,format="PNG")
    image="data:image/png;base64,"+base64.b64encode(data.getvalue()).decode()
    item=observation(1,"图片原话",parts=[ObservationPart(type="image",url=image)])
    save(history,item)
    result=reader.search(query="图片原话")
    assert result["records"][0]["image_status"]=="cached"
    messages=reader.image_messages(result,ImageThumbnailCache())
    assert len(messages)==1 and messages[0].images[0].startswith("data:image/jpeg;")
    for path in store.media.root.glob("sha256/*/*"):path.unlink()
    result=reader.read(item.raw_ref)
    assert result["records"][0]["content"]=="图片原话"
    assert result["records"][0]["image_status"]=="unavailable"
    assert reader.image_messages(result,ImageThumbnailCache())==[]


def test_saved_snapshot_with_cross_group_sources_is_rejected(history):
    _, store, reader=history
    a,b=observation(1),observation(2,group="B")
    for item in (a,b):save(history,item)
    snap=SocialSnapshot(batch_id="forged",source="qq",conversation_id="A",window_start=NOW,
        window_end=NOW,message_count=2,summary="错误混群",confidence=.5,
        observation_ids=[a.observation_id,b.observation_id],raw_refs=[a.raw_ref,b.raw_ref])
    with store._connect() as db:
        db.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)",(snap.snapshot_id,"qq","A",NOW.isoformat(),snap.model_dump_json()))
    assert reader.read("snapshot:"+snap.snapshot_id)["status"]=="not_found"


def test_search_never_returns_private_experience_or_other_event_types(history):
    from zhaoxi.cognitive_stream.models import CognitiveEventType
    stream,_,reader=history
    event=save(history,observation(1,"公开原文"),experience=True)
    stream.append(event.model_copy(update={"event_id":"private","source_refs":["qq:group:A:p"],"privacy_level":"OWNER_PRIVATE","content":"隐私关键词"}))
    stream.append(event.model_copy(update={"event_id":"tool","source_refs":[],"event_type":CognitiveEventType.TOOL_OBSERVATION,"content":"工具关键词"}))
    stream.append(event.model_copy(update={"event_id":"summary","source_refs":[],"event_type":CognitiveEventType.SOCIAL_SNAPSHOT,"content":"摘要关键词"}))
    for query in ("隐私关键词","工具关键词","摘要关键词"):
        assert reader.search(query=query)["status"]=="not_found"

def test_private_experience_classification_cannot_be_bypassed_via_legacy_copy(history):
    stream,_,reader=history
    event=save(history,observation(1,"受保护内容"),experience=True)
    private=event.model_copy(update={"privacy_level":"OWNER_PRIVATE"})
    with stream._connect() as db:
        db.execute("UPDATE events SET payload=? WHERE event_id=?",(private.model_dump_json(),event.event_id))
    assert reader.read(event.source_refs[0])["status"]=="forbidden"
    with history[1]._connect() as db:
        observation_id=db.execute("SELECT id FROM observations WHERE raw_ref=?",(event.source_refs[0],)).fetchone()[0]
    assert reader.read("observation:"+observation_id)["status"]=="forbidden"
    assert reader.search(query="受保护内容")["status"]=="not_found"


def test_ledger_only_perception_file_does_not_break_history_lookup(history,tmp_path):
    import sqlite3
    file=tmp_path/"ledger-only.db"
    with sqlite3.connect(file) as db:db.execute("CREATE TABLE ledger(id TEXT)")
    reader=SocialTraceReader(history[0],file)
    assert reader.read("qq:group:A:1")["status"]=="not_found"
    assert reader.read("snapshot:absent")["status"]=="not_found"
    assert reader.search(group_id="A")["status"]=="not_found"

async def test_group_model_can_search_legacy_messages_and_see_history_images(tmp_path):
    from test_social_trace import make_runtime, qq_event, PIC
    from zhaoxi_ext.qq_napcat.codec import decode
    from zhaoxi.core.message import Role
    from zhaoxi.models.types import ModelResponse, ToolCall
    calls=[]
    async def generate(messages, tools):
        calls.append(messages)
        assert {t["function"]["name"] for t in tools or []}<={"read_social_context"}
        if not any(m.role is Role.TOOL for m in messages):
            return ModelResponse(tool_calls=[ToolCall(id="search",name="read_social_context",
                arguments={"query":"旧图线索","include_images":True})])
        assert any(m.role is Role.TOOL and "旧图线索" in (m.content or "") for m in messages)
        assert any(m.images and '"timeline_scope":"attention"' in (m.content or "") for m in messages)
        return ModelResponse(content="找到了保存的旧群消息和图片。")
    runtime,agent=make_runtime(tmp_path,generate)
    runtime.store.media=agent.experience_stream.media
    old=decode(qq_event(1,text="旧图线索",kind="group",image=PIC),self_id="42")
    runtime.store.insert(old,ObservationStatus.PROCESSED)
    agent.registry.register(ReadSocialContextTool(agent.experience_stream,perception_path=runtime.store.path))
    trigger=agent.cognitive_ingress.observation(decode(qq_event(2,text="搜索之前群里的图片",kind="group"),self_id="42"),session_id="qq/group/123")
    result=await agent.run_channel_reply(trigger.content,trigger_event=trigger,audience="public")
    assert result.content=="找到了保存的旧群消息和图片。" and len(calls)==2
