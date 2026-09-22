import json
import random

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.reply import EmojiSegment, TextSegment, commit_reply, parse_reply
from zhaoxi.expression import EmojiService
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.models.types import ModelResponse


def make_service(tmp_path):
    root = tmp_path / "emoji"
    (root / "images").mkdir(parents=True)
    records = [
        {"id": "proud_a", "file": "images/a.png", "description": "得意邀功", "tags": ["得意", "邀功"], "emotion": "proud", "enabled": True},
        {"id": "proud_b", "file": "images/b.png", "description": "得意邀功", "tags": ["得意", "邀功"], "emotion": "proud", "enabled": True},
        {"id": "disabled", "file": "images/c.png", "description": "开心", "tags": ["开心"], "emotion": "happy", "enabled": False},
    ]
    for name in ("a.png", "b.png", "c.png"):
        (root / "images" / name).write_bytes(b"image")
    path = root / "emoji_registry.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return EmojiService(path, random_source=random.Random(0))


def test_parser_covers_text_spacing_chinese_comma_empty_and_malformed():
    assert parse_reply("纯文本").segments == [TextSegment(content="纯文本")]
    sequence = parse_reply("开头\n[emoji: 得意， 邀功 ]\n结尾\n[emoji:得意]")
    assert [item.type for item in sequence.segments] == ["text", "emoji", "text", "emoji"]
    assert sequence.segments[1].requested_tags == ["得意", "邀功"]
    assert parse_reply("前[emoji:]后").visible_text == "前后"
    assert parse_reply("[emoji:开心").visible_text == "[emoji:开心"


def test_resolver_unknown_disabled_and_recent_downweight(tmp_path):
    service = make_service(tmp_path)
    assert service.resolve_tags(["宇宙爆炸式快乐"]).status == "no_match"
    assert service.resolve_tags(["开心"]).status == "no_match"
    first = service.resolve_tags(["得意", "邀功"])
    second = service.resolve_tags(["得意", "邀功"])
    assert first.emoji_id != second.emoji_id


def test_commit_reply_preserves_text_emoji_text_emoji_order(tmp_path):
    conversation = Conversation()
    sequence, ids = commit_reply(
        conversation,
        "哼。\n[emoji:得意,邀功]\n看见了吧。\n[emoji:得意]",
        make_service(tmp_path),
    )
    assert [item.type for item in sequence.segments] == ["text", "emoji", "text", "emoji"]
    assert [item.segment_type for item in conversation.messages] == ["text", "emoji", "text", "emoji"]
    assert [item.message_id for item in conversation.messages] == ids
    assert all("[emoji:" not in (item.content or "") for item in conversation.messages)


def test_context_has_enabled_tags_without_ids_or_paths(tmp_path):
    context = make_service(tmp_path).build_context()
    assert "[得意,邀功]" in context
    assert "开心" not in context
    assert "proud_a" not in context
    assert "images/" not in context


def test_send_emoji_is_not_a_builtin_tool():
    names = {tool.name for tool in create_builtin_tools()}
    assert "send_emoji" not in names


async def test_resolved_sequence_roundtrips_without_resolving_again(tmp_path):
    service = make_service(tmp_path)
    conversation = Conversation()
    commit_reply(conversation, "前\n[emoji:得意,邀功]\n后", service)
    selected = conversation.messages[1].emoji_id
    store = SQLiteSessionStore(tmp_path / "session.db")
    session = Session(id="local", conversation=conversation)
    await store.save(session)

    service.recent_ids.clear()
    service.recent_ids.append(selected)
    restored = await store.get("local")

    assert restored is not None
    assert [item.segment_type for item in restored.conversation.messages] == ["text", "emoji", "text"]
    assert restored.conversation.messages[1].emoji_id == selected
    assert restored.conversation.messages[1].requested_tags == ["得意", "邀功"]


async def test_agent_reply_flows_through_dsl_parser_and_resolver(tmp_path):
    service = make_service(tmp_path)
    agent = ZhaoxiAgent(
        provider=FakeProvider([ModelResponse(content="哼。\n[emoji:得意,邀功]\n看见了吧。")]),
        registry=ToolRegistry(),
        context_builder=ContextBuilder("朝汐", emoji_service=service),
    )

    response = await agent.run_direct("给我表演一下")

    assert response.content == "哼。\n\n看见了吧。"
    assert [item.segment_type for item in agent.conversation.messages[1:]] == ["text", "emoji", "text"]
    assert agent.last_emoji_trace["requested_tags"] == [["得意", "邀功"]]
    assert "[emoji:" not in response.content
