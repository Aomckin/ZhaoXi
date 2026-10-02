"""Presence 2.0 acceptance uses temporary stores and a fake provider only."""
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
import pytest
from zhaoxi.config.settings import Settings
from zhaoxi.cognitive_stream import ExperienceStream, CognitiveEvent, CognitiveEventType
from zhaoxi.current_cognition.store import CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionService
from zhaoxi.current_cognition.maintainer import CurrentCognitionMaintainer
from zhaoxi.current_cognition.models import CognitionThread, EvidenceRef, JournalItem
from zhaoxi.internal_activity.runtime import InternalActivityRuntime
from zhaoxi.internal_activity.models import ActivitySpec, ActivityResult, ActivityCategory as Category, CostClass as Cost, PresenceState as Presence
from zhaoxi.internal_activity.budget import TickBudget
from zhaoxi.internal_activity.activities.cognitive import FAST_DIGEST, REMINISCENCE
from zhaoxi.internal_activity.activities.social import privacy_gate, public_context
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.models import MemoryCreate, MemoryQuery, MemoryStatus, MemoryCluster, MemoryEmbedding
from zhaoxi.models.types import ModelResponse
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.perception.models import Observation, ObservationStatus
from zhaoxi.proactive.interaction import Interaction, InteractionState
from zhaoxi.sdk.external_source import SendResult
from zhaoxi.reliability.retry import consume_provider_budget

class Provider:
    def __init__(self, value=None):
        self.value = value or {"decision": "NO_CHANGE"}
        self.calls = []

    async def generate(self, messages, tools=None, **kwargs):
        consume_provider_budget()
        self.calls.append(messages)
        return ModelResponse(content=json.dumps(self.value, ensure_ascii=False))

def runtime(tmp_path, **kwargs):
    settings = Settings(_env_file=None, presence_v2_enabled=True,
        current_cognition_consolidation_enabled=False, memory_maintenance_enabled=False,
        agenda_maintenance_enabled=False, proactive_activity_enabled=False,
        external_cognition_ambient_enabled=False, **kwargs)
    provider = Provider()
    cognition = CurrentCognitionService(CurrentCognitionStore(tmp_path / "cognition.db"))
    agent = SimpleNamespace(current_cognition=cognition, provider=provider,
        experience_stream=ExperienceStream(tmp_path / "experience.db"),
        current_cognition_maintainer=CurrentCognitionMaintainer(cognition, provider))
    return InternalActivityRuntime(agent, settings, tmp_path / "activity.db")

def fast(r, text, **kwargs):
    return r.agent.experience_stream.append(CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,
        source="desktop", actor_role=kwargs.get("actor_role", "OWNER"), trust_level="TRUSTED", content=text,
        metadata={"dialogue_lane": "fast_chat"}))

def social(r):
    r.agent.perception = SimpleNamespace(store=PerceptionStore(r.path.parent / "perception.db"), sources=None)
    observation = Observation(source="qq", source_plugin="qq_napcat", source_kind="chat",
        conversation_kind="group", conversation_id="123456", content="喜欢日语歌，最近在练唱歌",
        actor_name="群友", raw_ref="qq:test")
    r.agent.perception.store.insert(observation, ObservationStatus.BUFFERED)
    return observation

async def memory(r):
    r.agent.memory_service = MemoryService(SQLiteMemoryRepository(r.path.parent / "memory.db"))
    return r.agent.memory_service

async def old_memory(service, **kwargs):
    record = (await service.remember(MemoryCreate(content=kwargs.pop("content", "很久前练唱一首日语歌"),
        kind="episodic", importance=.8, activation=.2, tags=["日语歌"]))).record
    record.created_at = record.updated_at = datetime.now(UTC) - timedelta(days=60)
    record.status = kwargs.pop("status", MemoryStatus.COLD)
    for key, value in kwargs.items():
        setattr(record, key, value)
    await service.repository.save(record)
    return record

async def test_empty_tick_is_no_activity(tmp_path):
    r = runtime(tmp_path)
    await r.run_tick()
    assert r.last_selected == []
    assert any(e.get("reason") == "NO_ACTIVITY" for e in r.diagnostics()["timeline"])

async def test_fast_small_talk_advances_durable_cursor_without_provider(tmp_path):
    r = runtime(tmp_path)
    events = [fast(r, "哈哈") for _ in range(10)]
    await r.run_tick(force=FAST_DIGEST)
    assert r.state[FAST_DIGEST]["fast_digest_cursor"] == events[-1].event_id
    assert r.state[FAST_DIGEST]["last_result"] == "NO_CHANGE"
    assert not r.agent.provider.calls
    restored = InternalActivityRuntime(r.agent, r.settings, r.path)
    assert restored.state[FAST_DIGEST]["fast_digest_cursor"] == events[-1].event_id

async def test_fast_weak_trend_is_evidenced_and_does_not_move_normal_cursor(tmp_path):
    r = runtime(tmp_path)
    events = [fast(r, text) for text in ["日语唱K想加快学习", "还想练日语歌", "日语学习也要继续"] * 4]
    state = r.agent.current_cognition.state()
    state.last_processed_message_id = "normal-maintainer-cursor"
    r.agent.current_cognition.store.save(state)
    refs = [e.event_id for e in events[:3]]
    r.agent.provider.value = {"decision": "UPDATE", "evidence_message_ids": refs,
        "thread_ops": [{"action": "upsert", "key": "japanese_learning", "title": "日语学习",
            "summary": "想继续日语学习和练唱日语歌", "evidence_message_ids": refs}]}
    await r.run_tick(force=FAST_DIGEST)
    state = r.agent.current_cognition.state()
    assert state.threads[0].key == "japanese_learning"
    assert state.last_processed_message_id == "normal-maintainer-cursor"
    assert len(r.agent.provider.calls) == 1

async def test_fast_reject_and_failure_do_not_commit_cursor(tmp_path):
    r = runtime(tmp_path)
    for _ in range(10):
        fast(r, "想继续学日语")
    r.agent.provider.value = {"decision": "UPDATE", "evidence_message_ids": ["not-evidence"],
        "thread_ops": [{"action": "upsert", "key": "job", "title": "日语", "summary": "日语"}]}
    await r.run_tick(force=FAST_DIGEST)
    assert r.state[FAST_DIGEST]["last_result"] == "FAILED"
    assert not r.state[FAST_DIGEST].get("fast_digest_cursor")

async def test_untrusted_self_events_never_become_owner_digest(tmp_path):
    r = runtime(tmp_path)
    for _ in range(10):
        fast(r, "想学日语", actor_role="SELF")
    await r.run_tick(force=FAST_DIGEST)
    assert not r.agent.current_cognition.state().threads
    assert not r.agent.provider.calls

async def test_cognition_gardening_merges_cools_and_cleans_without_model(tmp_path):
    r = runtime(tmp_path)
    e = fast(r, "日语学习")
    now = datetime.now(UTC)
    thread = CognitionThread(key="japanese", title="日语学习", summary="练习日语", first_seen_at=now,
        last_updated_at=now, last_evidence_at=now - timedelta(days=4), source_refs=[EvidenceRef(event_id=e.event_id)])
    state = r.agent.current_cognition.state()
    state.threads = [thread, thread.model_copy(deep=True),
        thread.model_copy(update={"key": "resolved", "status": "resolved"}, deep=True)]
    state.watch_items = [JournalItem(key="unsupported", text="无效关注", created_at=now, updated_at=now)]
    r.agent.current_cognition.store.save(state)
    await r.run_tick(force="cognition_gardening")
    state = r.agent.current_cognition.state()
    assert len(state.threads) == 1 and state.threads[0].status == "cooling"
    assert state.threads[0].salience <= .45 and not state.watch_items
    assert not r.agent.provider.calls

async def test_gardening_deduplicates_without_creating_new_memory(tmp_path):
    r = runtime(tmp_path)
    service = await memory(r)
    first = (await service.remember(MemoryCreate(content="喜欢日语歌", kind="semantic"))).record
    duplicate = first.model_copy(update={"id": uuid4().hex}, deep=True)
    await service.repository.create(duplicate)
    await r.run_tick(force="memory_gardening")
    rows = await service.repository.list_records(MemoryQuery(statuses=[]))
    assert len(rows) == 2
    assert sum(x.status == MemoryStatus.SUPERSEDED for x in rows) == 1

async def test_reminiscence_never_raises_activation_or_recall_count(tmp_path):
    r = runtime(tmp_path)
    service = await memory(r)
    record = await old_memory(service)
    before = await service.repository.get(record.id)
    await r.run_tick(force=REMINISCENCE)
    after = await service.repository.get(record.id)
    assert (after.activation, after.access_count, after.accessed_at, after.updated_at) == (
        before.activation, before.access_count, before.accessed_at, before.updated_at)
    assert after.metadata["reminiscence_count"] == 1
    await r.run_tick(force=REMINISCENCE)
    assert (await service.repository.get(record.id)).metadata["reminiscence_count"] == 1
    assert not r.agent.provider.calls

async def test_reminiscence_avoids_recently_recalled_and_hot_memories(tmp_path):
    r = runtime(tmp_path)
    service = await memory(r)
    await old_memory(service, accessed_at=datetime.now(UTC))
    await old_memory(service, content="最近很热的记忆", activation=.9, status=MemoryStatus.ACTIVE)
    assert not await service.repository.reminiscence_candidates(datetime.now(UTC))

async def test_reminiscence_daily_cap_survives_restart(tmp_path):
    r = runtime(tmp_path, memory_reminiscence_daily_limit=1)
    service = await memory(r)
    await old_memory(service)
    await r.run_tick(force=REMINISCENCE)
    restored = InternalActivityRuntime(r.agent, r.settings, r.path)
    await restored.run_tick(force=REMINISCENCE)
    assert restored.last_skipped[REMINISCENCE] == "daily_budget"

async def test_cluster_split_candidate_is_incremental_and_no_embedding_api(tmp_path):
    r = runtime(tmp_path)
    service = await memory(r)
    cluster = MemoryCluster(topic="历史主题")
    await service.repository.save_cluster(cluster)
    for i in range(4):
        record = (await service.remember(MemoryCreate(content=f"历史歌曲记录 {i}", kind="episodic"))).record
        record.cluster_id = cluster.id
        await service.repository.save(record)
        await service.repository.add_cluster_member(cluster.id, record.id, .5)
        vector = [0.] * 256
        vector[0] = 1. if i % 2 else -1.
        await service.repository.save_embedding(MemoryEmbedding(memory_id=record.id,
            embedding_model="local-hash-v1", embedding_hash=str(i), vector=vector))
    await r.run_tick(force="cluster_gardening")
    clusters = await service.repository.list_clusters()
    assert len(clusters) == 1 and clusters[0].metadata["split_candidate"]
    assert not r.agent.provider.calls

async def test_social_lurk_is_read_only_and_records_self_provenance(tmp_path):
    r = runtime(tmp_path, social_lurk_enabled=True, social_wander_qq_allowed_groups=["123456"])
    social(r)
    await r.run_tick(force="social_lurk")
    assert r.state["social_lurk"]["last_result"] == "NO_MESSAGE"
    event = r.agent.experience_stream.recent(1)[0]
    assert event.actor_role == "SELF"
    assert event.metadata["source_plugin"] == "qq_napcat"
    assert event.conversation_id == "123456"
    assert not r.agent.provider.calls

async def test_social_requires_enabled_flag_and_whitelist_even_in_debug(tmp_path):
    r = runtime(tmp_path)
    social(r)
    await r.run_tick(force="social_wander", confirm_social_write=True)
    assert r.last_skipped["social_wander"] == "disabled"
    r.settings.social_wander_enabled = True
    await r.run_tick(force="social_wander", confirm_social_write=True)
    assert r.last_selected == []

@pytest.mark.parametrize("draft", ["暗苟明天面试公司", "主人今天的日程", "我妈妈在家", "其他群刚说", "私聊告诉我的", "暗苟让我告诉你", "owner has an interview", "密码是123456", "今晚20:00开会"])
def test_privacy_gate_rejects_private_or_owner_claims(draft):
    assert privacy_gate(draft).status == "REJECT"

async def test_public_context_excludes_private_stores(tmp_path):
    r = runtime(tmp_path)
    r.agent.agenda = "private-agenda"
    r.agent.memory_service = "private-memory"
    context = json.dumps(public_context(r, [], "日语歌"), ensure_ascii=False)
    assert "private-agenda" not in context and "private-memory" not in context
    assert "current_state" not in context and "threads" not in context

async def test_social_manual_write_confirmation_cooldown_and_daily_budget(tmp_path):
    r = runtime(tmp_path, social_wander_enabled=True, social_wander_chat_probability=1,
        social_wander_qq_allowed_groups=["123456"], social_wander_daily_message_limit=1)
    social(r)
    sent = []
    async def send(target, message):
        sent.append((target, message))
        return SendResult(sent=True, segment_count=1)
    r.agent.perception.sources = SimpleNamespace(send=send)
    r.agent.provider.value = {"action": "CHAT", "draft": "日语歌我也很喜欢，练唱挺有意思的。"}
    await r.run_tick(force="social_wander")
    assert not sent
    # Clear only activity cooldown to test confirmation; channel gates remain intact.
    r.state["social_wander"]["last_run_at"] = None
    await r.run_tick(force="social_wander", confirm_social_write=True)
    assert len(sent) == 1 and sent[0][0].metadata["actor_role"] == "SELF"
    restored = InternalActivityRuntime(r.agent, r.settings, r.path)
    restored.state["social_wander"]["last_run_at"] = None
    await restored.run_tick(force="social_wander", confirm_social_write=True)
    assert len(sent) == 1

async def test_social_privacy_rejection_never_reaches_transport(tmp_path):
    r = runtime(tmp_path, social_wander_enabled=True, social_wander_chat_probability=1,
        social_wander_qq_allowed_groups=["123456"])
    social(r)
    async def forbidden(*args):
        raise AssertionError("private draft must not be sent")
    r.agent.perception.sources = SimpleNamespace(send=forbidden)
    r.agent.provider.value = {"action": "CHAT", "draft": "暗苟明天要面试"}
    await r.run_tick(force="social_wander", confirm_social_write=True)
    assert r.state["social_wander"]["privacy_gate"]["status"] == "REJECT"
    assert r.daily_count("social_write") == 0

@pytest.mark.parametrize("state", ["ACTIVE", "AWAY", "SLEEP"])
async def test_presence_blocks_social_even_for_manual_trigger(tmp_path, state):
    r = runtime(tmp_path, social_lurk_enabled=True, social_wander_qq_allowed_groups=["123456"])
    interaction = Interaction()
    interaction.force_debug_state(InteractionState(state), datetime.now(UTC))
    r.agent.proactive_state = SimpleNamespace(interaction=interaction, interacting=False)
    social(r)
    await r.run_tick(force="social_lurk")
    assert r.last_selected == [] and r.last_skipped["social_lurk"] == "presence:" + state

async def test_foreground_preempts_leisure_and_recovers_tick(tmp_path):
    r = runtime(tmp_path)
    started = asyncio.Event()
    async def run(runtime, kind):
        started.set()
        await asyncio.Event().wait()
    async def due(runtime, now):
        return "read", Cost.EXTERNAL_READ.value
    r.registry.register(ActivitySpec("slow_lurk", Category.SOCIAL, Cost.EXTERNAL_READ,
        frozenset({Presence.SEMI_ACTIVE}), 10, 1, run, due))
    task = asyncio.create_task(r.run_tick(force="slow_lurk"))
    await started.wait()
    r.foreground_enter()
    await asyncio.wait_for(task, timeout=1)
    assert r.state["slow_lurk"]["last_result"] == "PREEMPTED"
    assert r.current_activity is None and r.presence() == Presence.ACTIVE
    r.foreground_exit()

async def test_manual_execution_cannot_bypass_external_budget(tmp_path):
    r = runtime(tmp_path, social_lurk_enabled=True, social_wander_qq_allowed_groups=["123456"],
        internal_activity_max_external_read_per_tick=0)
    social(r)
    await r.run_tick(force="social_lurk")
    assert r.last_skipped["social_lurk"] == "budget"

async def test_high_priority_debt_blocks_social_when_local_budget_empty(tmp_path):
    r = runtime(tmp_path, social_lurk_enabled=True, social_wander_qq_allowed_groups=["123456"],
        internal_activity_max_local_per_tick=0)
    social(r)
    now = datetime.now(UTC)
    state = r.agent.current_cognition.state()
    state.threads = [CognitionThread(key="old", title="旧主线", summary="已过期", first_seen_at=now,
        last_updated_at=now, last_evidence_at=now-timedelta(days=8))]
    r.agent.current_cognition.store.save(state)
    await r.run_tick()
    assert r.last_skipped["cognition_gardening"] == "budget"
    assert r.last_skipped["social_lurk"] == "maintenance_pending"


async def test_social_channel_cooldown_cannot_be_bypassed_by_force(tmp_path):
    r = runtime(tmp_path, social_wander_enabled=True, social_wander_chat_probability=1,
        social_wander_qq_allowed_groups=["123456"], social_wander_daily_message_limit=6)
    social(r)
    sent = []
    async def send(target, message):
        sent.append(target)
        return SendResult(sent=True, segment_count=1)
    r.agent.perception.sources = SimpleNamespace(send=send)
    r.agent.provider.value = {"action": "CHAT", "draft": "日语歌挺好听的。"}
    await r.run_tick(force="social_wander", confirm_social_write=True)
    r.state["social_wander"]["last_run_at"] = None
    await r.run_tick(force="social_wander", confirm_social_write=True)
    assert len(sent) == 1


async def test_manual_tick_does_not_grant_social_write(tmp_path):
    r = runtime(tmp_path, social_wander_enabled=True, social_wander_chat_probability=1,
        social_wander_qq_allowed_groups=["123456"])
    social(r)
    sent = []
    async def send(target, message):
        sent.append(target)
        return SendResult(sent=True)
    r.agent.perception.sources = SimpleNamespace(send=send)
    r.agent.provider.value = {"action": "CHAT", "draft": "练唱日语歌挺开心。"}
    await r.run_tick(manual=True)
    assert r.state["social_wander"]["last_result"] == "NO_MESSAGE"
    assert not sent


async def test_social_commit_is_not_cancelled_mid_send(tmp_path):
    r = runtime(tmp_path, social_wander_enabled=True, social_wander_chat_probability=1,
        social_wander_qq_allowed_groups=["123456"])
    social(r)
    started, finish = asyncio.Event(), asyncio.Event()
    async def send(target, message):
        started.set()
        await finish.wait()
        return SendResult(sent=True, segment_count=1)
    r.agent.perception.sources = SimpleNamespace(send=send)
    r.agent.provider.value = {"action": "CHAT", "draft": "日语歌很好听。"}
    task = asyncio.create_task(r.run_tick(force="social_wander", confirm_social_write=True))
    await started.wait()
    r.foreground_enter()
    finish.set()
    await asyncio.wait_for(task, timeout=1)
    assert r.state["social_wander"]["last_result"] == "MESSAGE"
    assert r.daily_count("social_write") == 1
    r.foreground_exit()


async def test_public_social_input_filters_owner_and_sensitive_group_messages(tmp_path):
    r = runtime(tmp_path)
    safe = social(r)
    secret = safe.model_copy(update={"content": "暗苟明天面试", "actor_role": "OWNER"})
    third_party = safe.model_copy(update={"content": "家人的手机号码123456789"})
    context = public_context(r, [secret, third_party, safe], "unused")
    assert "面试" not in context["group_context_untrusted"]
    assert "123456789" not in context["group_context_untrusted"]
    assert "练唱歌" in context["group_context_untrusted"]


async def test_social_reads_do_not_mix_plugins_groups_or_private_chats(tmp_path):
    r = runtime(tmp_path)
    observation = social(r)
    for values in ({"source_plugin": "other"}, {"conversation_id": "654321"}, {"conversation_kind": "private"}):
        item = observation.model_copy(update={"observation_id": uuid4().hex, "raw_ref": uuid4().hex, **values})
        r.agent.perception.store.insert(item, ObservationStatus.BUFFERED)
    observations = r.agent.perception.store.social_observations("qq_napcat", "123456", limit=20,
        since=datetime.now(UTC)-timedelta(hours=1))
    assert [o.observation_id for o in observations] == [observation.observation_id]


async def test_llm_budget_zero_prevents_digest_provider_call(tmp_path):
    r = runtime(tmp_path, internal_activity_max_llm_light_per_tick=0)
    for _ in range(10):
        fast(r, "日语学习想继续")
    await r.run_tick(force=FAST_DIGEST)
    assert r.last_skipped[FAST_DIGEST] == "budget"
    assert not r.agent.provider.calls


async def test_debug_http_api_is_authenticated_and_supports_new_activities(tmp_path):
    from zhaoxi.web.app import create_app
    from zhaoxi.core.conversation import Conversation
    from fastapi.testclient import TestClient
    r = runtime(tmp_path, perception_enabled=False,
        interface_settings_path=str(tmp_path / "interfaces.json"),
        filesystem_access_path=str(tmp_path / "filesystem.json"))
    r.agent.conversation = Conversation()
    r.agent.internal_activity = r
    r.agent.proactive_state = SimpleNamespace(interaction=Interaction(), interacting=False)
    # TestClient manages its own loop; keep this test free from a competing tick.
    with TestClient(create_app(agent=r.agent, settings=r.settings, api_token="test-token")) as client:
        assert client.get("/api/debug/internal-activity").status_code == 401
        client.headers["X-Zhaoxi-Token"] = "test-token"
        response = client.get("/api/debug/internal-activity")
        assert response.status_code == 200
        assert "fast_digest" in response.json()["activities"]
        assert client.post("/api/debug/presence", json={"state": "SLEEP"}).status_code == 200
        assert client.get("/api/recent-context").json()["presence"]["current_presence"] == "SLEEP"
        assert client.post("/api/debug/internal-activity", json={"activity": "social_wander"}).status_code == 200
        assert client.post("/api/debug/internal-activity", json={"activity": "unknown"}).status_code == 422


async def test_maintenance_failure_backoff_still_blocks_leisure(tmp_path):
    r = runtime(tmp_path, social_lurk_enabled=True, social_wander_qq_allowed_groups=["123456"])
    social(r)
    r.state["memory_gardening"].update(dirty=True, failure_count=3, last_run_at=datetime.now(UTC).isoformat())
    await r.run_tick()
    assert r.last_skipped["memory_gardening"] == "backoff"
    assert r.last_skipped["social_lurk"] == "maintenance_pending"
