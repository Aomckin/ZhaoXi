import pytest
import httpx

from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction
from zhaoxi.cognitive.memory_decision import MemoryDecision
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.memory.models import MemoryCreate, MemoryQuery, MemoryStatus
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def control(name, arguments):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments)])


def make_cognitive(provider, service):
    registry = ToolRegistry()
    for tool in create_builtin_tools(service):
        registry.register(tool)
    conversation = Conversation()
    context = ContextBuilder("你是朝汐。")
    planner = PlannerRuntime(
        provider=provider,
        registry=registry,
        context_builder=context,
        conversation=conversation,
    )
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=context,
        conversation=conversation,
        planner=planner,
    )
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        auto_memory=AutoMemory(provider, service),
    )
    return agent


@pytest.mark.asyncio
async def test_simple_tool_request_does_not_plan_or_create_memory(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "tool", "reason": "需要当前时间"}),
        control("current_time", {}),
        ModelResponse(content="现在是测试时间。"),
        control("decide_memory", {"action": "ignore", "reason": "瞬时工具结果"}),
    ])
    agent = make_cognitive(provider, service)
    response = await agent.run_natural("现在几点？")
    assert response.route == CognitiveRoute.TOOL
    assert response.memory_action == MemoryAction.IGNORE
    assert await agent.planner.store.list() == []
    assert await service.search(MemoryQuery()) == []


@pytest.mark.asyncio
async def test_stable_preference_is_created_automatically(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "direct", "reason": "普通表达"}),
        ModelResponse(content="听起来你更享受晚上的开发节奏。"),
        ModelResponse(content='{"action":"create","content":"用户更喜欢晚上开发，而不是刷算法","tags":["偏好","开发"],"confidence":0.9,"reason":"稳定偏好"}'),
    ])
    response = await make_cognitive(provider, service).run_natural("我发现晚上开发比刷算法舒服。")
    records = await service.search(MemoryQuery(text="晚上开发", limit=10))
    assert response.memory_action == MemoryAction.CREATE
    assert len(records) == 1
    assert "晚上开发" in records[0].record.content
    assert provider.tool_schemas[1] is None


@pytest.mark.asyncio
async def test_project_version_updates_existing_memory(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    old = (await service.remember(MemoryCreate(content="Zhaoxi 当前版本 v0.2"))).record
    provider = FakeProvider([
        control("route_cognition", {"route": "direct", "reason": "状态陈述"}),
        ModelResponse(content="v0.3 完成了，进展很明确。"),
        ModelResponse(content=__import__("json").dumps({
            "action": "update",
            "content": "Zhaoxi 当前版本 v0.3，Planner 已完成",
            "target_memory_id": old.id,
            "tags": ["zhaoxi", "版本"],
            "reason": "项目状态更新",
        }, ensure_ascii=False)),
    ])
    response = await make_cognitive(provider, service).run_natural("Zhaoxi v0.3 做完了。")
    active = await service.search(MemoryQuery(text="Zhaoxi 当前版本", limit=10))
    assert response.memory_action == MemoryAction.UPDATE
    assert len(active) == 1
    assert active[0].record.id == old.id
    assert "v0.3" in active[0].record.content


@pytest.mark.asyncio
async def test_complex_memory_audit_routes_to_planner_and_has_trace(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await service.remember(MemoryCreate(content="用户喜欢无糖咖啡"))
    provider = FakeProvider([
        control("route_cognition", {"route": "plan", "reason": "需要检查后整理"}),
        control("create_plan", {"steps": ["读取记忆", "分析重复与冲突"]}),
        control("search_memories", {"query": "", "limit": 20}),
        control("echo", {"message": "未发现重复或冲突"}),
        control("finish_task", {"summary": "检查完成，未发现重复或冲突。"}),
        control("decide_memory", {"action": "ignore", "reason": "一次性审计结果"}),
    ])
    agent = make_cognitive(provider, service)
    response = await agent.run_natural("帮我检查长期记忆里有没有重复或者冲突。")
    assert response.route == CognitiveRoute.PLAN
    assert response.goal_id
    assert any(
        event.event_type == "task_completed"
        for event in agent.planner.trace.events(response.goal_id)
    )


@pytest.mark.asyncio
async def test_user_denial_prevents_auto_memory(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "direct", "reason": "私密陈述"}),
        ModelResponse(content="明白，这件事不会进入长期记忆。"),
    ])
    response = await make_cognitive(provider, service).run_natural("不要记住下面这件事：XXX")
    assert response.memory_action == MemoryAction.IGNORE
    assert await service.search(MemoryQuery()) == []


@pytest.mark.asyncio
async def test_read_only_plan_blocks_mutating_tools(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    existing = (await service.remember(MemoryCreate(content="用户喜欢无糖咖啡"))).record
    provider = FakeProvider([
        control("route_cognition", {"route": "plan", "reason": "检查并整理"}),
        control("create_plan", {"steps": ["检查记忆", "整理结果"]}),
        control("update_memory", {"memory_id": existing.id, "content": "已被错误修改"}),
        control("search_memories", {"query": "咖啡"}),
        control("echo", {"message": "整理完成"}),
        control("finish_task", {"summary": "只读检查完成。"}),
        control("decide_memory", {"action": "ignore", "reason": "审计结果"}),
    ])
    response = await make_cognitive(provider, service).run_natural("帮我查一下记忆并整理，但不要修改。")
    assert response.route == CognitiveRoute.PLAN
    assert (await service.require(existing.id)).content == "用户喜欢无糖咖啡"


@pytest.mark.asyncio
async def test_explicit_remember_is_forced_when_decision_output_is_missing(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "tool", "reason": "明确记忆意图"}),
        ModelResponse(content="记住了。"),
        ModelResponse(content="invalid memory decision"),
    ])
    response = await make_cognitive(provider, service).run_natural("记住我喜欢无糖咖啡")
    records = await service.search(MemoryQuery(text="无糖咖啡"))
    assert response.memory_action == MemoryAction.CREATE
    assert len(records) == 1


@pytest.mark.asyncio
async def test_explicit_forget_uses_existing_tool_and_is_not_recreated(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    existing = (await service.remember(MemoryCreate(content="需要忘掉的事实"))).record
    provider = FakeProvider([
        control("route_cognition", {"route": "tool", "reason": "明确遗忘意图"}),
        control("forget_memory", {"memory_id": existing.id}),
        ModelResponse(content="已经忘掉了。"),
    ])
    response = await make_cognitive(provider, service).run_natural("忘掉这条记忆")
    assert response.memory_action == MemoryAction.IGNORE
    assert await service.search(MemoryQuery(text="需要忘掉的事实")) == []


@pytest.mark.asyncio
async def test_simple_request_guard_overrides_bad_plan_route(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "plan", "reason": "错误分类"}),
        control("current_time", {}),
        ModelResponse(content="现在是测试时间。"),
        control("decide_memory", {"action": "ignore", "reason": "瞬时结果"}),
    ])
    response = await make_cognitive(provider, service).run_natural("现在几点？")
    assert response.route == CognitiveRoute.TOOL


@pytest.mark.asyncio
async def test_merge_updates_in_place_and_conflict_preserves_history(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    original = (await service.remember(MemoryCreate(content="用户晚上喜欢开发"))).record
    auto = AutoMemory(FakeProvider([ModelResponse(content="unused")]), service)
    action = await auto.apply(MemoryDecision(
        action=MemoryAction.MERGE,
        target_memory_id=original.id,
        content="用户晚上喜欢开发，尤其偏好处理项目功能",
        tags=["开发偏好"],
    ))
    assert action == MemoryAction.MERGE
    assert "项目功能" in (await service.require(original.id)).content

    action = await auto.apply(MemoryDecision(
        action=MemoryAction.CONFLICT,
        target_memory_id=original.id,
        content="用户现在更喜欢早晨开发",
        reason="偏好随时间变化",
    ))
    assert action == MemoryAction.CONFLICT
    assert (await service.require(original.id)).status == MemoryStatus.SUPERSEDED
    active = await service.search(MemoryQuery(text="早晨开发"))
    assert len(active) == 1
    assert active[0].record.supersedes_id == original.id


@pytest.mark.asyncio
async def test_auto_memory_uses_one_plain_json_request_without_tool_choice(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        payload = __import__("json").loads(request.content)
        assert "tool_choice" not in payload
        assert "tools" not in payload
        assert "response_format" not in payload
        message = {"content": '{"action":"create","content":"用户喜欢晚上开发","tags":["偏好"],"confidence":0.9,"reason":"稳定偏好"}'}
        return httpx.Response(200, json={
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1",
            api_key="secret",
            model="test-model",
            client=client,
        )
        decision = await AutoMemory(provider, service).process(
            "我发现晚上开发更舒服。", "听起来这是稳定偏好。"
        )
    assert decision.action == MemoryAction.CREATE
    assert request_count == 1
    assert len(await service.search(MemoryQuery(text="晚上开发"))) == 1


@pytest.mark.asyncio
async def test_json_output_http_error_uses_durable_fact_fallback(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    request_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(400, json={"error": {"message": "unsupported response mode"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        decision = await AutoMemory(provider, service).process(
            "我不喜欢晦涩的名字，只想要叫起来顺口、贴近生活但有点不同。",
            "明白了。",
        )
    assert request_count == 1
    assert decision.action == MemoryAction.CREATE
    assert len(await service.search(MemoryQuery(text="不喜欢晦涩"))) == 1


@pytest.mark.asyncio
async def test_wrong_ignore_is_overridden_for_durable_naming_preference(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([ModelResponse(content='{"action":"ignore","reason":"误判为闲聊"}')])
    decision = await AutoMemory(provider, service).process(
        "其实，单纯是我不喜欢晦涩的，只想要叫起来顺口，贴近生活的同时带点不同。",
        "原来如此。",
    )
    assert decision.action == MemoryAction.CREATE
    records = await service.search(MemoryQuery(text="不喜欢晦涩"))
    assert len(records) == 1


@pytest.mark.asyncio
async def test_discussing_memory_is_not_an_explicit_remember_command(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([ModelResponse(content="invalid decision")])
    auto = AutoMemory(provider, service)
    message = "我不会专门提记住，你尝试记住一下？"
    assert auto._is_explicit_remember(message) is False
    decision = await auto.process(message, "可以尝试。")
    assert decision.action == MemoryAction.IGNORE
    assert await service.search(MemoryQuery()) == []


def test_context_explains_post_turn_auto_memory_without_false_confirmation():
    context = ContextBuilder("你是朝汐。")
    system = context.build(Conversation())[0].content
    assert "回复后独立判断" in system
    assert "不要声称普通对话已经自动保存" in system
    assert "仅当用户明确要求记住长期信息" not in system
