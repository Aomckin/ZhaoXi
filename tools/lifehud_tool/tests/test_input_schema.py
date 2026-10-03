"""The model gets actionable fields and can recover from the observed diet failure."""

import json

import httpx
import pytest

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_exported_schema_explains_every_business_field_and_meal_semantics():
    parameters = LifeHudTool(None).schema()["function"]["parameters"]
    assert parameters["properties"]["operation"]["description"]
    branches = parameters["properties"]["arguments"]["anyOf"]
    for branch in branches:
        for name, schema in branch["properties"].items():
            assert schema.get("description"), (branch["title"], name)
    meal = next(branch for branch in branches if branch["title"] == "record.meal")["properties"]
    assert meal["type"]["enum"] == ["meal"]
    assert "具体吃了什么" in meal["description"]["description"]
    assert "不是记录正文" in meal["note"]["description"]
    assert "description" in meal["note"]["description"]
    assert (meal["satisfaction"]["minimum"], meal["satisfaction"]["maximum"]) == (1, 5)
    assert set(meal["mealType"]["enum"]) == {"BREAKFAST", "LUNCH", "DINNER", "SNACK", "OTHER"}


@pytest.mark.anyio
async def test_diet_failure_returns_a_working_meal_example_with_separate_note():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "meal-1", **json.loads(request.content)})
        return httpx.Response(200, json={"id": "meal-1", "saved": True})
    tool = LifeHudTool(LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler)))
    failed = await tool.run({"operation": "record", "arguments": {"type": "diet", "action": "create"}})
    assert not failed.success and requests == []
    assert "type='meal'" in failed.content
    corrected = failed.data["input_hint"]["example"]
    corrected["arguments"]["description"] = "老干妈蛋炒饭，吃了一半"
    corrected["arguments"]["note"] = "另一半还花了十一块"
    result = await tool.run(corrected)
    assert result.success
    body = json.loads(requests[0].content)
    assert body["description"] == "老干妈蛋炒饭，吃了一半"
    assert body["note"] == "另一半还花了十一块"
    assert body["satisfaction"] == 1
    assert body["time"] == "2026-09-29T18:25:00+08:00"
    assert [(request.method, request.url.path) for request in requests] == [
        ("POST", "/api/life/meals"), ("GET", "/api/life/meals/meal-1")]


@pytest.mark.anyio
@pytest.mark.parametrize("payload,field_name", [
    ({"note": "蛋炒饭"}, "description"),
    ({"description": "蛋炒饭", "rating": 3}, "rating"),
    ({"data": {"description": "蛋炒饭"}}, "data"),
])
async def test_misplaced_food_or_unknown_fields_fail_before_writing(payload, field_name):
    def handler(request):
        pytest.fail("invalid input must not write or upload anything")
    tool = LifeHudTool(LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler)))
    result = await tool.run({"operation": "record", "arguments": {"type": "meal", **payload}})
    assert not result.success and field_name in result.content
    guidance = result.data["input_hint"]["fields"]
    assert "description" in guidance and "note" in guidance and "satisfaction" in guidance
