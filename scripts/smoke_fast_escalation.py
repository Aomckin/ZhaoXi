"""Opt-in real-model FAST capability upgrade checks on disposable fixtures."""
import argparse
import asyncio
import gc
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from smoke_fast_gate_v2 import FixtureRead
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.config import Settings
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.decision.service import DecisionService
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import UnifiedMessage, InterfaceChannel
from zhaoxi.memory.models import MemoryRecord, MemorySearchResult
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.tools.registry import ToolRegistry


async def main(output):
    settings = Settings()
    settings.max_tokens = 1024
    provider = build_model_runtime(settings)
    rows = []
    report = {"at":datetime.now(UTC).isoformat(), "model":settings.model_name,
              "mode":"real_provider_isolated_fast_escalation", "cases":rows}
    with tempfile.TemporaryDirectory(prefix="zhaoxi-fast-escalation-") as temp:
        root = Path(temp)
        (root / "计划.md").write_text("合成验收计划：蓝色方案先实现小范围回归，然后确认工具权限边界。", encoding="utf-8")
        for kind, message in [
            ("tool", "请读取验收夹具中的计划.md，告诉我它说了什么。"),
            ("recall", "我上次说那辆测试车是什么颜色来着？请核对真实的长期记忆。"),
            ("decision", "我有两个正式 Offer，一个高薪高压，一个低薪但方向更喜欢，应该选哪个？")]:
            registry = ToolRegistry()
            registry.register(FixtureRead(root))
            agent = ZhaoxiAgent(provider=provider, registry=registry,
                context_builder=ContextBuilder("你是朝汐，用中文简短回应；当前全部资料均为隔离验收夹具。"))
            agent.cognitive = CognitiveCoordinator(agent=agent,
                router=CognitiveRouter(provider, tool_catalog=registry.manifest()), fast_gate=FastDialogueGate())
            # Force admission to exercise capability discovery, rather than Gate rejection.
            agent.cognitive.force_fast_chat = True
            record = MemoryRecord(kind="episodic", content="上次验收提到那辆测试车为蓝色。",
                normalized_content="test vehicle blue", source_type="user", source="synthetic", confidence=1)
            service = SimpleNamespace(search=AsyncMock(return_value=[MemorySearchResult(record=record, score=1)]))
            agent.context_builder.memory_retriever = MemoryRetriever(service)
            agent.decision_service = DecisionService(provider,
                rule_directory=Path("data/decisions/rules"), data_directory=root / kind)
            gateway = InterfaceGateway(agent)
            events = []
            gateway.event_sink = events.append
            row = {"capability":kind, "input":message}
            try:
                result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content=message))
                row["response"] = result.content
                metrics = agent.last_action_trace["runtime_metrics"]
                row["metrics"] = {key:metrics.get(key) for key in (
                    "runtime_lane","route_source","route","fast_escalation_count","fast_escalation_kind",
                    "escalation_reason","foreground_llm_calls","router_llm_calls","memory_search_count","decision_used","tool_rounds")}
                text = json.dumps([events,result.model_dump(mode="json"),[m.model_dump(mode="json") for m in agent.conversation.messages]], ensure_ascii=False)
                row["no_directive_leak"] = "[escalate:" not in text and "【escalate:" not in text
                row["passed"] = (row["no_directive_leak"] and metrics["fast_escalation_count"] == 1
                    and metrics["fast_escalation_kind"] == kind and metrics["runtime_lane"] == "standard"
                    and metrics["router_llm_calls"] == 0)
            except Exception as exc:
                row.update(error_type=type(exc).__name__,error_code=getattr(exc,"code",None),passed=False)
            rows.append(row)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps({"capability":kind,"passed":row["passed"],"metrics":row.get("metrics")},ensure_ascii=False),flush=True)
        gc.collect()
    report["passed"] = all(row["passed"] for row in rows)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return int(not report["passed"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    raise SystemExit(asyncio.run(main(parser.parse_args().output)))
