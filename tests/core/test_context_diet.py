"""Successful actions shed irrelevant prompts without ending remaining work."""
import base64
from io import BytesIO
import pytest
from PIL import Image
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import ToolResult
from zhaoxi.core.references import set_references, reset_references
from zhaoxi.observability import action_trace_scope
from zhaoxi.models.types import ModelResponse
from test_loop_safety import Probe, agent, call, correlation


def photo():
    out = BytesIO()
    Image.new("RGB", (1400, 900), "orange").save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


class WriteProbe(Probe):
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False


class Unrelated(Probe):
    name = "lifehud"
    group = "lifehud"
    description = "unrelated-action-definition" * 1000


@pytest.mark.parametrize("kind", ["write", "read", "failure", "no_facts"])
async def test_post_action_slim_context_and_image_extraction_gate(kind):
    tool = (WriteProbe if kind != "read" else Probe)([ToolResult(
        success=kind != "failure", content="confirmed image date 2026-10-23T19:00:00+08:00",
        data=None if kind == "no_facts" else {"title": "synthetic film", "start_at": "2026-10-23T19:00:00+08:00"},
        error="unavailable" if kind == "failure" else None)])
    a, provider = agent([call(), ModelResponse(content="已核实结果。")], tool)
    a.registry.register(Unrelated([]))
    a.registry.update_tools(name="lifehud", force_expose=True)
    original = photo()
    with action_trace_scope() as trace:
        await a.run("帮我保存这个日程", images=[original], require_tool_call=True, required_tool="probe")
    first, second = provider.calls
    assert any(s["function"]["name"] == "lifehud" for s in provider.tool_schemas[0])
    if kind != "failure":
        assert all(s["function"]["name"] != "lifehud" for s in provider.tool_schemas[1])
        assert len(second[0].content) < len(first[0].content)
        assert any(e.event_type == "post_action_context_slimmed" for e in trace.events)
    else:
        assert any(s["function"]["name"] == "lifehud" for s in provider.tool_schemas[1])
    images = [image for m in second for image in m.images]
    assert images
    if kind == "write":
        assert original not in images
        for image in images:
            with Image.open(BytesIO(base64.b64decode(image.partition(",")[2]))) as im:
                assert max(im.size) <= 512
    else:
        assert original in images
    assert any(original in m.images for m in a.conversation.messages)
    assert "2026-10-23T19:00:00+08:00" in "".join(m.content or "" for m in second)
    assert len(tool.calls) == 1 and len(provider.calls) == 2


async def test_slim_continuation_preserves_multiple_actions_without_replay():
    tool = WriteProbe([ToolResult(success=True, content="saved", data={"id":"one"})])
    a, p = agent([call(query="first"), call(query="second", id="second"), ModelResponse(content="两项已完成。")], tool)
    a.allow_multi_model_calls = True
    result = await a.run("保存两个事项，先第一个再第二个", require_tool_call=True, required_tool="probe")
    assert result.result_status == "completed" and tool.calls == ["first", "second"]
    assert len(p.calls) == 3 and any(s["function"]["name"] == "probe" for s in p.tool_schemas[1])


async def test_repair_does_not_reintroduce_original_reference_images():
    tool = WriteProbe([ToolResult(success=True, content="saved", data={"title":"confirmed film"})])
    a, p = agent([call(), ModelResponse(content='{"reply":'), ModelResponse(content='{"reply":"已保存。"}')], tool)
    a.decision_mode = "agency"
    original = photo()
    token = set_references({"items":[{"view":{"message_id":"ref"},"content":"image facts", "images":[original]}]})
    try:
        result = await a.run("帮我保存图片中的日程", require_tool_call=True, required_tool="probe")
    finally:
        reset_references(token)
    assert result.content == "已保存。" and len(tool.calls) == 1
    assert any(original in m.images for m in p.calls[0])
    assert all(original not in m.images for messages in p.calls[1:] for m in messages)
    assert any(m.images for m in p.calls[-1]) and p.tool_schemas[-1] is None


def test_bad_thumbnail_never_falls_back_to_original_after_extraction(monkeypatch):
    from zhaoxi.core.context import ContextBuilder
    from zhaoxi.core.conversation import Conversation
    builder = ContextBuilder("persona")
    conversation = Conversation()
    original = photo()
    conversation.add_user("image", images=[original])
    monkeypatch.setattr(builder.image_thumbnail_cache, "thumbnail", lambda *args: None)
    messages = builder.build(conversation, extracted_images=True)
    assert all(not m.images for m in messages)
    assert "历史图片摘要" in messages[-1].content
    assert conversation.messages[-1].images == [original]


async def test_router_domain_prediction_mounts_only_live_groups_for_one_turn():
    from conftest import FakeProvider
    from zhaoxi.models.types import ToolCall
    from zhaoxi.cognitive.router import CognitiveRouter
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    class Future(Probe):
        name = "future_tool"
        group = "future_domain"
        domain = "Future"
        domain_description = "synthetic future capability"
    class Disabled(Future):
        name = "disabled_tool"
        group = "disabled_domain"
    a, p = agent([ModelResponse(content="收到。")])
    tool = Future([]);a.registry.register(tool);a.registry.register(Disabled([]))
    a.registry.update_tools(name="disabled_tool",enabled=False)
    routing = FakeProvider([ModelResponse(tool_calls=[ToolCall(id="route",name="route_cognition",arguments={
        "route":"tool","reason":"possible future action","preload_tool_groups":["future_domain","disabled_domain","all","unknown"]})])])
    router = CognitiveRouter(routing,tool_catalog_provider=a.registry.manifest)
    coordinator = CognitiveCoordinator(agent=a,router=router)
    with action_trace_scope() as trace:
        await coordinator.run("接着处理那个事项")
    assert len(routing.calls) == 1 and "Tool Domain Map" in routing.calls[0][0].content
    assert "future_domain" in routing.calls[0][0].content
    names = {schema["function"]["name"] for schema in p.tool_schemas[0]}
    assert "future_tool" in names and "disabled_tool" not in names
    assert not tool.calls
    assert any(e.event_type == "tools_preloaded" and e.metadata["groups"] == ["future_domain"] for e in trace.events)
    assert a._tool_discovery_state.expansion_count == 0
    await a.run("下一条普通聊天")
    assert "future_tool" not in {schema["function"]["name"] for schema in p.tool_schemas[-1] or []}


async def test_preloading_never_enables_disabled_tools_or_bypasses_write_confirmation():
    class Guarded(WriteProbe):
        name = "guarded"
        group = "guarded_domain"
        default_confirm_write = True
    tool = Guarded([ToolResult(success=True,content="saved",data={"id":"one"})])
    a, p = agent([call(name="guarded")],tool)
    result = await a.run("帮我保存那个事项",preload_tool_groups=["guarded_domain","all","missing"])
    assert result.permission_confirmation is not None and tool.calls == []
    assert a._tool_discovery_state.preloaded == ["guarded"]


def test_preload_survives_unforce_but_never_survives_disable():
    from zhaoxi.tools.discovery import ToolDiscoveryState
    tool = Unrelated([])
    a, p = agent([ModelResponse(content="ok")])
    a.registry.register(tool);a.registry.update_tools(name="lifehud",force_expose=True)
    state = ToolDiscoveryState(a._tool_context("普通聊天"),preloaded=["lifehud"],preloaded_groups=["lifehud"])
    a.registry.update_tools(name="lifehud",force_expose=False)
    assert any(s["function"]["name"] == "lifehud" for s in state.schemas(a.registry))
    a.registry.update_tools(name="lifehud",enabled=False)
    assert all(s["function"]["name"] != "lifehud" for s in state.schemas(a.registry))
