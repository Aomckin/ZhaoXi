import base64
import json
from datetime import UTC, datetime, timedelta

from zhaoxi.core.message import Message, Role
from zhaoxi.perception.models import Observation, ObservationPart, ObservationStatus
from zhaoxi.perception.store import PerceptionStore


def test_inspection_returns_compact_refs_without_hydrating_images(tmp_path, monkeypatch):
    store = PerceptionStore(tmp_path / "perception.db")
    image = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 500_000).decode()
    item = Observation(source="qq", source_kind="group_message", content="图片说明",
                       parts=[ObservationPart(type="image", url=image)])
    store.insert(item, ObservationStatus.PROCESSED)
    # The vision/provider path still receives the complete image as an image block.
    restored = store.recent_observations()[0]
    assert restored.parts[0].url == image
    message = Message(role=Role.EXTERNAL, content=restored.content, images=[restored.parts[0].url])
    content = message.to_provider_dict()["content"]
    assert content[0] == {"type": "text", "text": item.content}
    assert content[1]["image_url"]["url"] == image

    def refuse_hydration(*args):
        raise AssertionError("debug must not read image blobs")

    monkeypatch.setattr(store.media, "loads", refuse_hydration)
    result = store.inspect_recent_observations()
    ref = result[0]["parts"][0]["url"]
    assert ref["$media"].startswith("sha256:")
    assert ref["mime"] == "image/jpeg" and ref["size"] == 500_003
    assert result[0]["content"] == item.content
    assert len(json.dumps(result)) < 2000


def test_inspection_omits_legacy_inline_payloads_without_rewriting_records(tmp_path):
    store = PerceptionStore(tmp_path / "perception.db")
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 50_000).decode()
    item = Observation(source="qq", source_kind="group_message", content="原始文本",
                       parts=[ObservationPart(type="image", url="data:image/png;base64," + encoded)],
                       metadata={"attachment": {"file": "base64://" + encoded}, "ordinary_url": "https://example.test/image.png"})
    raw = item.model_dump_json()
    store.insert(item, ObservationStatus.PROCESSED)
    with store._connect() as db:
        db.execute("UPDATE observations SET payload=? WHERE id=?", (raw, item.observation_id))
    result = store.inspect_recent_observations()[0]
    assert result["parts"][0]["url"] == {"$inline_media": True, "mime": "image/png",
                                          "encoded_chars": len(encoded), "payload_omitted": True}
    assert result["metadata"]["attachment"]["file"]["payload_omitted"] is True
    assert result["metadata"]["ordinary_url"] == item.metadata["ordinary_url"]
    assert result["content"] == item.content
    assert len(json.dumps(result)) < 2000
    with store._connect() as db:
        assert db.execute("SELECT payload FROM observations WHERE id=?", (item.observation_id,)).fetchone()[0] == raw


def test_inspection_preserves_recent_order_and_limit(tmp_path):
    store = PerceptionStore(tmp_path / "perception.db")
    now = datetime.now(UTC)
    for index in range(3):
        store.insert(Observation(source="qq", source_kind="group_message", content=str(index),
                                 received_at=now + timedelta(seconds=index)), ObservationStatus.BUFFERED)
    assert [item["content"] for item in store.inspect_recent_observations(2)] == ["2", "1"]
