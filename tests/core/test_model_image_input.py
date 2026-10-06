import base64
from io import BytesIO

from PIL import Image

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.image_thumbnails import ImageThumbnailCache


def test_five_large_current_images_are_bounded_without_mutating_originals(tmp_path, five_large_photos, monkeypatch):
    cache = ImageThumbnailCache(tmp_path / "previews")
    builder = ContextBuilder("朝汐", image_thumbnail_cache=cache)
    conversation = Conversation()
    original = conversation.add_user("把这五张照片记到 LifeHUD", images=list(five_large_photos))
    messages = builder.build(conversation)
    outgoing = messages[-1].images
    assert len(outgoing) == 5
    colors = []
    sizes = []
    for source, preview in zip(five_large_photos, outgoing):
        assert 2_000_000 < len(base64.b64decode(source.split(",", 1)[1])) < 3_500_000
        payload = base64.b64decode(preview.split(",", 1)[1])
        sizes.append(len(payload))
        assert len(payload) <= cache.MODEL_MAX_BYTES
        with Image.open(BytesIO(payload)) as image:
            assert max(image.size) <= cache.MODEL_MAX_EDGE
            colors.append(image.getpixel((5, 5))[0])
    assert colors == sorted(colors) and len(set(colors)) == 5
    assert sum(sizes) <= 5 * 512 * 1024
    assert conversation.messages[-1].images == list(five_large_photos)
    cache.retain(conversation.messages)
    assert len(list(cache.directory.glob("*-model.jpg"))) == 5
    def unexpected_decode(*args, **kwargs):
        raise AssertionError("a model-loop round decoded the original photos again")
    monkeypatch.setattr(Image, "open", unexpected_decode)
    final = builder.build(conversation, release_images=True, preserve_current_image=True,
                          current_image_message_id=original.message_id)
    assert final[-1].images == outgoing


def test_all_historical_images_remain_thumbnails_without_count_limit():
    import base64
    output = BytesIO()
    Image.new("RGB", (1000, 800), "red").save(output, format="PNG")
    photo = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    conversation = Conversation()
    old = [conversation.add_user("旧照片", images=[photo] * 5) for _ in range(6)]
    current = conversation.add_user("看这五张新图", images=[photo] * 5)
    context = ContextBuilder("朝汐").build(conversation)
    assert sum(len(m.images) for m in context) == 35
    assert next(m for m in context if m.message_id == current.message_id).images == [photo] * 5
    historical = [m for m in context if m.message_id in {p.message_id for p in old}]
    assert all(len(m.images) == 5 and "历史图片摘要" not in m.content for m in historical)
    for message in historical:
        for preview in message.images:
            assert preview != photo
            with Image.open(BytesIO(base64.b64decode(preview.split(",", 1)[1]))) as image:
                assert max(image.size) == 512
    assert all(len(m.images) == 5 for m in conversation.messages)
