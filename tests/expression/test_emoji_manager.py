import base64
import json

import pytest

from zhaoxi.core.conversation import Conversation
from zhaoxi.expression import EmojiManager, EmojiMetadata, EmojiService
from zhaoxi.tools.builtin.save_emoji import SaveEmojiTool
from zhaoxi.tools.registry import ToolRegistry


def data_url(kind="png", payload=None):
    raw = payload or (b"\x89PNG\r\n\x1a\n" + b"payload")
    return f"data:image/{kind};base64,{base64.b64encode(raw).decode()}"


def manager(tmp_path):
    registry = tmp_path / "emoji" / "emoji_registry.json"
    registry.parent.mkdir()
    registry.write_text("[]", encoding="utf-8")
    service = EmojiService(registry)
    return EmojiManager(service)


def meta(description="得意地邀功", enabled=True):
    return EmojiMetadata(description=description, tags=["得意", "邀功"], emotion="proud", intensity=.7, enabled=enabled)


def test_add_list_update_duplicate_delete_and_auto_reload(tmp_path):
    value = manager(tmp_path)
    added = value.add_data_url(data_url(), meta())
    assert added.status == "added" and added.emoji_id == "emoji_0001"
    assert value.service.entries[0].id == "emoji_0001"
    assert value.add_data_url(data_url(), meta()).status == "duplicate"
    assert value.list_all("邀功")[0]["id"] == "emoji_0001"
    assert value.update_metadata("emoji_0001", meta("改成轻微吐槽", enabled=False)).status == "updated"
    assert value.service.entries == []
    assert value.list_all(enabled=False)[0]["description"] == "改成轻微吐槽"
    image = value.image_path("emoji_0001")
    assert image and image.exists()
    assert value.delete("emoji_0001").status == "deleted"
    assert not image.exists() and value.list_all() == []


def test_registry_write_is_atomic_and_failed_add_rolls_back_file(tmp_path, monkeypatch):
    value = manager(tmp_path)
    original = value._write_registry
    monkeypatch.setattr(value, "_write_registry", lambda records: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        value.add_data_url(data_url(), meta())
    assert list(value.images_dir.iterdir()) == []
    monkeypatch.setattr(value, "_write_registry", original)
    value.add_data_url(data_url(), meta())
    assert not value.registry_path.with_suffix(".json.tmp").exists()
    assert json.loads(value.registry_path.read_text(encoding="utf-8"))[0]["id"] == "emoji_0001"


def test_pending_gif_preserved_commit_and_discard(tmp_path):
    value = manager(tmp_path)
    gif = data_url("gif", b"GIF89a" + b"animated")
    pending = value.add_pending(gif)
    path = value.pending_path(pending.pending_id)
    assert path.suffix == ".gif" and path.read_bytes().startswith(b"GIF89a")
    committed = value.commit_pending(pending.pending_id, meta())
    assert committed.status == "added"
    final = value.image_path(committed.emoji_id)
    assert final.suffix == ".gif" and final.read_bytes().startswith(b"GIF89a")
    another = value.add_pending(data_url(payload=b"\x89PNG\r\n\x1a\nother"))
    assert value.delete_pending(another.pending_id).status == "deleted"


@pytest.mark.asyncio
async def test_save_emoji_tool_resolves_latest_image_and_reports_not_found(tmp_path):
    value = manager(tmp_path)
    conversation = Conversation()
    conversation.add_user("这个存一下", images=[data_url()])
    tool = SaveEmojiTool(value, conversation)
    registry = ToolRegistry()
    registry.register(tool)
    assert registry.write_confirmation_required("save_emoji") is False
    result = await tool.run({"image_ref": "latest", "description": "得意邀功", "tags": ["得意"]})
    assert result.data["status"] == "added"
    missing = await tool.run({"image_ref": "missing", "description": "得意邀功", "tags": ["得意"]})
    assert missing.data["status"] == "not_found"
    assert value.service.entries[0].id == result.data["emoji_id"]
