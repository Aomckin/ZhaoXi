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
from zhaoxi.expression import EmojiService
from zhaoxi.memory.models import MemoryCreate, MemoryQuery, MemoryStatus
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def test_router_fallback_recognizes_iron_curtain_workflows():
    hints = __import__("tools.lifehud_tool.package", fromlist=["create_package"]).create_package().routing_hints()
    router = CognitiveRouter(FakeProvider([]), routing_hints=hints)
    opened = router._fallback("朝汐，开幕，开发 v0.5")
    closed = router._fallback("朝汐，落幕，完成 Workflow")
    assert opened.route == CognitiveRoute.WORKFLOW
    assert opened.workflow_id == "lifehud.iron_curtain.open"
    assert opened.workflow_inputs["title"] == "开发 v0.5"
    assert closed.workflow_id == "lifehud.iron_curtain.close"
    assert closed.workflow_inputs["note"] == "完成 Workflow"


def test_router_hint_does_not_hijack_ordinary_opening_text():
    hints = __import__("tools.lifehud_tool.package", fromlist=["create_package"]).create_package().routing_hints()
    router = CognitiveRouter(FakeProvider([]), routing_hints=hints)
    decision = router._fallback("那个电影节今天开幕了。")
    assert decision.workflow_id != "lifehud.iron_curtain.open"


def test_router_fallback_sends_lifehud_and_tool_inspection_to_tools():
    hints = __import__("tools.lifehud_tool.package", fromlist=["create_package"]).create_package().routing_hints()
    router = CognitiveRouter(FakeProvider([]), routing_hints=hints)
    assert router._fallback("随便用 LifeHUD 查点啥").route == CognitiveRoute.TOOL
    assert router._fallback("你检查下工具看看？").route == CognitiveRoute.TOOL


@pytest.mark.asyncio
async def test_qwen_text_function_call_routes_archive_query_to_tool_path():
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={
            "id": "qwen-route",
            "choices": [{"message": {"content": (
                "<tool_call><function=route_cognition>"
                "<parameter=route>tool</parameter>"
                "<parameter=reason>需要查询潮庭书库</parameter>"
                "</function></tool_call>"
            )}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="qwen3.8-flash", client=client
        )
        decision = await CognitiveRouter(provider, archive_enabled=True).route("潮庭里有几把钥匙？")

    assert requests[0]["tools"][0]["function"]["name"] == "route_cognition"
    assert decision.route is CognitiveRoute.TOOL


@pytest.mark.asyncio
async def test_contextual_lifehud_followup_forces_a_real_tool_call():
    hints = __import__("tools.lifehud_tool.package", fromlist=["create_package"]).create_package().routing_hints()
    provider = FakeProvider([
        control("route_cognition", {"route": "direct", "reason": "错误地只看了当前短句"}),
    ])
    router = CognitiveRouter(provider, routing_hints=hints)

    decision = await router.route(
        "你明明可以查到的",
        recent_context="user: 你肯定不知道我中午吃的啥\nassistant: 我可以看 LifeHUD",
    )

    assert decision.route == CognitiveRoute.TOOL
    assert decision.requires_tool_call is True
    assert decision.reason == "contextual tool follow-up"
    assert "最近对话" in provider.calls[0][1].content


@pytest.mark.asyncio
async def test_contextual_tool_followup_cannot_end_on_a_verbal_promise(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        control("route_cognition", {"route": "direct", "reason": "错误地只看了当前短句"}),
        ModelResponse(content="我这就去看看。"),
        control("current_time", {}),
        ModelResponse(content="已经实际查过了。"),
        control("decide_memory", {"action": "ignore", "reason": "一次查询"}),
    ])
    agent = make_cognitive(provider, service)
    agent.cognitive.router.routing_hints = (
        __import__("tools.lifehud_tool.package", fromlist=["create_package"])
        .create_package()
        .routing_hints()
    )
    agent.conversation.add_user("你肯定不知道我中午吃的啥")
    agent.conversation.add_assistant("我可以看 LifeHUD。")

    response = await agent.run_natural("你明明可以查到的")

    assert response.route == CognitiveRoute.TOOL
    assert response.content == "已经实际查过了。"
    assert provider.tool_schemas[1]
    assert provider.tool_schemas[2]
    assert any(message.name == "current_time" for message in agent.conversation.messages)


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
    assert {schema["function"]["name"] for schema in provider.tool_schemas[1]} == {
        "remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog",
    }


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

@pytest.mark.asyncio
async def test_direct_dinner_guess_promoting_own_lookup_finishes_same_turn(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    promise = '唔……居然又要考我。这回我可不傻，我直接去翻你的LifeHUD记录，看看你晚饭到底填了什么。'
    provider = FakeProvider([
        control('route_cognition', {'route': 'direct', 'reason': '闲聊猜测'}),
        ModelResponse(content=promise),
        control('current_time', {}),
        ModelResponse(content='查完了，这是完整的最终回复。'),
        control('decide_memory', {'action': 'ignore', 'reason': '查询'}),
    ])
    agent = make_cognitive(provider, service)
    result = await agent.run_natural('猜猜我晚上吃的啥')
    assert result.route == CognitiveRoute.TOOL
    assert result.content == '查完了，这是完整的最终回复。'
    assert {schema["function"]["name"] for schema in provider.tool_schemas[1]} == {
        "remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog",
    }
    assert provider.tool_schemas[2]
    assert sum(m.role.value == 'user' for m in agent.conversation.messages) == 1
    assert not any(m.content == promise for m in agent.conversation.messages)
    assert any(m.role.value == 'tool' for m in agent.conversation.messages)


@pytest.mark.asyncio
async def test_guess_without_lookup_remains_direct(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    provider = FakeProvider([
        control('route_cognition', {'route': 'direct', 'reason': '闲聊'}),
        ModelResponse(content='我猜是面条？只是猜的。'),
        control('decide_memory', {'action': 'ignore', 'reason': '猜测'}),
    ])
    result = await make_cognitive(provider, service).run_natural('猜猜我晚上吃的啥')
    assert result.route == CognitiveRoute.DIRECT
    assert {schema["function"]["name"] for schema in provider.tool_schemas[1]} == {
        "remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog",
    }


@pytest.mark.asyncio
async def test_direct_repeated_lookup_promise_returns_with_notice(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    provider = FakeProvider([
        control('route_cognition', {'route': 'direct', 'reason': '闲聊'}),
        ModelResponse(content='我这就去查一下。'),
        ModelResponse(content='我马上去查。'),
    ])
    agent = make_cognitive(provider, service)
    result = await agent.run_natural('猜猜晚饭')
    assert result.content == (
        '我马上去查。\n\n'
        '（提醒：这次没有实际调用工具，回复未经工具核验。）'
    )
    assert result.route == CognitiveRoute.DIRECT
    assert agent.conversation.messages[-1].content == result.content
    assert len(provider.calls) == 4
    assert len(agent.conversation.messages) == 2


@pytest.mark.asyncio
async def test_optional_tool_path_cannot_end_on_lookup_promise(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    provider = FakeProvider([
        ModelResponse(content='我先检查一下记录。'),
        control('current_time', {}),
        ModelResponse(content='查询完成。'),
    ])
    result = await make_cognitive(provider, service).run('猜猜晚饭')
    assert result.content == '查询完成。'
    assert len(provider.calls) == 3


@pytest.mark.parametrize('text', ['我不会查记录，只猜。', '我不能查询。', '我可以查询记录。', '你去查一下。'])
def test_non_commitments_do_not_trigger_lookup(text):
    assert not ZhaoxiAgent._promises_lookup(text)


def test_emoji_send_is_direct_but_saving_remains_a_tool_request():
    router = CognitiveRouter(FakeProvider([]), tool_catalog=[{
        'name': 'save_emoji', 'group': 'expression', 'summary': '收藏会话图片',
        'usage': '只在用户明确要求保存时使用', 'enabled': True, 'available': True,
    }])
    assert router._fallback('给我发个表情').route is CognitiveRoute.DIRECT
    saving = router._fallback('把这张图收藏成表情')
    assert saving.route is CognitiveRoute.TOOL
    assert saving.required_tool == 'save_emoji'
