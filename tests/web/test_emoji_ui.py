from pathlib import Path
import base64
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from zhaoxi.config.settings import Settings
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from conftest import FakeProvider
from zhaoxi.expression import EmojiManager, EmojiService
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.web.app import create_app


def test_reply_renderer_is_served_before_the_shell():
    from web_fixture import FakeAgent

    with TestClient(create_app(agent=FakeAgent(), settings=Settings(dev_browser_ui=True, perception_enabled=False))) as client:
        for route in ("/", "/static/engineering.html"):
            response = client.get(route)
            assert response.status_code == 200
            assert response.text.index('/static/reply-renderer.js') < response.text.index('/static/shell.js')
        response = client.get("/static/reply-renderer.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]


def test_emoji_debug_and_guarded_image_endpoint(tmp_path):
    root = tmp_path / "emoji"
    (root / "images").mkdir(parents=True)
    (root / "images/wave.gif").write_bytes(b"GIF89a")
    (root / "emoji_registry.json").write_text(json.dumps([{
        "id": "wave", "file": "images/wave.gif", "description": "开心地挥手",
        "tags": ["开心", "挥手"], "emotion": "happy", "enabled": True,
    }], ensure_ascii=False), encoding="utf-8")
    service = EmojiService(root / "emoji_registry.json")
    manager = EmojiManager(service)
    agent = SimpleNamespace(
        conversation=Conversation(), proactive=None, proactive_scheduler=None,
        proactive_state=None, planner=None, workflow=None,
        tool_executor=SimpleNamespace(gateway=SimpleNamespace(store=SimpleNamespace(pending={}))),
        emoji_service=service, emoji_manager=manager,
    )
    with TestClient(create_app(agent=agent)) as client:
        assert client.get("/api/debug/emoji").json()["loaded_emojis"] == 1
        tested = client.post("/api/debug/emoji", json={"intent": "开心地挥手"}).json()
        assert tested["candidates"][0]["emoji_id"] == "wave"
        response = client.get("/api/expression/emoji/wave")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/gif"
        assert client.get("/api/expression/emoji/../secret").status_code == 404
        png = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\napi").decode()
        created = client.post("/api/emoji", json={"data_url": png, "description": "开心挥手", "tags": ["开心"], "emotion": "happy", "intensity": .5, "enabled": True}).json()
        emoji_id = created["emoji_id"]
        assert client.get("/api/emoji?q=开心").json()["count"] >= 1
        assert client.patch(f"/api/emoji/{emoji_id}", json={"description": "轻轻挥手", "tags": ["挥手"], "emotion": "happy", "intensity": .4, "enabled": False}).json()["status"] == "updated"
        assert client.get("/api/emoji?enabled=false").json()["items"][0]["id"] == emoji_id
        assert client.delete(f"/api/emoji/{emoji_id}").json()["status"] == "deleted"


def test_emoji_cabinet_assets_and_routes_are_present():
    root = Path(__file__).parents[2]
    page = (root / "src/zhaoxi/web/static/engineering.html").read_text(encoding="utf-8")
    script = (root / "src/zhaoxi/web/static/emoji-cabinet.js").read_text(encoding="utf-8")
    assert 'id="emojiCabinetPanel"' in page
    assert 'id="emojiPendingGrid"' in page
    assert 'id="emojiEditor"' in page
    for route in ("/api/emoji/pending", "/api/emoji/analyze", "/api/emoji/"):
        assert route in script
    assert "confirm(" in script


def test_debug_direct_send_is_stable_for_ten_runs_and_acknowledged(tmp_path):
    root = tmp_path / 'emoji'
    (root / 'images').mkdir(parents=True)
    (root / 'images' / 'wave.png').write_bytes(b'image')
    (root / 'emoji_registry.json').write_text(json.dumps([{
        'id': 'wave', 'file': 'images/wave.png', 'description': 'friendly wave',
        'tags': ['wave'], 'emotion': 'happy', 'intensity': .6, 'enabled': True,
    }]), encoding='utf-8')
    service = EmojiService(root / 'emoji_registry.json')
    registry = ToolRegistry()
    store = SQLiteSessionStore(tmp_path / 'sessions.db')
    conversation = Conversation()
    agent = ZhaoxiAgent(provider=FakeProvider([]), registry=registry,
                        context_builder=ContextBuilder("Test"), conversation=conversation)
    agent.emoji_service = service
    agent.emoji_manager = EmojiManager(service)
    agent.session_store = store
    agent.session_record = Session(id='local', conversation=conversation)
    agent.last_emoji_trace = {}
    agent.proactive = None
    agent.proactive_scheduler = None
    agent.proactive_state = None
    agent.planner = None
    agent.workflow = None
    agent.tool_executor = SimpleNamespace(gateway=SimpleNamespace(store=SimpleNamespace(pending={})))

    with TestClient(create_app(agent=agent)) as client:
        message_ids = []
        for _ in range(10):
            response = client.post('/api/debug/emoji/direct')
            assert response.status_code == 200
            payload = response.json()
            assert payload['trace']['persisted'] is True
            assert payload['trace']['gateway_emitted'] is True
            assert payload['messages'][0]['type'] == 'image'
            assert payload['messages'][0]['source'] == 'emoji'
            message_ids.append(payload['messages'][0]['message_id'])
        assert len(set(message_ids)) == 10

        trace_id = payload['trace_id']
        acknowledged = client.post('/api/debug/emoji/trace/ack', json={
            'trace_id': trace_id, 'received': True, 'rendered': True,
        }).json()
        assert acknowledged['frontend_received'] is True
        assert acknowledged['frontend_rendered'] is True
        assert client.get('/api/debug/emoji/trace').json()['trace_id'] == trace_id

    restored = store.get_sync('local')
    assert restored is not None
    restored_images = [message for message in restored.conversation.messages if message.source == 'emoji']
    assert [message.message_id for message in restored_images] == message_ids
