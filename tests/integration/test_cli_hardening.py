from types import SimpleNamespace

import pytest

from zhaoxi import cli
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.tools.registry import ToolRegistry


class FailingAgent:
    async def run_natural(self, text):
        raise RuntimeError("internal detail must not reach user")


async def test_unexpected_turn_error_does_not_exit_or_print_traceback(monkeypatch, capsys):
    answers = iter(["触发一次异常", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli, "Settings", lambda: SimpleNamespace(log_level="INFO"))
    monkeypatch.setattr(cli, "configure_logging", lambda level: None)
    monkeypatch.setattr(cli, "build_agent", lambda settings: FailingAgent())

    await cli.interactive()

    output = capsys.readouterr().out
    assert "追踪号" in output
    assert "再见" in output
    assert "Traceback" not in output
    assert "internal detail" not in output


class OfflineProvider(ModelProvider):
    async def generate(self, messages, tools=None, **kwargs):
        raise ProviderError("private network detail")


async def test_provider_failure_is_natural_and_info_log_has_no_traceback(caplog):
    agent = ZhaoxiAgent(
        provider=OfflineProvider(),
        registry=ToolRegistry(),
        context_builder=ContextBuilder("你是朝汐。"),
    )
    with pytest.raises(AgentLoopError, match="模型服务当前不可访问"):
        await agent.run("查点东西")
    records = [record for record in caplog.records if "provider error" in record.message]
    assert records and all(record.exc_info is None for record in records)
