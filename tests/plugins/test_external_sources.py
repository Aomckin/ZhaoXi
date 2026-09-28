import asyncio
from types import SimpleNamespace
import pytest

from zhaoxi.perception.models import Observation
from zhaoxi.plugins.manifests import PluginManifest
from zhaoxi.plugins.registry import PluginRegistry
from zhaoxi.plugins.source_router import PerceptionSink, outbound_message, reply_target
from zhaoxi.sdk.external_source import SourceCapabilities, SendResult
from zhaoxi_ext.qq_napcat.codec import decode

class FakeSource:
    def __init__(self, name):
        self.plugin_id = name
        self.sink = None
        self.started = 0
        self.stopped = 0
        self.ready = asyncio.Event()
        self.sent = []

    async def start(self, sink):
        self.sink = sink
        self.started += 1
        self.ready.set()
        await asyncio.Event().wait()

    async def stop(self):
        self.stopped += 1
        self.sink = None

    def capabilities(self):
        return SourceCapabilities(text_in=True, text_out=True)

    def diagnostics(self):
        return {"started": self.started}

    async def send(self, target, content):
        self.sent.append((target, content))
        return SendResult(sent=True, segment_count=1)


def manifest(name):
    return PluginManifest(id=name, name=name, version="1", entrypoint="none:None")

@pytest.mark.asyncio
async def test_zero_plugin_and_two_source_hot_disable():
    events = []
    sink = SimpleNamespace(emit=lambda event: events.append(event))
    async def receive(event):
        events.append(event)
    sink.emit = receive
    registry = PluginRegistry(sink)
    assert registry.diagnostics() == []
    one, two = FakeSource("one"), FakeSource("two")
    registry.register(manifest("one"), plugin=one)
    registry.register(manifest("two"), plugin=two)
    await registry.enable("one")
    await registry.enable("two")
    await one.sink.emit(Observation(source="mock", source_kind="message"))
    await two.sink.emit(Observation(source="mock", source_kind="message"))
    assert [event.source_plugin for event in events] == ["one", "two"]
    await registry.disable("one")
    assert one.stopped == 1
    assert registry.diagnostics()[0]["status"] == "disabled"
    await registry.enable("one")
    assert one.started == 2
    await registry.stop()
    assert two.stopped == 1

@pytest.mark.asyncio
async def test_source_router_returns_reply_to_origin():
    one, two = FakeSource("one"), FakeSource("two")
    perception = SimpleNamespace(agent=SimpleNamespace(emoji_service=None),
        ingest=None, reply_sent=None, last_error=None)
    async def ingest(event):
        return "hello"
    sent = []
    async def reply_sent(*args):
        sent.append(args)
    perception.ingest, perception.reply_sent = ingest, reply_sent
    registry = PluginRegistry(None)
    registry.sink = PerceptionSink(perception, registry)
    registry.register(manifest("one"), plugin=one)
    registry.register(manifest("two"), plugin=two)
    await registry.enable("one")
    await registry.enable("two")
    await two.sink.emit(Observation(source="mock", source_kind="message",
        conversation_id="room", conversation_kind="private", actor_id="user",
        metadata={"message_id": "77"}))
    assert not one.sent
    target, message = two.sent[0]
    assert target.message_ref == "77" and message.parts[0].text == "hello"
    assert sent[0][2] == 1
    await registry.stop()

@pytest.mark.asyncio
async def test_import_failure_degrades_only_plugin():
    registry = PluginRegistry(SimpleNamespace(emit=None))
    registry.register(PluginManifest(id="bad", name="bad", version="1",
        entrypoint="nonexistent_package:Plugin"))
    registry.register(manifest("good"), plugin=FakeSource("good"))
    await registry.enable("bad")
    await registry.enable("good")
    states = {item["plugin_id"]: item["status"] for item in registry.diagnostics()}
    assert states == {"bad": "degraded", "good": "running"}
    await registry.stop()

def test_qq_codec_provides_standard_identity_and_target():
    event = {"post_type": "message", "message_type": "private", "user_id": 8,
        "message_id": 9, "message": "hello"}
    observation = decode(event, self_id="42", owner_id="8")
    assert observation.actor_role == "OWNER"
    assert observation.source_plugin == "qq_napcat"
    assert reply_target(observation).source_plugin == "qq_napcat"


@pytest.mark.asyncio
async def test_crashed_start_and_send_do_not_break_other_sources():
    class Crashed(FakeSource):
        async def start(self, sink):
            raise RuntimeError("startup")
    class FailedSend(FakeSource):
        async def send(self, target, content):
            raise ConnectionError("send")
    registry = PluginRegistry(SimpleNamespace(emit=None))
    registry.register(manifest("crashed"), plugin=Crashed("crashed"))
    registry.register(manifest("failed_send"), plugin=FailedSend("failed_send"))
    await registry.enable("crashed")
    await registry.enable("failed_send")
    await asyncio.sleep(0)
    assert registry.diagnostics()[0]["status"] == "degraded"
    result = await registry.send(reply_target(Observation(source="mock",
        source_plugin="failed_send", source_kind="message",
        conversation_id="1", conversation_kind="private")),
        outbound_message("hello"))
    assert not result.sent
    assert registry.diagnostics()[1]["status"] == "degraded"
    await registry.stop()

def test_manifest_error_is_reported_without_losing_valid_source(tmp_path):
    from zhaoxi.plugins.loader import discover
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    good.mkdir()
    bad.mkdir()
    (good / "manifest.toml").write_text('id="good"\nname="Good"\nversion="1"\nentrypoint="x:Y"\n')
    (bad / "manifest.toml").write_text("broken = [")
    errors = []
    found = discover(tmp_path, errors)
    assert list(found) == ["good"]
    assert errors == [("bad", "TOMLDecodeError")]

def test_loads_manifest_plugin_from_local_directory(tmp_path):
    from zhaoxi.plugins.loader import discover, load
    folder = tmp_path / "local_source"
    folder.mkdir()
    (folder / "manifest.toml").write_text(
        'id="local_source"\nname="Local"\nversion="1"\nentrypoint="plugin:LocalSource"\n')
    (folder / "plugin.py").write_text(
        'class LocalSource:\n    plugin_id = "local_source"\n')
    plugin = load(discover(tmp_path)["local_source"])
    assert plugin.plugin_id == "local_source"

@pytest.mark.asyncio
async def test_perception_operates_with_no_source_plugins(tmp_path):
    from zhaoxi.config.settings import Settings
    from zhaoxi.core.context import ContextBuilder
    from zhaoxi.perception.runtime import PerceptionRuntime
    from zhaoxi.reliability import MetricRegistry
    settings = Settings(_env_file=None,
        perception_db_path=str(tmp_path / "perception.db"),
        perception_image_temp_dir=str(tmp_path / "images"))
    agent = SimpleNamespace(context_builder=ContextBuilder("朝汐"),
                            metrics=MetricRegistry())
    runtime = PerceptionRuntime(settings, agent)
    runtime.sources = PluginRegistry(None)
    observation = Observation(source="mock", source_kind="message",
        conversation_id="room", conversation_kind="group", content="ambient")
    assert await runtime.ingest(observation) is None
    assert runtime.diagnostics()["source_count"] == 0
    assert runtime.store.recent_observations()[0].content == "ambient"
