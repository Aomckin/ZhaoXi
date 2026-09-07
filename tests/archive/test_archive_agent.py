from conftest import FakeProvider

from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.cli import main


def test_archive_cli_status_does_not_require_model_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZHAOXI_MODEL_API_KEY", "")
    monkeypatch.setenv("ZHAOXI_MODEL_NAME", "")
    monkeypatch.setenv("ZHAOXI_ARCHIVE_DIRECTORY", str(tmp_path / "archive"))
    monkeypatch.setenv("ZHAOXI_ARCHIVE_DB_PATH", str(tmp_path / "archive.db"))
    monkeypatch.setattr("sys.argv", ["zhaoxi", "--archive-status"])
    main()
    output = capsys.readouterr().out
    assert '"enabled": true' in output
    assert '"documents": 0' in output


def test_archive_factual_questions_force_a_real_tool_route():
    router = CognitiveRouter(FakeProvider([]), archive_enabled=True)
    for question in (
        "朝汐，你为什么怕黑？",
        "向日葵发卡是谁送给你的？",
        "我具体哪一天把向日葵发卡送给你的？",
    ):
        decision = router._fallback(question)
        assert decision.route is CognitiveRoute.TOOL
        assert decision.requires_tool_call
    assert router._fallback("朝汐，早上好").route is CognitiveRoute.DIRECT


def test_system_context_separates_archive_memory_and_unknown_facts():
    system = ContextBuilder("你是朝汐。正在使用 archive_search 字样也不代表检索结果。").build(Conversation())[0].content
    assert "canonical Archive" in system
    assert "不等同于长期记忆" in system
    assert "没有记录" in system
    assert "多个 canonical 冲突" in system
