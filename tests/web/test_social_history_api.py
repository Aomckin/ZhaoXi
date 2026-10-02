from datetime import UTC, datetime
from fastapi.testclient import TestClient
from test_web import FakeAgent
from zhaoxi.config.settings import Settings
from zhaoxi.cognitive_stream import ExperienceStream
from zhaoxi.perception.models import Observation, ObservationStatus
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.web.app import create_app


def test_search_api_uses_legacy_store_auth_and_validates_time(tmp_path):
    stream=ExperienceStream(tmp_path/"events.db")
    store=PerceptionStore(tmp_path/"perception.db",media_directory=stream.media.root)
    item=Observation(source="qq",source_plugin="napcat",source_kind="group_message",conversation_kind="group",
        conversation_id="A",actor_id="8",actor_role="EXTERNAL",content="历史关键词",raw_ref="qq:group:A:1",
        occurred_at=datetime(2026,10,2,tzinfo=UTC))
    store.insert(item,ObservationStatus.PROCESSED)
    agent=FakeAgent();agent.experience_stream=stream
    settings=Settings(_env_file=None,perception_enabled=False,perception_db_path=str(store.path))
    app=create_app(settings=settings,agent=agent,api_token="history-test")
    params={"query":"关键词","group_id":"A","since":"2026-10-02T08:00:00+08:00"}
    with TestClient(app) as client:
        headers={"X-Zhaoxi-Token":"history-test"}
        assert client.get("/api/debug/cognitive-stream/social-trace",params=params).status_code==401
        result=client.get("/api/debug/cognitive-stream/social-trace",params=params,headers=headers)
        assert result.status_code==200
        assert result.json()["records"][0]["reference"]==item.raw_ref
        assert result.json()["records"][0]["evidence_store"]=="perception"
        for bad in ({"query":"关键词","since":"2026-10-02T00:00:00"},
                    {"query":"关键词","reference":item.raw_ref}, {}):
            assert client.get("/api/debug/cognitive-stream/social-trace",params=bad,headers=headers).status_code==422
        result=client.get("/api/debug/cognitive-stream/social-trace",params={"reference":item.raw_ref},headers=headers)
        assert result.status_code==200 and result.json()["records"][0]["content"]==item.content
