import asyncio
from datetime import UTC, datetime
from types import MethodType
from zhaoxi.cognitive_stream import CognitiveEvent, CognitiveEventType, ExperienceStream
from zhaoxi.current_cognition.maintainer import CurrentCognitionMaintainer


def test_current_cognition_reads_only_owner_events(tmp_path):
    stream = ExperienceStream(tmp_path / 'experience.db')
    now = datetime.now(UTC)
    third = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source='qq',
        actor_role='THIRD_PARTY', trust_level='LOW', content='暗苟已经拿 offer 了',
        occurred_at=now, received_at=now)
    owner = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source='qq',
        actor_role='OWNER', trust_level='TRUSTED', content='今晚就修 v1.3.2',
        occurred_at=now, received_at=now)
    stream.append(third)
    stream.append(owner)
    class Service:
        def state(self):
            return type('State', (), {'last_processed_message_id': None})()
    maintainer = CurrentCognitionMaintainer(Service(), None)
    seen = []
    async def capture(self, messages, **kwargs):
        seen.extend(messages)
        return 'UPDATE'
    maintainer.maintain = MethodType(capture, maintainer)
    assert asyncio.run(maintainer.maintain_events(stream)) == 'UPDATE'
    assert [item.content for item in seen] == ['今晚就修 v1.3.2']
