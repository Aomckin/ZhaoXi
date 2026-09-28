import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zhaoxi_ext.qq_napcat.codec import decode
from zhaoxi.config.settings import Settings
from zhaoxi.core.message import Role
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream, AttentionRetriever
from zhaoxi.models.types import ModelResponse
from zhaoxi.perception import PerceptionRuntime, PerceptionStore
from zhaoxi.perception.models import AttentionHint, Observation, TrustLevel
from zhaoxi.perception.router import route
from zhaoxi.reliability import MetricRegistry


def event(message_id=1, message=None, user_id=9, kind="group"):
    return {"post_type": "message", "message_type": kind, "group_id": 123,
            "user_id": user_id, "message_id": message_id, "time": 1000000000,
            "sender": {"nickname": "A"}, "message": message or [{"type": "text", "data": {"text": "hello"}}]}


def test_codec_routes_and_provenance():
    plain = decode(event(), self_id="42")
    assert route(plain) is AttentionHint.AMBIENT
    assert plain.raw_ref == "qq:group:123:1"
    assert plain.trust_level is TrustLevel.LOW
    direct = decode(event(2, [{"type": "at", "data": {"qq": "42"}},
                              {"type": "text", "data": {"text": " hi"}}]), self_id="42")
    assert route(direct) is AttentionHint.DIRECT
    assert route(decode(event(3, user_id=42), self_id="42")) is AttentionHint.IGNORE
    assert decode({"post_type": "meta_event", "meta_event_type": "heartbeat"}, self_id="42") is None
    owner = decode(event(4, user_id=8), self_id="42", owner_id="8")
    assert owner.actor_role == "OWNER" and owner.trust_level is TrustLevel.TRUSTED


def test_model_requires_timezone():
    try:
        Observation(source="x", source_kind="y", occurred_at=datetime(2020, 1, 1))
    except ValueError:
        pass
    else:
        raise AssertionError("naive timestamp accepted")


def test_store_dedupe_and_restart(tmp_path):
    path = tmp_path / "perception.db"
    first = decode(event(), self_id="42")
    store = PerceptionStore(path)
    assert store.insert(first, __import__("zhaoxi.perception.models", fromlist=["ObservationStatus"]).ObservationStatus.BUFFERED)
    assert not PerceptionStore(path).insert(decode(event(), self_id="42"), __import__("zhaoxi.perception.models", fromlist=["ObservationStatus"]).ObservationStatus.BUFFERED)
    assert len(PerceptionStore(path).buffered(store.bucket(first))) == 1


def test_ambient_batch_and_external_boundary(tmp_path):
    async def run():
        settings = Settings(perception_db_path=str(tmp_path / "perception.db"),
                            perception_batch_max_messages=2)
        responses = AsyncMock(side_effect=[
            ModelResponse(content="你好"),
            ModelResponse(content="你好"),
        ])
        async def generate(messages, tools=None, **kwargs):
            return await responses(messages, tools)
        provider = SimpleNamespace(generate=generate)
        builder = ContextBuilder("朝汐")
        agent = ZhaoxiAgent(
            provider=provider, registry=ToolRegistry(override_path=tmp_path / "tools.json"),
            context_builder=builder,
        )
        agent.metrics = MetricRegistry()
        agent.conversation_lock = asyncio.Lock()
        agent.experience_stream = ExperienceStream(tmp_path / "experience.db")
        agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
        agent.attention_retriever = AttentionRetriever(agent.experience_stream)
        builder.attention_retriever = agent.attention_retriever
        runtime = PerceptionRuntime(settings, agent)
        await runtime.ingest(decode(event(1), self_id="42"))
        assert responses.await_count == 0
        await runtime.ingest(decode(event(2), self_id="42"))
        snapshots = runtime.store.recent_snapshots("qq", "123")
        assert len(snapshots) == 1 and snapshots[0].message_count == 2
        direct = decode(event(3, [{"type": "at", "data": {"qq": "42"}},
                                  {"type": "text", "data": {"text": " 请问这是什么？"}}]), self_id="42")
        assert await runtime.ingest(direct) == "你好"
        assert agent.conversation.messages == []
        messages, tools = responses.await_args.args
        assert tools is None
        assert any(message.role is Role.EXTERNAL for message in messages)
        assert "私人日程" in messages[0].content
        assert await runtime.ingest(direct) is None
    asyncio.run(run())
