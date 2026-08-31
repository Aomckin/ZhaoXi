"""Lightweight model-assisted routing before normal conversation execution."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from zhaoxi.core.message import Message, Role
from zhaoxi.models.base import ModelProvider


class CognitiveRoute(StrEnum):
    DIRECT = "direct"
    TOOL = "tool"
    PLAN = "plan"
    WORKFLOW = "workflow"


class RouteDecision(BaseModel):
    route: CognitiveRoute
    reason: str = ""
    workflow_id: str | None = None
    workflow_inputs: dict[str, Any] = Field(default_factory=dict)
    requires_tool_call: bool = False


class RouteInput(BaseModel):
    route: CognitiveRoute
    reason: str = Field(min_length=1)
    workflow_id: str | None = None
    workflow_inputs: dict[str, Any] = Field(default_factory=dict)


ROUTE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "route_cognition",
        "description": "判断用户消息应该直接回答、使用工具、进入 Planner，还是运行已注册 Workflow。",
        "parameters": RouteInput.model_json_schema(),
    },
}


class CognitiveRouter:
    """Classify a turn without mutating the conversation."""

    SYSTEM_PROMPT = (
        "你是 Zhaoxi Core 的轻量认知路由器，只调用 route_cognition。"
        "DIRECT 用于闲聊、解释和无需真实工具的简单回答；"
        "TOOL 用于一个或少量直接工具调用，包括时间、计算、明确记住或遗忘；"
        "PLAN 仅用于确实存在多个步骤、依赖关系、检查后再整理或可能需要重规划的复杂目标。"
        "WORKFLOW 仅用于已知流程：用户说开幕/开始铁幕时选择 lifehud.iron_curtain.open，"
        "说落幕/结束铁幕时选择 lifehud.iron_curtain.close；并提取 title 或 note。"
        "用户要求查询 Life HUD、检查可用工具或随便调用工具验证时选择 TOOL；"
        "不要选择 DIRECT 后声称稍后检查。"
        "简单请求禁止选择 PLAN。"
    )

    def __init__(self, provider: ModelProvider) -> None:
        self.provider = provider

    async def route(self, user_message: str) -> RouteDecision:
        try:
            response = await self.provider.generate(
                [
                    Message(role=Role.SYSTEM, content=self.SYSTEM_PROMPT),
                    Message(role=Role.USER, content=user_message),
                ],
                [ROUTE_SCHEMA],
            )
        except Exception:
            return self._fallback(user_message)
        for call in response.tool_calls:
            if call.name != "route_cognition":
                continue
            try:
                value = RouteInput.model_validate(call.arguments)
                return self._guard_simple_request(
                    user_message, RouteDecision(route=value.route, reason=value.reason,
                        workflow_id=value.workflow_id, workflow_inputs=value.workflow_inputs)
                )
            except ValidationError:
                break
        return self._fallback(user_message)

    @staticmethod
    def _guard_simple_request(user_message: str, decision: RouteDecision) -> RouteDecision:
        text = user_message.casefold()
        if decision.route == CognitiveRoute.WORKFLOW:
            return decision
        if "lifehud" in text or "life hud" in text:
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: Life HUD query", requires_tool_call=True)
        if "工具" in text and any(marker in text for marker in ("检查", "看看", "有哪些", "可用", "试试")):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool inspection", requires_tool_call=True)
        if decision.route != CognitiveRoute.PLAN:
            return decision
        simple_tool_markers = ("几点", "现在时间", "计算", "算一下", "记住", "记一下", "忘掉")
        complex_markers = ("然后", "再", "整理", "检查", "重复", "冲突", "分步骤")
        if any(marker in text for marker in simple_tool_markers) and not any(
            marker in text for marker in complex_markers
        ):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="simple request guard")
        return decision

    @staticmethod
    def _fallback(user_message: str) -> RouteDecision:
        text = user_message.casefold()
        if "开幕" in text or "开始铁幕" in text:
            title = user_message
            for marker in ("朝汐", "开幕", "开始铁幕", "，", ","):
                title = title.replace(marker, " ")
            return RouteDecision(route=CognitiveRoute.WORKFLOW, reason="明确的铁幕开幕命令",
                workflow_id="lifehud.iron_curtain.open", workflow_inputs={"title": title.strip() or "铁幕"})
        if "落幕" in text or "结束铁幕" in text:
            note = user_message
            for marker in ("朝汐", "落幕", "结束铁幕", "，", ","):
                note = note.replace(marker, " ")
            return RouteDecision(route=CognitiveRoute.WORKFLOW, reason="明确的铁幕落幕命令",
                workflow_id="lifehud.iron_curtain.close", workflow_inputs={"note": note.strip() or None})
        if "lifehud" in text or "life hud" in text:
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: Life HUD query", requires_tool_call=True)
        if "工具" in text and any(marker in text for marker in ("检查", "看看", "有哪些", "可用", "试试")):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool inspection", requires_tool_call=True)
        plan_markers = ("分步骤", "先", "然后", "再", "整理", "检查", "重复", "冲突", "规划")
        if sum(marker in text for marker in plan_markers) >= 2 or (
            "帮我" in text and any(marker in text for marker in ("检查", "整理", "准备", "规划"))
        ):
            return RouteDecision(route=CognitiveRoute.PLAN, reason="fallback: multi-step markers")
        tool_markers = ("几点", "计算", "算一下", "记住", "记一下", "忘掉", "遗忘", "查记忆", "铁幕开着")
        if any(marker in text for marker in tool_markers):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool marker")
        return RouteDecision(route=CognitiveRoute.DIRECT, reason="fallback: simple conversation")
