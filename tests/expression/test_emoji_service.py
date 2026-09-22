import json
import random

import pytest

from zhaoxi.expression import EmojiService
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.reply import commit_reply


def make_registry(tmp_path, records):
    root = tmp_path / "emoji"
    images = root / "images"
    images.mkdir(parents=True)
    for record in records:
        if record.pop("make_file", True):
            (root / record["file"]).write_bytes(b"image")
    path = root / "emoji_registry.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def entry(identifier, description, tags, emotion, *, enabled=True, make_file=True):
    return {"id": identifier, "file": f"images/{identifier}.png", "description": description,
            "tags": tags, "emotion": emotion, "intensity": 0.7, "enabled": enabled,
            "make_file": make_file}


def test_registry_skips_disabled_and_missing_files(tmp_path):
    path = make_registry(tmp_path, [
        entry("ready", "被夸奖后很得意", ["得意"], "proud"),
        entry("disabled", "开心", ["开心"], "happy", enabled=False),
        entry("missing", "无语", ["无语"], "speechless", make_file=False),
    ])
    assert [item.id for item in EmojiService(path).entries] == ["ready"]


def test_invalid_json_returns_no_match_without_crashing(tmp_path):
    path = tmp_path / "emoji_registry.json"
    path.write_text("{bad", encoding="utf-8")
    service = EmojiService(path)
    assert service.select("开心").status == "no_match"
    assert service.diagnostics()["load_error"] == "registry_invalid"


def test_search_prefers_semantic_match_and_rejects_unrelated(tmp_path):
    path = make_registry(tmp_path, [
        entry("proud", "被主人夸奖后明显有点得意，想邀功", ["得意", "邀功"], "proud"),
        entry("speechless", "无语又嫌弃地看着对方，适合吐槽", ["无语", "嫌弃"], "speechless"),
    ])
    service = EmojiService(path)
    assert service.search("被主人夸了以后非常得意")[0].emoji_id == "proud"
    assert service.search("无语地看着对方")[0].emoji_id == "speechless"
    assert service.search("讨论 MySQL RR 隔离级别的技术细节") == []


def test_recent_history_avoids_immediate_repeat(tmp_path):
    path = make_registry(tmp_path, [
        entry("proud_a", "被夸奖后得意邀功", ["得意", "邀功"], "proud"),
        entry("proud_b", "做成事情后开心得意地炫耀", ["得意", "炫耀"], "proud"),
    ])
    service = EmojiService(path, random_source=random.Random(0))
    first = service.select("被夸奖后得意", "proud")
    second = service.select("被夸奖后得意", "proud")
    assert first.status == second.status == "matched"
    assert first.emoji_id != second.emoji_id


def test_resolve_tags_returns_structured_match(tmp_path):
    path = make_registry(tmp_path, [entry("proud", "被夸奖后得意", ["得意"], "proud")])
    result = EmojiService(path).resolve_tags(["得意"])
    assert result.status == "matched"
    assert result.emoji_id == "proud"


def test_matched_reply_segment_becomes_independent_image_message(tmp_path):
    path = make_registry(tmp_path, [entry("proud", "被夸奖后得意", ["得意"], "proud")])
    conversation = Conversation()
    sequence, _ = commit_reply(conversation, "[emoji:得意]", EmojiService(path))
    message = conversation.messages[-1]
    assert message.is_image_only
    assert message.source == "emoji"
    assert message.emoji_id == "proud"
    assert message.images == ["/api/expression/emoji/proud"]
    assert message.requested_tags == ["得意"]
    assert sequence.segments[0].emoji_id == "proud"
