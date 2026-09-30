"""Opt-in real-provider acceptance on synthetic conversations and disposable files.

Run: python scripts/smoke_fast_gate_v2.py --output report.json
Only configured model credentials/settings are read from the live installation.
"""
from __future__ import annotations
import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import json
import gc
from pathlib import Path
import tempfile

from pydantic import BaseModel, Field
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.config import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.current_cognition.models import CurrentCognitionState, CognitionThread
from zhaoxi.current_cognition.service import CurrentCognitionService
from zhaoxi.current_cognition.store import CurrentCognitionStore
from zhaoxi.observability import action_trace_scope
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.reliability import CorrelationContext, correlation_scope
from zhaoxi.reliability.retry import provider_budget_scope
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


class ReadInput(BaseModel):
    query: str = Field(default="", description="要读取的合成文档或历史记录")


class FixtureRead(Tool):
    name = "archive_read"
    group = "archive"
    description = "读取验收夹具中的计划.md、未来开发计划9.21版和亚信面试历史；均为合成资料。"
    aliases = ("书馆", "未来开发计划", "亚信", "面试历史", "计划.md")
    input_model = ReadInput
    def __init__(self, root):
        self.root = root
    async def execute(self, arguments):
        return ToolResult(success=True, content=(self.root / "计划.md").read_text(encoding="utf-8"))


class WriteInput(BaseModel):
    content: str = Field(min_length=1, description="要写入隔离 bug 记录文件的正文")


class FixtureWrite(Tool):
    name = "fixture_bug_record"
    group = "filesystem_write"
    description = "把 bug 记录保存到隔离验收目录的 bug.md；不接收路径，不能修改真实资料。"
    aliases = ("bug记录", "记录文件", "记录", "补一份", "保存")
    input_model = WriteInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False
    def __init__(self, root):
        self.root = root
    async def execute(self, arguments):
        target = self.root / "bug.md"
        target.write_text(arguments.content, encoding="utf-8")
        return ToolResult(success=True, content="隔离验收 bug.md 已保存。",
                          data={"exists": target.is_file(), "chars": len(arguments.content)})


# 25 independent turns, with explicit prior context where needed.
CASES = [
    ("小金毛？", "FAST_CONFIDENT", ""),
    ("你好", "FAST_CONFIDENT", ""),
    ("朝汐？", "FAST_CONFIDENT", ""),
    ("哈哈", "FAST_CONFIDENT", ""),
    ("晚安", "FAST_CONFIDENT", ""),
    ("我今天有点累", "FAST_CONFIDENT", ""),
    ("最近秋招真没啥结果", "FAST_CONFIDENT", ""),
    ("LifeHUD 这个界面看着有点怪", "FAST_CONFIDENT", ""),
    ("这个改版看起来舒服多了", "FAST_CONFIDENT", ""),
    ("确实舒服多了", "FAST_CONFIDENT", "Fast Chat 现在终于快了"),
    ("我这几天还是在弄朝汐", "FAST_CONFIDENT", ""),
    ("今天开发挺开心的", "FAST_CONFIDENT", ""),
    ("书馆里未来开发计划9.21版，自己去看", "HEAVY_CONFIDENT", ""),
    ("去补一份吧，把这个 bug 记录起来，我等下处理", "HEAVY_CONFIDENT", "图片历史丢失，缺一份 bug 记录文件"),
    ("读取计划.md", "HEAVY_CONFIDENT", ""),
    ("记录一下这个 bug", "HEAVY_CONFIDENT", "图片历史输入为空"),
    ("亚信上次具体问了我哪些题？", "HEAVY_CONFIDENT", ""),
    ("现在几点？", "HEAVY_CONFIDENT", ""),
    ("帮我算一下 23 乘 17", "HEAVY_CONFIDENT", ""),
    ("之前那个你觉得怎么样？", "AMBIGUOUS", ""),
    ("那个呢？", "AMBIGUOUS", ""),
    ("LifeHUD", "AMBIGUOUS", ""),
    ("冰柜里的第八个", "AMBIGUOUS", ""),
    ("我想了解那个文件", "AMBIGUOUS", ""),
    ("春天会有新结果吧", "AMBIGUOUS", ""),
]


async def main(output: Path):
    settings = Settings()
    # Keep this acceptance bounded; preserve configured provider/model/thinking.
    settings.max_tokens = 1024
    provider = build_model_runtime(settings)
    rows = []
    report = {"at": datetime.now(UTC).isoformat(), "model": settings.model_name,
              "mode": "real_provider_isolated_runtime", "case_count": len(CASES), "cases": rows}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zhaoxi-gate-v2-") as temp:
        root = Path(temp)
        (root / "计划.md").write_text("合成验收资料：未来开发计划9.21版包含 Gate 路由、工具边界和回归测试。亚信上次面试题为：测试夹具题 A、测试夹具题 B。", encoding="utf-8")
        now = datetime.now(UTC)
        store = CurrentCognitionStore(root / "cognition.db")
        store.save(CurrentCognitionState(overview="秋招还没什么结果，朝汐开发仍是近期主线。", updated_at=now,
            threads=[CognitionThread(key="job_search", title="秋招", summary="秋招缺少实质性结果。",
                first_seen_at=now, last_updated_at=now, last_evidence_at=now)]))
        cognition = CurrentCognitionService(store)
        semaphore = asyncio.Semaphore(2)
        async def run_case(index, case):
            async with semaphore:
                message, expected, recent = case
                case_root = root / str(index)
                case_root.mkdir()
                registry = ToolRegistry()
                for tool in [*create_builtin_tools(), FixtureRead(root), FixtureWrite(case_root)]:
                    registry.register(tool)
                agent = ZhaoxiAgent(provider=provider, registry=registry, max_steps=4,
                    timeout_seconds=settings.request_timeout_seconds,
                    context_builder=ContextBuilder("你是朝汐，用中文简短自然回应。当前资料与工具均属于隔离验收夹具。",
                                                   current_cognition_service=cognition))
                agent.cognitive = CognitiveCoordinator(agent=agent,
                    router=CognitiveRouter(provider, tool_catalog=registry.manifest()),
                    fast_gate=FastDialogueGate(settings.fast_gate))
                if recent:
                    agent.conversation.add_assistant(recent)
                row = {"id": index + 1, "message": message, "expected_gate": expected}
                with correlation_scope(CorrelationContext(trace_id=f"gate-smoke-{index}", request_id=f"gate-smoke-{index}")), action_trace_scope() as trace, provider_budget_scope(8, max_total_tokens=30000):
                    try:
                        result = await agent.run_natural(message)
                        row.update(route=result.route.value, response=result.content,
                                   permission_pending=bool(result.permission_confirmation))
                    except Exception as exc:
                        row["error_type"] = type(exc).__name__
                        row["error_code"] = getattr(exc, "code", None)
                    metrics = trace.metrics()
                    row["metrics"] = {k:metrics.get(k) for k in ("fast_gate_version", "fast_gate_decision", "fast_gate_reason", "fast_gate_signals", "fast_score", "heavy_score", "fast_positive_evidence", "heavy_evidence", "router_required", "router_override", "router_final_lane", "router_to_fast_count", "runtime_lane", "foreground_llm_calls", "router_llm_calls", "tool_rounds", "escalation_reason")}
                    row["tool_events"] = [{"type":e.event_type, "tool":e.tool_name} for e in trace.events if e.event_type in {"tool_call_succeeded", "tool_call_failed"}]
                row["bug_file_exists"] = (case_root / "bug.md").is_file()
                row["gate_ok"] = row["metrics"]["fast_gate_decision"] == expected
                row["call_contract_ok"] = (expected != "FAST_CONFIDENT" or (row["metrics"]["router_llm_calls"] == 0 and row["metrics"]["foreground_llm_calls"] == 1 and row.get("route") == "fast_chat"))
                row["heavy_route_ok"] = expected != "HEAVY_CONFIDENT" or row.get("route") not in {None, "fast_chat"}
                rows.append(row)
                rows.sort(key=lambda r:r["id"])
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({"id":row["id"], "gate":row["metrics"]["fast_gate_decision"], "route":row.get("route"), "calls":row["metrics"]["foreground_llm_calls"], "error":row.get("error_type")}, ensure_ascii=False), flush=True)
        try:
            await asyncio.gather(*(run_case(i, case) for i, case in enumerate(CASES)))
        finally:
            gc.collect()
    report["summary"] = {"gate_counts": dict(Counter(r["metrics"]["fast_gate_decision"] for r in rows)),
        "errors": sum("error_type" in r for r in rows),
        "gate_failures": sum(not r["gate_ok"] for r in rows),
        "call_contract_failures": sum(not r["call_contract_ok"] for r in rows),
        "heavy_route_failures": sum(not r["heavy_route_ok"] for r in rows),
        "router_to_fast_count": sum(r["metrics"]["router_to_fast_count"] or 0 for r in rows)}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return int(any(report["summary"][k] for k in ("errors", "gate_failures", "call_contract_failures", "heavy_route_failures")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.output)))
