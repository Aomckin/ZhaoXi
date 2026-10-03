"""Live model acceptance with synthetic context; no production data or tools."""
import asyncio
import json
import sys
import time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests/decision"))
from test_decision_awareness import make_agent, cognition, agenda
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.config.settings import Settings
from zhaoxi.models.base import ModelProvider
from zhaoxi.personality.loader import PersonalityLoader, ExpressionLoader
from zhaoxi.memory.models import MemoryRecord, MemorySearchResult
from zhaoxi.reliability.retry import provider_budget_scope

class Counted(ModelProvider):
    def __init__(self, provider):
        self.provider, self.calls, self.last_awareness = provider, 0, None
    async def generate(self, messages, tools=None, **kwargs):
        self.calls += 1
        response = await self.provider.generate(messages, tools, **kwargs)
        if not response.tool_calls:
            try:
                self.last_awareness = json.loads(response.content or '{}').get('awareness')
            except ValueError:
                self.last_awareness = None
        return response

async def run():
    settings = Settings()
    settings.retry_max_attempts = 2
    settings.request_timeout_seconds = 45
    cases = [
        ("menu", "菜单有辣椒炒肉、番茄鸡蛋、牛肉面，这几个吃啥？", ["PICK"]),
        ("cola", "无糖可乐买几瓶？", ["PICK"]),
        ("snack", "这包十块钱的薯片买不买？", ["PICK","ADVISE"]),
        ("afternoon", "下午打舞萌还是继续项目？", ["ADVISE"]),
        ("activity", "今天晚上的普通社团活动去不去？", ["ADVISE"]),
        ("shopping", "两根一块钱的笔，黑壳和白壳功能一样，这俩选哪个？", ["PICK"]),
        ("career", "这个实习岗位让我连续两周晚上没空写项目，要不要继续面？", ["ADVISE","FRAME"]),
        ("offer", "A Offer 月薪20k但每周加班20小时，B月薪16k准点下班，两个正式Offer你直接替我决定。", ["FRAME"]),
        ("implicit", "我在货架前站半天了。黑壳和白壳的笔功能、价格都一样，都是一块钱。", ["PICK"]),
        ("reflection", "我为什么最近总在想要不要出门？", ["NONE"]),
    ]
    if len(sys.argv) > 1:
        cases = [case for case in cases if case[0] in sys.argv[1:]]
    rows = []
    run_id = uuid4().hex
    for name, question, expected in cases:
        base = ROOT / ".zhaoxi/v146-live-fixtures" / run_id / name
        agent, _ = make_agent(base, [], fast=True)
        agent.context_builder.personality_prompt = PersonalityLoader.load_prompt()
        agent.context_builder.expression_prompt = ExpressionLoader.load_prompt()
        agent.context_builder.current_cognition_service = cognition()
        agent.decision_awareness.cognition = cognition()
        agent.decision_awareness.agenda = agenda()
        memory = MemoryRecord(id="synthetic-project-time",kind="semantic",source_type="user",
            content="我希望工作之外每周有稳定的时间开发朝汐项目。",normalized_content="project time",
            source="synthetic_acceptance",confidence=1)
        agent.decision_awareness.memory = SimpleNamespace(retrieve=AsyncMock(
            return_value=[MemorySearchResult(record=memory,score=1)]))
        class OfferFacts:
            async def retrieve(self, query, *, limit):
                return [{"ref":"offer:synthetic","content":"A正式合同：20k/月，每周加班20小时；B正式合同：16k/月，准点下班。均在相同城市，录用期限明天。"}][:limit]
        agent.decision_awareness.register_context_provider("offer_facts",OfferFacts())
        counted = Counted(build_model_runtime(settings))
        agent.provider = counted
        start = time.perf_counter()
        try:
            with provider_budget_scope(6):
                response = await agent.run_natural(question)
            latest = agent.decision_awareness.diagnostics()["latest"]
            mode = latest["mode"] if latest else "NONE"
            row = {"case":name,"expected_modes":expected,"mode":mode,
                "model_calls":counted.calls,"elapsed_ms":round((time.perf_counter()-start)*1000),
                "context_sources":latest["context_sources"] if latest else [],
                "reply":response.content,"expected_mode_passed":mode in expected,
                "metadata_private":"<decision-awareness" not in response.content, "raw_awareness":counted.last_awareness,
                "one_call_pick_passed": mode != "PICK" or counted.calls == 1}
        except Exception as exc:
            row = {"case":name,"error":type(exc).__name__,"error_code":getattr(exc,"code",None),"cause":type(exc.__cause__).__name__,"model_calls":counted.calls}
        rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
        if row.get("error"):
            break
    result = {"environment":"configured real model, synthetic contexts, isolated choice history",
              "production_tools":False,"isolated_run_id":run_id,"call_count_unit":"generate calls; provider transport retries are not counted separately","cases":rows}
    destination = ROOT / "docs/v1.4.x/evidence/decision_v146_live_final_acceptance.json"
    if destination.exists():
        previous = json.loads(destination.read_text(encoding="utf-8"))
        result["prior_attempts"] = [*previous.get("prior_attempts", []), {"cases":previous["cases"]}]
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if all(row.get("expected_mode_passed") and row.get("metadata_private") for row in rows) else 1

if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
