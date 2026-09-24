import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.errors import ProviderError
from zhaoxi.models.types import ModelResponse
from zhaoxi.short_term_memory import ShortTermMemoryMaintainer, ShortTermMemoryService, ShortTermMemoryStore
from zhaoxi.short_term_memory.models import Category, Source, Status
from zhaoxi.short_term_memory.service import ItemProposal, ItemUpdate, Reinforcement, ShortTermMemoryPatch


ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 23, 12, tzinfo=ZONE)


def make_service(tmp_path):
    return ShortTermMemoryService(ShortTermMemoryStore(tmp_path / "stm.db"))


def proposal(category, content, message_id):
    return ItemProposal(category=category, content=content, source=Source.USER,
                        source_message_id=message_id)


def test_persists_across_restart_and_forty_message_window(tmp_path):
    service = make_service(tmp_path)
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[proposal(
        Category.ACTIVE_CONTEXT, "近期持续参与秋招", "old")]),
        source_by_id={"old": "user"}, last_message_id="old", now=NOW)
    conversation = Conversation(max_messages=40)
    for index in range(50):
        conversation.add_user(f"第 {index} 条关于朝汐开发的消息")
    assert all(message.message_id != "old" for message in conversation.messages)
    restored = make_service(tmp_path)
    built = ContextBuilder("人格", short_term_memory_service=restored).build(conversation)
    assert "近期持续参与秋招" in built[0].content
    assert len(built) == 41
    assert restored.diagnostics()["last_processed_message_id"] == "old"


def test_topic_requires_reinforcement_and_no_change_preserves_text(tmp_path):
    service = make_service(tmp_path)
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[proposal(
        Category.RECENT_TOPIC, "近期动漫与角色绘图讨论增加", "u1")]),
        source_by_id={"u1": "user"}, last_message_id="u1", now=NOW)
    item = service.state().items[0]
    assert "动漫" not in service.snapshot()
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[proposal(
        Category.RECENT_TOPIC, "近期动漫与角色绘图讨论增加", "u1")]),
        source_by_id={"u1": "user"}, last_message_id="u1", now=NOW)
    assert "动漫" not in service.snapshot()
    service.apply(ShortTermMemoryPatch(action="NO_CHANGE"), source_by_id={"u2": "user"},
                  last_message_id="u2", now=NOW + timedelta(hours=1))
    assert service.state().items[0].content == item.content
    service.apply(ShortTermMemoryPatch(action="UPDATE", reinforce=[Reinforcement(
        id=item.id, source_message_id="u3")]), source_by_id={"u3": "user"},
        last_message_id="u3", now=NOW + timedelta(days=1))
    assert "动漫" in service.snapshot()
    assert service.state().items[0].reinforcements == 2


def test_explicit_correction_replaces_conflicting_state_and_age_fades_topic(tmp_path):
    service = make_service(tmp_path)
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[
        proposal(Category.ACTIVE_THREAD, "近期准备算法岗", "u1"),
        proposal(Category.RECENT_TOPIC, "近期讨论某部动漫", "u1"),
    ]), source_by_id={"u1": "user"}, last_message_id="u1", now=NOW)
    old, topic = service.state().items
    service.apply(ShortTermMemoryPatch(action="UPDATE", update=[ItemUpdate(
        id=old.id, content="近期转向后端与 AI 应用岗位", source=Source.USER,
        source_message_id="u2")]), source_by_id={"u2": "user"}, last_message_id="u2",
        now=NOW + timedelta(days=1))
    assert "算法岗" not in service.snapshot()
    assert "后端与 AI 应用" in service.snapshot()
    service.apply(ShortTermMemoryPatch(action="NO_CHANGE"), source_by_id={"u3": "user"},
                  last_message_id="u3", now=NOW + timedelta(days=5))
    assert next(x for x in service.state().items if x.id == topic.id).status == Status.FADING
    service.apply(ShortTermMemoryPatch(action="UPDATE", remove=[topic.id]),
                  source_by_id={"u4": "user"}, last_message_id="u4", now=NOW + timedelta(days=6))
    assert all(x.id != topic.id for x in service.state().items)


def test_rejects_unproven_assistant_or_mismatched_source(tmp_path):
    service = make_service(tmp_path)
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[
        ItemProposal(category=Category.ACTIVE_CONTEXT, content="通过动漫逃避秋招压力",
                     source=Source.ASSISTANT, source_message_id="a1"),
        ItemProposal(category=Category.ACTIVE_CONTEXT, content="无证据推测",
                     source=Source.USER, source_message_id="a1"),
    ]), source_by_id={"a1": "assistant"}, last_message_id="a1", now=NOW)
    assert service.state().items == []
    assert "逃避" not in service.snapshot()


def test_causal_psychological_guess_requires_explicit_user_evidence(tmp_path):
    service = make_service(tmp_path)
    text = "秋招比较忙，最近动漫聊得比较多"
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[proposal(
        Category.ACTIVE_CONTEXT, "通过动漫逃避秋招压力", "u1")]),
        source_by_id={"u1": "user"}, evidence_by_id={"u1": text},
        last_message_id="u1", now=NOW)
    assert service.state().items == []
    explicit = "我确实在通过动漫逃避秋招压力"
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=[proposal(
        Category.ACTIVE_CONTEXT, "通过动漫逃避秋招压力", "u2")]),
        source_by_id={"u2": "user"}, evidence_by_id={"u2": explicit},
        last_message_id="u2", now=NOW)
    assert "逃避秋招压力" in service.snapshot()


class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0
        self.requests = []

    async def generate(self, messages, tools=None, **kwargs):
        self.calls += 1
        self.requests.append((messages, kwargs))
        value = next(self.outputs)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, ModelResponse):
            return value
        if isinstance(value, str):
            return ModelResponse(content=value)
        return ModelResponse(content=json.dumps(value, ensure_ascii=False))


@pytest.mark.asyncio
async def test_maintainer_no_change_then_merge_then_failure_keeps_state(tmp_path):
    service = make_service(tmp_path)
    provider = FakeProvider([
        {"action": "NO_CHANGE"},
        {"action": "UPDATE", "add": [{"category": "active_context", "content": "近期持续参与秋招",
                                      "source": "user", "source_message_id": "u2"}]},
        RuntimeError("provider offline"),
    ])
    maintainer = ShortTermMemoryMaintainer(service, provider)
    messages = [Message(message_id="u1", role=Role.USER, content="哈哈哈哈")]
    assert await maintainer.maintain(messages) == "NO_CHANGE"
    assert service.state().items == []
    messages.append(Message(message_id="u2", role=Role.USER, content="最近仍在忙秋招"))
    assert await maintainer.maintain(messages) == "UPDATE"
    assert "秋招" in service.snapshot()
    messages.append(Message(message_id="u3", role=Role.USER, content="继续说"))
    assert await maintainer.maintain(messages) == "FAILED"
    assert "秋招" in make_service(tmp_path).snapshot()
    assert service.diagnostics()["last_maintenance"]["result"] == "FAILED"
    assert make_service(tmp_path).diagnostics()["last_maintenance"]["result"] == "FAILED"


@pytest.mark.asyncio
async def test_maintainer_recovers_from_invalid_json_with_smaller_batch(tmp_path):
    service = make_service(tmp_path)
    provider = FakeProvider([
        ModelResponse(content="", finish_reason="length"),
        {"action": "UPDATE", "add": [{"category": "active_context", "content": "近期持续参与秋招",
                                       "source": "user", "source_message_id": "u19"}]},
    ])
    messages = [Message(message_id=f"u{i}", role=Role.USER, content="最近仍在忙秋招") for i in range(20)]
    maintainer = ShortTermMemoryMaintainer(service, provider)
    assert await maintainer.maintain(messages) == "UPDATE"
    assert "秋招" in service.snapshot()
    assert provider.calls == 2
    assert len(json.loads(provider.requests[0][0][1].content)["new_messages"]) == 20
    retry_ids = [entry["id"] for entry in json.loads(provider.requests[1][0][1].content)["new_messages"]]
    assert len(retry_ids) == 16
    assert retry_ids[0] == "u0" and retry_ids[-1] == "u19"
    assert provider.requests[0][1]["response_format"] == {"type": "json_object"}
    assert provider.requests[1][1]["max_tokens"] > provider.requests[0][1]["max_tokens"]


@pytest.mark.asyncio
async def test_maintainer_accepts_wrapped_json_without_retry(tmp_path):
    service = make_service(tmp_path)
    provider = FakeProvider(['```json\n{"action":"NO_CHANGE"}\n```'])
    maintainer = ShortTermMemoryMaintainer(service, provider)
    assert await maintainer.maintain([Message(message_id="u1", role=Role.USER, content="哈哈")]) == "NO_CHANGE"
    assert provider.calls == 1
    assert service.state().last_processed_message_id == "u1"


@pytest.mark.asyncio
async def test_maintainer_falls_back_when_provider_rejects_json_mode(tmp_path):
    service = make_service(tmp_path)
    provider = FakeProvider([ProviderError("HTTP 400", code="provider_http_400"),
                             {"action": "NO_CHANGE"}])
    maintainer = ShortTermMemoryMaintainer(service, provider)
    assert await maintainer.maintain([Message(message_id="u1", role=Role.USER, content="哈哈")]) == "NO_CHANGE"
    assert provider.calls == 2
    assert provider.requests[0][1]["response_format"] == {"type": "json_object"}
    assert "response_format" not in provider.requests[1][1]


@pytest.mark.asyncio
async def test_maintainer_persists_safe_diagnostics_after_two_invalid_responses(tmp_path, caplog):
    service = make_service(tmp_path)
    provider = FakeProvider([ModelResponse(content="私人对话原文", finish_reason="length"),
                             ModelResponse(content='{"action":', finish_reason="length")])
    maintainer = ShortTermMemoryMaintainer(service, provider)
    assert await maintainer.maintain([Message(message_id="u1", role=Role.USER, content="私人对话原文")]) == "FAILED"
    result = make_service(tmp_path).diagnostics()["last_maintenance"]
    assert result["attempt"] == 2
    assert result["finish_reason"] == "length"
    assert result["response_chars"] == len('{"action":')
    assert result["error_position"] == len('{"action":')
    assert result["last_processed_message_id"] is None
    assert "私人对话原文" not in caplog.text


def test_capacity_is_bounded_without_filling_unused_categories(tmp_path):
    service = make_service(tmp_path)
    subjects = ["岗位投递", "项目演示", "线下活动", "朝汐重构", "作品绘图", "课程收尾",
                "旅行准备", "读书安排", "设备更换", "写作进展"]
    adds = [proposal(Category.RECENT_CHANGE, subject, f"u{i}") for i, subject in enumerate(subjects)]
    service.apply(ShortTermMemoryPatch(action="UPDATE", add=adds[:10]),
                  source_by_id={f"u{i}": "user" for i in range(10)}, last_message_id="u9", now=NOW)
    assert len(service.state().items) == 6
    assert not any(x.category == Category.UNRESOLVED for x in service.state().items)
