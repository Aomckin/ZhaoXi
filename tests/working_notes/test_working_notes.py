from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from zhaoxi.working_notes import (
    NoteConfidence, NoteSource, NoteStatus, NoteType,
    SQLiteWorkingNotesStore, WorkingNotesService,
)


ZONE = ZoneInfo("Asia/Shanghai")


def service(tmp_path, now, **kwargs):
    return WorkingNotesService(SQLiteWorkingNotesStore(tmp_path / "notes.db"), clock=lambda: now, **kwargs)


def test_crud_expiration_and_cross_restart(tmp_path):
    now = datetime(2026, 9, 22, 10, tzinfo=ZONE)
    notes = service(tmp_path, now)
    note, created = notes.add(topic="v1.2.6", type=NoteType.WORKING, content="正在接 Agenda",
                              source=NoteSource.USER, confidence=NoteConfidence.CONFIRMED)
    assert created
    notes.update(note.id, content="正在接 Context Builder")
    expiring, _ = notes.add(topic="临时", type=NoteType.TEMP, content="短期信息",
                            source=NoteSource.SYSTEM, confidence=NoteConfidence.WORKING,
                            expires_at=now + timedelta(minutes=1))
    restored = service(tmp_path, now + timedelta(minutes=2))
    assert restored.require(note.id).content.endswith("Builder")
    assert restored.list("expired")[0].id == expiring.id
    assert restored.resolve(note.id).status is NoteStatus.RESOLVED
    restored.delete(note.id)
    assert all(item.id != note.id for item in restored.list("all_recent"))


def test_assistant_hypothesis_never_formats_as_confirmed(tmp_path):
    now = datetime(2026, 9, 22, 10, tzinfo=ZONE)
    notes = service(tmp_path, now)
    note, _ = notes.add(topic="存储", type=NoteType.HYPOTHESIS, content="可能使用 SQLite",
                        source=NoteSource.ASSISTANT, confidence=NoteConfidence.CONFIRMED)
    assert note.confidence is NoteConfidence.TENTATIVE
    snapshot = notes.snapshot()
    assert "Hypotheses:" in snapshot and "assistant/tentative" in snapshot
    assert "Confirmed:" not in snapshot


def test_capacity_and_topic_deduplication(tmp_path):
    now = datetime(2026, 9, 22, 10, tzinfo=ZONE)
    notes = service(tmp_path, now, max_active_per_type=1)
    first, _ = notes.add(topic="接入", type=NoteType.TODO, content="接 Context",
                         source=NoteSource.ASSISTANT, confidence=NoteConfidence.WORKING)
    updated, created = notes.add(topic="接入", type=NoteType.TODO, content="接 Context Builder",
                                 source=NoteSource.ASSISTANT, confidence=NoteConfidence.WORKING)
    assert not created and updated.id == first.id
    second, _ = notes.add(topic="测试", type=NoteType.TODO, content="补测试",
                          source=NoteSource.ASSISTANT, confidence=NoteConfidence.WORKING)
    assert notes.require(first.id).status is NoteStatus.EXPIRED
    assert notes.list("active") == [second]
