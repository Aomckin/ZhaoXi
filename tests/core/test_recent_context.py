from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zhaoxi.agenda import AgendaService, AgendaType, SQLiteAgendaStore
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.working_notes import (
    NoteConfidence, NoteSource, NoteType, SQLiteWorkingNotesStore, WorkingNotesService,
)


def test_recent_snapshots_are_always_injected_and_independently_disabled(tmp_path):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    agenda = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"))
    notes = WorkingNotesService(SQLiteWorkingNotesStore(tmp_path / "notes.db"))
    agenda.add(type=AgendaType.FOCUS, title="完成 v1.2.6")
    notes.add(topic="开发", type=NoteType.WORKING, content="接 Context Builder",
              source=NoteSource.ASSISTANT, confidence=NoteConfidence.WORKING)
    builder = ContextBuilder("人格", agenda_service=agenda, working_notes_service=notes)
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" in system and "完成 v1.2.6" in system
    assert "[Zhaoxi Working Notes]" in system and "接 Context Builder" in system
    builder.agenda_context_enabled = False
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" not in system and "[Zhaoxi Working Notes]" in system


def test_recent_context_failure_is_non_fatal():
    class Broken:
        def snapshot(self, **kwargs):
            raise RuntimeError("broken")
    builder = ContextBuilder("人格", agenda_service=Broken(), working_notes_service=Broken())
    messages = builder.build(Conversation())
    assert messages[0].content.startswith("人格")
    assert builder.last_recent_context["errors"] == {"agenda": "RuntimeError", "working_notes": "RuntimeError"}


def test_debug_ui_exposes_recent_context_switches_and_snapshot():
    page = (Path(__file__).parents[2] / "src/zhaoxi/web/static/index.html").read_text(encoding="utf-8")
    assert "agendaContextToggle" in page
    assert "workingNotesContextToggle" in page
    assert "/api/debug/recent-context" in page
