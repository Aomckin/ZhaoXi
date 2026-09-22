"""Lightweight model-assisted routing before normal conversation execution."""

from enum import StrEnum
import json
import re
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
    required_tool: str | None = None


class RouteInput(BaseModel):
    route: CognitiveRoute
    reason: str = Field(min_length=1)
    requires_tool_call: bool = Field(
        default=False,
        description="满足当前请求是否必须产生真实工具调用或外部可观察效果",
    )
    required_tool: str | None = Field(
        default=None,
        description="必须执行时，填写当前运行时目录中最适合完成该效果的确切工具名",
    )
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
        "WORKFLOW 仅用于已经注册并由运行时提供的已知流程；"
        "用户要求检查外部事实或明确使用工具时选择 TOOL；"
        "询问朝汐自身设定、用户长期资料或项目正式文档中的具体事实时选择 TOOL，以便查询潮庭书库；"
        "请求朝汐发送或使用表情属于普通回复表达，选择 DIRECT；只有保存或收藏会话图片才使用 save_emoji Tool；"
        "不要选择 DIRECT 后声称稍后检查。"
        "简单请求禁止选择 PLAN。"
    )

    def __init__(
        self,
        provider: ModelProvider,
        *,
        routing_hints: list[dict[str, object]] | None = None,
        tool_catalog: list[dict[str, object]] | None = None,
        archive_enabled: bool = False,
    ) -> None:
        self.provider = provider
        self.routing_hints = list(routing_hints or [])
        self.tool_catalog = [
            {
                "name": item.get("name"),
                "group": item.get("group"),
                "summary": item.get("summary"),
                "usage": item.get("usage"),
            }
            for item in (tool_catalog or [])
            if item.get("enabled", True) and item.get("available", True)
        ]
        self.archive_enabled = archive_enabled

    @property
    def available_tool_names(self) -> list[str]:
        return [str(item["name"]) for item in self.tool_catalog if item.get("name")]

    def _system_prompt(self) -> str:
        if not self.tool_catalog:
            return self.SYSTEM_PROMPT
        catalog = json.dumps(self.tool_catalog, ensure_ascii=False, separators=(",", ":"))
        return (
            self.SYSTEM_PROMPT
            + " 当前运行时可用工具目录如下；用户要求产生其中能力对应的真实效果时必须选择 TOOL，"
              "并设置 requires_tool_call=true 和 required_tool=最适合的确切工具名。"
              "DIRECT 只能用于无需执行工具即可诚实完成的回答："
            + catalog
        )

    async def route(self, user_message: str, *, recent_context: str = "") -> RouteDecision:
        routing_input = user_message
        if recent_context.strip():
            routing_input = (
                "最近对话（只用于理解当前消息的指代与承接）：\n"
                f"{recent_context.strip()}\n\n当前用户消息：\n{user_message}"
            )
        try:
            response = await self.provider.generate(
                [
                    Message(role=Role.SYSTEM, content=self._system_prompt()),
                    Message(role=Role.USER, content=routing_input),
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
                required_tool = value.required_tool if value.required_tool in self.available_tool_names else None
                return self._guard_simple_request(
                    user_message, RouteDecision(route=value.route, reason=value.reason,
                        requires_tool_call=value.requires_tool_call, required_tool=required_tool,
                        workflow_id=value.workflow_id, workflow_inputs=value.workflow_inputs),
                    recent_context=recent_context,
                )
            except ValidationError:
                break
        return self._fallback(user_message)

    def _hint_decision(self, user_message: str) -> RouteDecision | None:
        text = user_message.casefold()
        normalized = re.sub(r"[，,。！!？?、:：;；]+", " ", text)
        normalized = " ".join(normalized.split())
        for hint in self.routing_hints:
            markers = [str(item).casefold() for item in hint.get("markers", [])]
            if hint.get("match") == "command":
                normalized_markers = [" ".join(re.sub(r"[，,。！!？?、:：;；]+", " ", marker).split()) for marker in markers]
                matched = next(
                    (marker for marker in normalized_markers
                     if normalized == marker or normalized.startswith(marker + " ")),
                    None,
                )
            else:
                matched = next((marker for marker in markers if marker in text), None)
            if matched is None:
                continue
            route = CognitiveRoute(str(hint["route"]))
            if route is CognitiveRoute.TOOL:
                return RouteDecision(route=route, reason="tool package routing hint", requires_tool_call=True)
            value = user_message
            if matched and hint.get("match") == "command":
                for token in matched.split():
                    value = re.sub(re.escape(token), " ", value, count=1, flags=re.IGNORECASE)
                value = re.sub(r"^[\s，,。！!？?、:：;；]+", "", value).strip()
            elif matched:
                value = re.sub(re.escape(matched), " ", value, count=1, flags=re.IGNORECASE).strip()
            input_name = hint.get("input")
            inputs = {str(input_name): value.strip() or hint.get("default_input")} if input_name else {}
            return RouteDecision(
                route=route,
                reason="tool package routing hint",
                workflow_id=str(hint.get("workflow_id")) if hint.get("workflow_id") else None,
                workflow_inputs=inputs,
            )
        return None

    def _guard_simple_request(
        self,
        user_message: str,
        decision: RouteDecision,
        *,
        recent_context: str = "",
    ) -> RouteDecision:
        text = user_message.casefold()
        archive = self._archive_decision(text)
        if archive is not None:
            return archive
        if self._is_emoji_save_request(text):
            return RouteDecision(
                route=CognitiveRoute.TOOL, reason="save emoji side effect",
                requires_tool_call=True,
                required_tool="save_emoji" if "save_emoji" in self.available_tool_names else None,
            )
        if self._is_emoji_reply_request(text):
            return RouteDecision(route=CognitiveRoute.DIRECT, reason="emoji is reply expression")
        contextual_tool = self._contextual_tool_followup(text, recent_context)
        if contextual_tool is not None:
            return contextual_tool
        if decision.route == CognitiveRoute.WORKFLOW:
            return decision
        if decision.requires_tool_call and decision.route is CognitiveRoute.DIRECT:
            return decision.model_copy(update={
                "route": CognitiveRoute.TOOL,
                "reason": "observable tool effect required",
            })
        if decision.route is CognitiveRoute.DIRECT:
            hinted = self._hint_decision(user_message)
            if hinted is not None:
                return hinted
        elif decision.route is CognitiveRoute.TOOL:
            hinted = self._hint_decision(user_message)
            if hinted is not None and hinted.route is CognitiveRoute.TOOL:
                return decision.model_copy(update={"requires_tool_call": True})
            if self._is_lookup_request(text):
                return decision.model_copy(update={"requires_tool_call": True})
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
    def _is_lookup_request(text: str) -> bool:
        return any(marker in text for marker in ("查", "看看", "读取", "核对", "检索", "调用"))

    @staticmethod
    def _is_emoji_reply_request(text: str) -> bool:
        if any(marker in text for marker in ("保存", "收藏", "收进", "加入表情")):
            return False
        return any(marker in text for marker in ("表情", "表情包", "emoji", "贴图")) and any(
            marker in text for marker in ("发", "来", "用", "给我", "看看", "展示")
        )

    @staticmethod
    def _is_emoji_save_request(text: str) -> bool:
        return any(marker in text for marker in ("表情", "表情包", "emoji", "贴图")) and any(
            marker in text for marker in ("保存", "收藏", "收进", "加入")
        )

    def _contextual_tool_followup(
        self, text: str, recent_context: str
    ) -> RouteDecision | None:
        """Resolve short follow-ups such as '你明明可以查到的' against recent tool mentions."""
        if not recent_context or not self._is_lookup_request(text):
            return None
        context = recent_context.casefold()
        for hint in self.routing_hints:
            if str(hint.get("route", "")) != CognitiveRoute.TOOL.value:
                continue
            if any(str(marker).casefold() in context for marker in hint.get("markers", [])):
                return RouteDecision(
                    route=CognitiveRoute.TOOL,
                    reason="contextual tool follow-up",
                    requires_tool_call=True,
                )
        return None

    def _fallback(self, user_message: str) -> RouteDecision:
        text = user_message.casefold()
        archive = self._archive_decision(text)
        if archive is not None:
            return archive
        if self._is_emoji_save_request(text):
            return RouteDecision(
                route=CognitiveRoute.TOOL, reason="save emoji side effect",
                requires_tool_call=True,
                required_tool="save_emoji" if "save_emoji" in self.available_tool_names else None,
            )
        if self._is_emoji_reply_request(text):
            return RouteDecision(route=CognitiveRoute.DIRECT, reason="emoji is reply expression")
        hinted = self._hint_decision(user_message)
        if hinted is not None:
            return hinted
        if "工具" in text and any(marker in text for marker in ("检查", "看看", "有哪些", "可用", "试试")):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool inspection", requires_tool_call=True)
        plan_markers = ("分步骤", "先", "然后", "再", "整理", "检查", "重复", "冲突", "规划")
        if sum(marker in text for marker in plan_markers) >= 2 or (
            "帮我" in text and any(marker in text for marker in ("检查", "整理", "准备", "规划"))
        ):
            return RouteDecision(route=CognitiveRoute.PLAN, reason="fallback: multi-step markers")
        tool_markers = ("几点", "计算", "算一下", "记住", "记一下", "忘掉", "遗忘", "查记忆")
        if any(marker in text for marker in tool_markers):
            return RouteDecision(route=CognitiveRoute.TOOL, reason="fallback: tool marker")
        return RouteDecision(route=CognitiveRoute.DIRECT, reason="fallback: simple conversation")

    def _archive_decision(self, text: str) -> RouteDecision | None:
        if not self.archive_enabled:
            return None
        domains = (
            "朝汐", "潮庭", "暗苟", "身世", "设定", "向日葵发卡", "怕黑",
            "夏装", "生日", "长期资料", "项目文档", "规划文档", "书库",
        )
        fact_markers = (
            "为什么", "是谁", "谁送", "哪天", "哪一天", "什么时候", "是什么", "有哪些",
            "怎么", "多少", "设定", "身世", "资料", "文档", "记载", "写过",
        )
        if any(item in text for item in domains) and any(item in text for item in fact_markers):
            return RouteDecision(
                route=CognitiveRoute.TOOL,
                reason="archive factual query",
                requires_tool_call=True,
            )
        return None
