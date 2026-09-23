from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from zhaoxi.agenda import AgendaService, AgendaType, SQLiteAgendaStore
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.short_term_memory import ShortTermMemoryService, ShortTermMemoryStore
from zhaoxi.short_term_memory.models import Category, Source
from zhaoxi.short_term_memory.service import ItemProposal, ShortTermMemoryPatch


def test_short_term_memory_is_always_injected_alongside_recent_messages(tmp_path):
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    agenda = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"))
    stm = ShortTermMemoryService(ShortTermMemoryStore(tmp_path / "stm.db"))
    agenda.add(type=AgendaType.FOCUS, title="完成 v1.2.6")
    stm.apply(ShortTermMemoryPatch(action="UPDATE", add=[ItemProposal(
        category=Category.ACTIVE_THREAD, content="近期持续开发朝汐", source=Source.USER,
        source_message_id="u1")]), source_by_id={"u1": "user"}, last_message_id="u1")
    builder = ContextBuilder("人格", agenda_service=agenda, short_term_memory_service=stm)
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" in system and "完成 v1.2.6" in system
    assert "[Short-Term Memory]" in system and "近期持续开发朝汐" in system
    builder.agenda_context_enabled = False
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" not in system and "[Short-Term Memory]" in system


def test_recent_context_failure_is_non_fatal():
    class Broken:
        def snapshot(self, **kwargs):
            raise RuntimeError("broken")
    builder = ContextBuilder("人格", agenda_service=Broken(), short_term_memory_service=Broken())
    messages = builder.build(Conversation())
    assert messages[0].content.startswith("人格")
    assert builder.last_recent_context["errors"] == {"agenda": "RuntimeError", "short_term_memory": "RuntimeError"}


def test_agenda_and_stm_precede_retrieved_long_term_memory(tmp_path):
    class Retrieval:
        def format(self, _items):
            return "长期背景"

    agenda = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"))
    stm = ShortTermMemoryService(ShortTermMemoryStore(tmp_path / "stm.db"))
    builder = ContextBuilder("人格", agenda_service=agenda, short_term_memory_service=stm,
                             memory_retriever=Retrieval())
    system = builder.build(Conversation(), memories=[object()])[0].content
    assert system.index("[Agenda]") < system.index("[Short-Term Memory]") < system.index("长期记忆：")


def test_debug_ui_exposes_agenda_switch_and_stm_snapshot():
    page = (Path(__file__).parents[2] / "src/zhaoxi/web/static/index.html").read_text(encoding="utf-8")
    assert "agendaContextToggle" in page
    assert "workingNotesContextToggle" not in page
    assert "Short-Term Memory Debug" in page
    assert "/api/debug/recent-context" in page
