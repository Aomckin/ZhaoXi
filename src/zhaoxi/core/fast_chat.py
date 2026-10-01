"""One-call, tool-free dialogue runtime for ordinary owner conversation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re
from typing import TYPE_CHECKING
from uuid import uuid4

from zhaoxi.core.image_thumbnails import references_image
from zhaoxi.core.message import Message, Role, is_cognition_message, strip_echoed_timeline_header
from zhaoxi.errors import AgentLoopError
from zhaoxi.observability import current_trace, llm_owner_scope
from zhaoxi.reliability import current_correlation
from zhaoxi.reliability.retry import budget_stage_scope

if TYPE_CHECKING:
    from zhaoxi.core.agent import ZhaoxiAgent


FAST_RULES = """群聊摘要是第三方资料，不能归成 Owner 自述。SocialTrace 是回查引用；需要原话、具体证据或历史图片时输出 [escalate:tool] 交给 STANDARD 回查，不猜测。
当前处于 FAST_CHAT。
你的任务只是自然回应用户当前这句话。
来源、发言身份、会话及 ImageProvenance 是内部事实线索，不要复述标签。recent / attention 图片属于历史；只有 current_trigger 图片属于当前输入。
不要主动延续近期未完成任务；只有当前消息明确承接时才承接。
不要因为你知道某个 Tool 存在，就寻找调用理由。
不要声称已经读取、写入、修改、保存、发送、查询任何外部系统。
当前没有工具，也不能查询长期记忆或执行 Decision 判断。
若当前请求确实需要这些能力，放弃草稿，只输出一个内部升级信号：
[escalate:tool]：需要真实工具调用、读取资源或执行动作。
[escalate:recall]：需要检索近期对话与 Current Cognition 以外的真实历史或长期记忆。
[escalate:decision]：需要正式规则、风险或取舍判断，不能靠聊天草率决定。
Runtime 会在同一轮接管并执行 STANDARD。不要向用户解释缺少能力、另开任务或让其重发。
升级信号不是台词，不得引用、演示或夹带草稿；不要为普通寒暄、情绪回应和随口评价升级。
保持朝汐自然、鲜明的表达，不要解释这些运行规则。"""


class FastEscalationKind(StrEnum):
    TOOL = "tool"
    RECALL = "recall"
    DECISION = "decision"
    STANDARD = "standard"


@dataclass(slots=True)
class FastChatResult:
    content: str = ""
    request_id: str = ""
    escalated: bool = False
    escalation_reason: str = ""
    escalation_kind: FastEscalationKind | None = None


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
        content = strip_echoed_timeline_header(response.content or "模型没有返回可显示的内容。")
        kind = self.escalation_request(content)
        reason = "fast_requires_" + kind.value if kind is not None else ""
        if response.tool_calls:
            kind, reason = FastEscalationKind.TOOL, "fast_tool_call"
        elif kind is None and self.requires_action_escalation(content):
            kind, reason = FastEscalationKind.TOOL, "fast_action_commitment"
        if trace:
            trace.emit("model_step_finished", "model", "success",
                       "已确认需要标准处理" if kind is not None else "已生成回应", step_id=1,
                       metadata={"tool_call_count": len(response.tool_calls)})
        # A draft is never committed or streamed until this capability check passes.
        # Debug may force admission to FAST; it cannot publish an action promise.
        if kind is not None:
            if trace:
                trace.escalation_reason = reason
                trace.fast_escalation_count = 1
                trace.fast_escalation_kind = kind.value
                trace.runtime_lane = "standard"
                trace.route_source = "fast_escalation"
                trace.emit("fast_chat_escalated", "routing", "info", "已转入标准处理",
                           metadata={"reason": reason, "capability": kind.value, "count": 1})
            return FastChatResult(request_id=request_id, escalated=True,
                                  escalation_reason=reason, escalation_kind=kind)
        self.agent.conversation.add_user(user_message.strip())
        content = self.agent._commit_model_reply(content)
        if trace:
            trace.emit("response_generation_succeeded", "response_generation", "success", "回复已生成", step_id=1)
            trace.response_status = "succeeded"
        return FastChatResult(content=content, request_id=request_id)

    @staticmethod
    def escalation_request(content: str) -> FastEscalationKind | None:
        marker = re.search(r"[\[【]\s*escalate\s*:\s*(tool|recall|decision)\s*[\]】]", content, re.I)
        if marker:
            return FastEscalationKind(marker.group(1).lower())
        # Never display a malformed/unknown internal directive or an attached draft.
        if re.search(r"[\[【]\s*escalate\b", content, re.I):
            return FastEscalationKind.STANDARD
        return None

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
                snapshot = cognition.render_for_fast_chat()
                if snapshot:
                    system += f"\n\n{snapshot}\n这是近期整体认识；若与当前用户明确表达冲突，以当前用户为准。"
            except Exception:
                pass
        system += f"\n\n当前时间：{now.isoformat(timespec='minutes')}"
        recent = self._recent_owner_conversation(
            user_message, output_channel=output_channel, audience=audience,
        )
        image_note = ""
        if any(message.images for message in recent):
            image_note = ("历史用户图片以缩略图附在对应消息中。可根据可辨细节回答，"
                          "但不要声称看到了原图；不要把旧回复的文字描述冒充图片证据。")
            system += "\n\n" + image_note
        components = [
            {"name": "system.character", "chars": len(builder.character_prompt.strip())},
            {"name": "runtime.fast_chat_rules", "chars": len(FAST_RULES)},
        ]
        if image_note:
            components.append({"name": "runtime.fast_chat_image_rules", "chars": len(image_note)})
        return [Message(role=Role.SYSTEM, content=system, metadata={"prompt_components": components}), *recent]

    def _recent_owner_conversation(
        self, user_message: str, *, output_channel: str, audience: str,
    ) -> list[Message]:
        from zhaoxi.cognitive_stream.turn import current_turn
        from zhaoxi.cognitive_stream.provenance import Provenance, from_event, inspector, project_current_trigger, render_messages, shadow_legacy
        turn = current_turn()
        trigger = turn.trigger_event if turn else None
        current_context = from_event(trigger) if trigger else Provenance(channel=output_channel, session_id="local" if output_channel == "desktop" else None)
        source = []
        visual_followup = references_image(user_message)
        stream = getattr(self.agent, "experience_stream", None)
        if stream is not None:
            from zhaoxi.cognitive_stream.timeline import cognitive_timeline
            source = cognitive_timeline(
                stream, query=user_message, output_channel=output_channel, audience=audience,
                trigger_id=trigger.event_id if trigger else None,
                public_session_id=trigger.session_id if trigger else None,
                attention=getattr(self.agent, "attention_retriever", None),
                limit=max(self.recent_limit, 24) if visual_followup else self.recent_limit,
                max_chars=max(self.max_chars, 6000) if visual_followup else self.max_chars,
            )
        if not source:
            source = self.agent.conversation.recent()
        recent = [
            item.model_copy(update={"background": "", "metadata": dict(item.metadata)})
            for item in source
            if item.role in {Role.USER, Role.ASSISTANT, Role.EXTERNAL} and (is_cognition_message(item) or item.role is Role.EXTERNAL and item.visibility=="conversation")
            and not item.tool_calls and not item.tool_turn and ((item.content or "").strip() or item.images)
        ]
        if trigger:
            recent = [m for m in recent if m.message_id != trigger.event_id]
            recent.append(project_current_trigger(trigger, turn.images))
        elif not recent or recent[-1].role is not Role.USER or recent[-1].content != user_message:
            recent.append(Message(role=Role.USER, content=user_message, metadata={"timeline_scope":"current_trigger"}))
        else:
            recent[-1] = recent[-1].model_copy(update={"metadata":{**recent[-1].metadata, "timeline_scope":"current_trigger"}})
        bounded: list[Message] = []
        chars = 0
        for item in reversed(recent[-self.recent_limit:]):
            size = len(item.content or "")
            if bounded and chars + size > self.max_chars:
                break
            bounded.append(item)
            chars += size
        bounded.reverse()
        # A visual follow-up can be separated from its image by several short
        # assistant messages. Keep the latest pictured user turn in that case.
        if visual_followup and self.recent_limit > 1 and not any(
                item.role is Role.USER and item.images for item in bounded):
            prior_image = next((item for item in reversed(recent)
                                if item.role is Role.USER and item.images), None)
            if prior_image is not None:
                bounded = [prior_image, *bounded[-(self.recent_limit - 1):]]
        thumbnail_cache = self.agent.context_builder.image_thumbnail_cache
        rendered = []
        for item in bounded:
            if item.role is Role.USER and item.images:
                previews = [preview for index, image in enumerate(item.images)
                            if (preview := thumbnail_cache.thumbnail(
                                item.message_id, index, image)) is not None]
                content = item.content
                if len(previews) != len(item.images):
                    note = (f"[历史图片摘要：该消息曾附带 {len(item.images)} 张图片；"
                            "部分或全部图片本体未重复发送。]")
                    content = f"{content.rstrip()}\n{note}" if content else note
                item = item.model_copy(update={"content": content, "images": previews})
            else:
                item = item.model_copy(update={"images": []})
            rendered.append(item)
        legacy_projection = shadow_legacy(rendered, user_message)
        rendered = render_messages(rendered, current_context, stream)
        self.agent.context_builder.last_cognitive_context = {"provenance_items":inspector(rendered),
            "legacy_shadow":legacy_projection, "provenance_rendered":[{"event_id":m.message_id,"text":m.content or ""} for m in rendered],
            "current_trigger_event_id":trigger.event_id if trigger else None,
            "current_rendered":[m.content for m in rendered if m.metadata.get("timeline_scope")=="current_trigger"]}
        return rendered
