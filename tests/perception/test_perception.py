import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from zhaoxi.adapters.qq.codec import decode
from zhaoxi.config.settings import Settings
from zhaoxi.core.message import Role
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
        provider = SimpleNamespace(generate=AsyncMock(return_value=ModelResponse(content="你好")))
        conversation = SimpleNamespace(messages=[])
        agent = SimpleNamespace(provider=provider, metrics=MetricRegistry(),
            context_builder=SimpleNamespace(character_prompt="朝汐"),
            conversation=conversation, conversation_lock=asyncio.Lock())
        runtime = PerceptionRuntime(settings, agent)
        await runtime.ingest(decode(event(1), self_id="42"))
        assert provider.generate.await_count == 0
        await runtime.ingest(decode(event(2), self_id="42"))
        snapshots = runtime.store.recent_snapshots("qq", "123")
        assert len(snapshots) == 1 and snapshots[0].message_count == 2
        direct = decode(event(3, [{"type": "at", "data": {"qq": "42"}}]), self_id="42")
        assert await runtime.ingest(direct) == "你好"
        assert agent.conversation.messages == []
        messages, tools = provider.generate.await_args.args
        assert tools == []
        assert all(message.role is Role.SYSTEM for message in messages)
        assert "不得自动写长期记忆" in messages[0].content
        assert await runtime.ingest(direct) is None
    asyncio.run(run())
