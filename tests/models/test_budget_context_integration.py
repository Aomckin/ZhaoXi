import json

import httpx
import pytest

from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.planner.models import GoalStatus
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.reliability.retry import BudgetPolicy, provider_budget_scope
from zhaoxi.tools.builtin.calculator import CalculatorTool
from zhaoxi.tools.builtin.echo import EchoTool
from zhaoxi.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_exact_provider_payload_is_measured_and_finalization_omits_tool_schema():
    payloads = []
    steps = [
        ("create_plan", {"steps": ["计算", "记录"]}),
        ("calculator", {"expression": "17*23"}),
        ("echo", {"message": "计算完成391"}),
    ]

    def handle(request):
        payloads.append(json.loads(request.content))
        index = len(payloads) - 1
        if index < len(steps):
            name, arguments = steps[index]
            message = {"content": "", "tool_calls": [{
                "id": f"call-{index}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }]}
        else:
            message = {"content": "两项操作已完成。"}
        return httpx.Response(200, json={"id": f"mock-{index}", "model": "mock",
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(EchoTool())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        raw = OpenAICompatibleProvider(base_url="https://mock.invalid/v1", api_key="test", model="mock", client=client)
        provider = ResilientProvider([raw], max_calls=8, max_total_tokens=10000)
        planner = PlannerRuntime(provider=provider, registry=registry,
                                 context_builder=ContextBuilder("你是朝汐。"), max_steps=6)
        with provider_budget_scope(8, policy=BudgetPolicy(
            base_budget=450, extension_1_limit=0, extension_2_limit=0,
            hard_limit=450, finalization_reserve=125,
        )) as budget:
            response = await planner.run("计算 17*23，然后记录结果。")
    assert response.status is GoalStatus.COMPLETED
    assert len(payloads) == 4
    assert "tools" in payloads[0] and "tools" not in payloads[-1]
    assert len(budget.context_reports) == 4
    assert budget.context_reports[0]["estimated"]["tool_schema"] > 0
    assert budget.context_reports[-1]["estimated"]["tool_schema"] == 0
    assert budget.context_reports[-1]["estimated"]["tool_result"] > 0
    assert all(report["total_input_tokens"] == 100 for report in budget.context_reports)
    assert budget.reserve_entered is True
    assert budget.extension_count == 0
    assert budget.total_tokens == 440
