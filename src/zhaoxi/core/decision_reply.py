"""Constrained Persona expression in the main reply chain.

The model chooses tone and which approved reasons to mention; executable words
always come from the validated DecisionResult, never from model reply text.
"""

from typing import Literal

from pydantic import BaseModel, Field

from zhaoxi.decision.models import DecisionLevel, DecisionResult


class DecisionExpression(BaseModel):
    tone: Literal["plain", "warm", "playful"] = "plain"
    reason_indices: list[int] = Field(default_factory=lambda: [0], max_length=2)


EXPRESSION_SCHEMA = {"type": "function", "function": {
    "name": "select_decision_expression",
    "description": "依据朝汐人格选择本次回复语气和已确认的理由编号；不可修改决策方向。",
    "parameters": DecisionExpression.model_json_schema(),
}}


def compose_decision_reply(result: DecisionResult, expression: DecisionExpression,
                           *, mode: str = "normal") -> str:
    """Compose only validated decision facts, so a Persona model cannot reverse them."""
    if result.level == DecisionLevel.L2:
        opener = {"plain": "这个得你定。", "warm": "这一步我陪你理清，但决定得留给你。",
                  "playful": "这题我不能替你按掉，最后那一下得你来。"}[expression.tone]
        parts = [opener]
        if result.conflicts:
            parts.append("核心冲突：" + result.conflicts[0])
        if result.missing_information:
            parts.append("还缺：" + "、".join(result.missing_information[:3]))
        parts.append("真正要你判断的是：" + (result.core_question or "你愿意承担哪一种长期代价？"))
        return "\n".join(parts)
    if mode == "decide_for_me" or result.level == DecisionLevel.L0:
        return result.verdict.rstrip("。！!") + "。"
    opener = {"plain": "建议：", "warm": "我给你一个方向：", "playful": "这题先帮你按掉："}[expression.tone]
    lines = [opener + result.verdict]
    selected = list(dict.fromkeys(index for index in expression.reason_indices
                                  if 0 <= index < len(result.reasons)))[:2]
    if selected:
        lines.append("原因：" + "；".join(result.reasons[index] for index in selected))
    if result.exception:
        lines.append("例外：" + result.exception)
    return "\n".join(lines)


def compose_override_reply(expression: DecisionExpression) -> str:
    return {"plain": "好，就按你刚才说的。", "warm": "好，听你的，就照你说的来。",
            "playful": "收到，这回听你的，我不跟你争。"}[expression.tone]
