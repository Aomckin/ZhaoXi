from pathlib import Path

from zhaoxi.agenda import AgendaService, AgendaType, SQLiteAgendaStore
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.current_cognition import CurrentCognitionService, CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionPatch


def test_current_cognition_is_always_injected_alongside_recent_messages(tmp_path):
    agenda = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"))
    cognition = CurrentCognitionService(CurrentCognitionStore(tmp_path / "cognition.db"))
    agenda.add(type=AgendaType.FOCUS, title="完成 v1.2.6")
    cognition.apply(CurrentCognitionPatch(decision="UPDATE", reason_code="ongoing_mainline",
        evidence_message_ids=["u1"], narrative_patch=[{"from": "", "to": "近期持续开发朝汐。"}]),
        source_by_id={"u1": "user"}, evidence_by_id={"u1": "我近期持续开发朝汐"}, last_message_id="u1")
    builder = ContextBuilder("人格", agenda_service=agenda, current_cognition_service=cognition)
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" in system and "完成 v1.2.6" in system
    assert "[Current Cognition]" in system and "近期持续开发朝汐" in system
    builder.agenda_context_enabled = False
    system = builder.build(Conversation())[0].content
    assert "[Agenda]" not in system and "[Current Cognition]" in system


def test_recent_context_failure_is_non_fatal():
    class Broken:
        def snapshot(self, **kwargs):
            raise RuntimeError("broken")
    builder = ContextBuilder("人格", agenda_service=Broken(), current_cognition_service=Broken())
    messages = builder.build(Conversation())
    assert messages[0].content.startswith("人格")
    assert builder.last_recent_context["errors"] == {"agenda": "RuntimeError", "current_cognition": "RuntimeError"}


def test_agenda_and_cognition_precede_retrieved_long_term_memory(tmp_path):
    class Retrieval:
        def format(self, _items):
            return "长期背景"
    agenda = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"))
    cognition = CurrentCognitionService(CurrentCognitionStore(tmp_path / "cognition.db"))
    builder = ContextBuilder("人格", agenda_service=agenda, current_cognition_service=cognition,
                             memory_retriever=Retrieval())
    system = builder.build(Conversation(), memories=[object()])[0].content
    assert system.index("[Agenda]") < system.index("[Current Cognition]") < system.index("长期记忆：")


def test_debug_ui_keeps_existing_panel():
    page = (Path(__file__).parents[2] / "src/zhaoxi/web/static/index.html").read_text(encoding="utf-8")
    assert "agendaContextToggle" in page
    assert "Current Cognition Debug" in page
    assert "/api/debug/recent-context" in page
