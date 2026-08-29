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


class RouteDecision(BaseModel):
    route: CognitiveRoute
    reason: str = ""


class RouteInput(BaseModel):
    route: CognitiveRoute
    reason: str = Field(min_length=1)


ROUTE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "route_cognition",
        "description": "判断用户消息应该直接回答、使用单步工具循环，还是进入显式多步 Planner。",
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
                    user_message, RouteDecision(route=value.route, reason=value.reason)
                )
            except ValidationError:
                break
        return self._fallback(user_message)

    @staticmethod
    def _guard_simple_request(user_message: str, decision: RouteDecision) -> RouteDecision:
        if decision.route != CognitiveRoute.PLAN:
            return decision
        text = user_message.casefold()
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
        plan_markers = ("分步骤", "先", "然后", "再", "整理", "检查", "重复", "冲突", "规划")
        if sum(marker in text for marker in plan_markers) >= 2 or (
            "帮我" in text and any(marker in text for marker in ("检查", "整理", "准备", "规划"))
        ):
            return RouteDecision(route=CognitiveRoute.PLAN, reason="fallback: multi-step markers")
        tool_markers = ("几点", "计算", "算一下", "记住", "记一下", "忘掉", "遗忘", "查记忆")
        if any(marker in text for marker in tool_markers):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool marker")
        return RouteDecision(route=CognitiveRoute.DIRECT, reason="fallback: simple conversation")
