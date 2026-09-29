"""One-call, tool-free dialogue runtime for ordinary owner conversation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import re
from typing import TYPE_CHECKING
from uuid import uuid4

from zhaoxi.core.message import Message, Role, is_cognition_message, strip_echoed_timeline_header
from zhaoxi.errors import AgentLoopError
from zhaoxi.observability import current_trace, llm_owner_scope
from zhaoxi.reliability import current_correlation
from zhaoxi.reliability.retry import budget_stage_scope

if TYPE_CHECKING:
    from zhaoxi.core.agent import ZhaoxiAgent


FAST_RULES = """当前处于 FAST_CHAT。
你的任务只是自然回应用户当前这句话。
不要主动延续近期未完成任务；只有当前消息明确承接时才承接。
不要因为你知道某个 Tool 存在，就寻找调用理由。
不要声称已经读取、写入、修改、保存、发送、查询任何外部系统。
当前没有工具；需要真实外部动作或事实时，诚实说明需要另行处理，不要承诺正在执行。
保持朝汐自然、鲜明的表达，不要解释这些运行规则。"""


@dataclass(slots=True)
class FastChatResult:
    content: str = ""
    request_id: str = ""
    escalated: bool = False
    escalation_reason: str = ""


class FastChatRuntime:
    def __init__(self, agent: "ZhaoxiAgent", *, recent_limit: int = 8, max_chars: int = 3000) -> None:
        self.agent = agent
        self.recent_limit = recent_limit
        self.max_chars = max_chars

    async def run_fast_chat(
        self, user_message: str, *, output_channel: str = "desktop",
        audience: str = "owner", expression_policy: str = "", force: bool = False,
    ) -> FastChatResult:
        correlation = current_correlation()
        request_id = correlation.request_id if correlation and correlation.request_id else uuid4().hex
        messages = self._messages(
            user_message, output_channel=output_channel, audience=audience,
            expression_policy=expression_policy,
        )
        trace = current_trace()
        if trace:
            trace.emit("model_step_started", "model", "running", "正在回应…", step_id=1)
            trace.emit("response_generation_started", "response_generation", "running", "正在整理回复…", step_id=1)
        try:
            with budget_stage_scope("response_generation"), llm_owner_scope("fast_chat", "response_generation"):
                response = await asyncio.wait_for(
                    self.agent.provider.generate(messages, None), timeout=self.agent.timeout_seconds
                )
        except TimeoutError as exc:
            if trace:
                trace.emit("model_step_failed", "model", "failed", "模型请求超时", step_id=1,
                           error_code="agent_timeout")
                trace.emit("response_generation_failed", "response_generation", "failed",
                           "最终回复生成超时", step_id=1, error_code="agent_timeout")
                trace.response_status = "failed"
            raise AgentLoopError(f"请求超过 {self.agent.timeout_seconds:g} 秒，已停止。", code="agent_timeout") from exc
        if trace:
            trace.emit("model_step_finished", "model", "success", "已生成回应", step_id=1,
                       metadata={"tool_call_count": len(response.tool_calls)})
        content = strip_echoed_timeline_header(response.content or "模型没有返回可显示的内容。")
        if not force and (response.tool_calls or self.requires_action_escalation(content)):
            if trace:
                trace.escalation_reason = "fast_action_commitment"
                trace.emit("fast_chat_escalated", "routing", "warning", "轻量回复需要升级处理",
                           metadata={"reason": trace.escalation_reason})
            return FastChatResult(request_id=request_id, escalated=True,
                                  escalation_reason="fast_action_commitment")
        self.agent.conversation.add_user(user_message.strip())
        content = self.agent._commit_model_reply(content)
        if trace:
            trace.emit("response_generation_succeeded", "response_generation", "success", "回复已生成", step_id=1)
            trace.response_status = "succeeded"
        return FastChatResult(content=content, request_id=request_id)

    @staticmethod
    def requires_action_escalation(content: str) -> bool:
        for clause in re.split(r"[。！？!?\n]", content):
            if re.search(r"(?:不|没|无法|不能|不会|不用|别)(?:去|再|帮你|替你|现在|马上)?", clause):
                continue
            if re.search(
                r"我(?:现在|这就|马上|直接|先|来|去|会|要|就|再|帮你|替你){1,5}"
                r"(?:查|查询|检查|读取|检索|调用|写入|记下|保存|发送|更新|修改|删除|同步|上传|打开|关闭)",
                clause,
            ):
                return True
        return False

    def _messages(
        self, user_message: str, *, output_channel: str, audience: str,
        expression_policy: str,
    ) -> list[Message]:
        builder = self.agent.context_builder
        now = datetime.now(builder.timezone)
        system = builder.character_prompt.strip() + "\n\n" + FAST_RULES
        if expression_policy:
            system += "\n\n" + expression_policy
        cognition = getattr(builder, "current_cognition_service", None)
        if cognition is not None:
            try:
                snapshot = cognition.snapshot()
                if snapshot:
                    system += f"\n\n{snapshot}\n这是近期整体认识；若与当前用户明确表达冲突，以当前用户为准。"
            except Exception:
                pass
        system += f"\n\n当前时间：{now.isoformat(timespec='minutes')}"
        recent = self._recent_owner_conversation(
            user_message, output_channel=output_channel, audience=audience,
        )
        components = [
            {"name": "system.character", "chars": len(builder.character_prompt.strip())},
            {"name": "runtime.fast_chat_rules", "chars": len(FAST_RULES)},
        ]
        return [Message(role=Role.SYSTEM, content=system, metadata={"prompt_components": components}), *recent]

    def _recent_owner_conversation(
        self, user_message: str, *, output_channel: str, audience: str,
    ) -> list[Message]:
        source = []
        stream = getattr(self.agent, "experience_stream", None)
        if stream is not None:
            from zhaoxi.cognitive_stream.timeline import cognitive_timeline
            source = cognitive_timeline(
                stream, query=user_message, output_channel=output_channel, audience=audience,
                attention=getattr(self.agent, "attention_retriever", None),
                limit=self.recent_limit, max_chars=self.max_chars,
            )
        if not source:
            source = self.agent.conversation.recent(self.recent_limit)
        recent = [
            item.model_copy(update={"images": [], "background": "", "metadata": {}})
            for item in source
            if item.role in {Role.USER, Role.ASSISTANT} and is_cognition_message(item)
            and not item.tool_calls and not item.tool_turn and (item.content or "").strip()
        ]
        if not recent or recent[-1].role is not Role.USER or recent[-1].content != user_message:
            recent.append(Message(role=Role.USER, content=user_message))
        bounded: list[Message] = []
        chars = 0
        for item in reversed(recent[-self.recent_limit:]):
            size = len(item.content or "")
            if bounded and chars + size > self.max_chars:
                break
            bounded.append(item)
            chars += size
        return list(reversed(bounded))
