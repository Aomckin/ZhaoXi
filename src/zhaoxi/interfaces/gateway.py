"""One serialized gateway into the local single-user Zhaoxi Core."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.message import Message, Role
from zhaoxi.core.reply.renderer import catalog_emoji_prefix
from zhaoxi.observability import action_trace_scope, current_trace
from zhaoxi.proactive.models import DeliveryStatus
from zhaoxi.interfaces.models import (
    MessageOrigin,
    PermissionView,
    UnifiedMessage,
    UnifiedResponse,
)
from zhaoxi.reliability import (
    CorrelationContext,
    MetricRegistry,
    correlation_scope,
    provider_budget_scope,
)


logger = logging.getLogger("INTERFACE")


class InterfaceGateway:
    """Serialize Core access and expose only safe, transport-neutral views."""

    def __init__(
        self,
        agent: ZhaoxiAgent,
        *,
        response_cache_size: int = 100,
        metrics: MetricRegistry | None = None,
    ) -> None:
        self.agent = agent
        self.metrics = metrics or getattr(agent, "metrics", None) or MetricRegistry()
        self._lock = getattr(agent, "conversation_lock", None) or asyncio.Lock()
        agent.conversation_lock = self._lock
        worker = getattr(agent, "proactive_worker", None)
        if worker:
            worker.delivery_lock = self._lock
        self._responses: OrderedDict[str, UnifiedResponse] = OrderedDict()
        self._response_cache_size = response_cache_size
        self.event_sink = None

    async def chat(self, message: UnifiedMessage) -> UnifiedResponse:
        if message.origin is not MessageOrigin.USER:
            self.metrics.increment("interface.chat.rejected")
            raise ValueError("只有 user origin 可以进入对话认知链路")
        cached = self._responses.get(message.request_id)
        if cached is not None:
            self.metrics.increment("interface.chat.cache_hit")
            return cached.model_copy(deep=True)
        async with self._lock:
            cached = self._responses.get(message.request_id)
            if cached is not None:
                self.metrics.increment("interface.chat.cache_hit")
                return cached.model_copy(deep=True)
            state = getattr(self.agent, "proactive_state", None)
            if state is not None:
                state.interacting = True
                state.last_interaction_at = datetime.now(UTC)
                state.interaction.interact(state.last_interaction_at)
                continuation = getattr(self.agent, "conversation_continuation", None)
                if continuation is not None:
                    continuation.note_user_message(message.content, state.last_interaction_at)
            started = monotonic()
            self.metrics.increment("interface.chat.started")
            previous_messages = {id(item) for item in self.agent.conversation.messages}
            context = CorrelationContext(
                trace_id=message.request_id,
                request_id=message.request_id,
                session_id=message.session_id,
            )
            trace = None
            budget = None
            try:
                await self._sync_deliveries()
                provider = getattr(self.agent, "provider", None)
                max_calls = getattr(provider, "max_calls", 12)
                max_total_tokens = getattr(provider, "max_total_tokens", 100_000)
                await self._maintain_current_cognition(bootstrap=True)
                with correlation_scope(context), provider_budget_scope(max_calls, max_total_tokens, policy=getattr(provider, "budget_policy", None)) as budget, action_trace_scope(self.event_sink) as trace:
                    trace.emit("request_started", "request", "running", "正在处理请求…")
                    response = await self.agent.run_natural(
                        message.content, **({"images": message.images} if message.images else {})
                    )
                    if getattr(response, "permission_confirmation", None) is not None:
                        trace.terminal_status = "waiting_for_permission"
                        trace.response_status = "waiting_for_permission"
                    else:
                        trace.response_status = "succeeded" if trace.response_status == "pending" else trace.response_status
                    self._attach_display_parts(message, previous_messages)
                    result = self._result(
                        response,
                        request_id=message.request_id,
                        session_id=message.session_id,
                        message_id=self._new_assistant_id(previous_messages),
                        output_messages=self._new_output_messages(previous_messages),
                    )
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome,
                               "等待操作确认" if trace.task_status == "waiting_for_permission" else
                               "已完成的操作均已保留" if trace.response_status == "failed" and trace.task_status == "completed" else
                               "本次操作已完成" if trace.task_status == "completed" else "本次操作部分完成")
                beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
                if beat:
                    beat.note_assistant(datetime.now(UTC))
                self._cache(result)
                await self._persist_session()
                if getattr(response, "permission_confirmation", None) is None:
                    await self._maintain_current_cognition()
                emoji_trace = getattr(self.agent, "last_emoji_trace", None)
                if emoji_trace and emoji_trace.get("trace_id") == message.request_id:
                    emoji_trace["persisted"] = any(
                        item.source == "emoji" and item.message_id in emoji_trace.get("message_ids", [])
                        for item in self.agent.conversation.messages
                    )
                    emoji_trace["gateway_emitted"] = any(
                        item.get("source") == "emoji" for item in result.output_messages
                    )
                    logger.info(
                        "emoji persisted=%s gateway_emitted=%s messages=%s",
                        emoji_trace["persisted"],
                        emoji_trace["gateway_emitted"],
                        len(emoji_trace.get("message_ids", [])),
                    )
                self.metrics.increment("interface.chat.completed")
                self.agent.last_action_trace = trace.summary()
                return result
            except Exception:
                if trace is not None:
                    trace.response_status = "failed"
                    trace.terminal_status = trace.task_status if trace.actions else "failed"
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome,
                               "已完成的操作均已保留" if trace.task_status == "completed" else "本次任务未完成")
                    self.agent.last_action_trace = trace.summary()
                self.metrics.increment("interface.chat.failed")
                # The model/tool path may fail after accepting the user turn.
                # Preserve that turn so a session refresh cannot make it disappear.
                self._attach_display_parts(message, previous_messages)
                if any(id(item) not in previous_messages for item in self.agent.conversation.messages):
                    try:
                        await self._persist_session()
                    except Exception as persist_error:
                        logger.warning(
                            "failed to persist conversation after chat error type=%s",
                            type(persist_error).__name__,
                        )
                raise
            finally:
                if budget is not None:
                    self.agent.last_budget_snapshot = budget.snapshot()
                if state is not None:
                    state.interacting = False
                    state.last_interaction_at = datetime.now(UTC)
                self.metrics.observe_duration("interface.chat", monotonic() - started)

    async def regenerate(self, message_id: str, *, request_id: str) -> UnifiedResponse:
        """Regenerate the latest assistant turn without forging a second user turn."""
        async with self._lock:
            messages = self.agent.conversation.messages
            target_index = next(
                (index for index, item in enumerate(messages) if item.message_id == message_id),
                None,
            )
            if target_index is None or messages[target_index].role not in {Role.USER, Role.ASSISTANT}:
                raise KeyError("找不到要重新生成的回复。")
            target = messages[target_index]
            if target.role == Role.ASSISTANT and (target.delivery_id or any(
                item.role in {Role.USER, Role.ASSISTANT} for item in messages[target_index + 1:]
            )):
                raise ValueError("只能重新生成当前最后一条普通回复。")
            pending = getattr(
                getattr(getattr(self.agent, "tool_executor", None), "gateway", None),
                "store", None,
            )
            if any(not item.resolved for item in getattr(pending, "pending", {}).values()):
                raise ValueError("当前有操作等待确认，不能重新生成这条回复。")
            if target.role == Role.USER:
                if any(item.role in {Role.USER, Role.ASSISTANT}
                       for item in messages[target_index + 1:]):
                    raise ValueError("只能重试当前最后一条未回复消息。")
                user_index = target_index
            else:
                user_index = next(
                    (index for index in range(target_index - 1, -1, -1)
                     if messages[index].role == Role.USER),
                    None,
                )
            if user_index is None:
                raise ValueError("这条回复没有可重试的用户消息。")

            original = messages
            source_user = messages[user_index].model_copy(deep=True)
            resume_in_place = target.role == Role.ASSISTANT and bool(target.tool_calls)
            if not resume_in_place:
                self.agent.conversation.replace(messages[:user_index])
            previous_messages = {id(item) for item in self.agent.conversation.messages}
            started = monotonic()
            self.metrics.increment("interface.regenerate.started")
            context = CorrelationContext(
                trace_id=request_id, request_id=request_id, session_id="local"
            )
            trace = None
            budget = None
            try:
                provider = getattr(self.agent, "provider", None)
                max_calls = getattr(provider, "max_calls", 12)
                max_total_tokens = getattr(provider, "max_total_tokens", 100_000)
                with correlation_scope(context), provider_budget_scope(max_calls, max_total_tokens, policy=getattr(provider, "budget_policy", None)) as budget, action_trace_scope(self.event_sink) as trace:
                    trace.emit("request_started", "request", "running", "正在重新生成…")
                    if resume_in_place:
                        response = await self.agent.resume_current_turn(
                            source_user.content or "请查看这些图片。"
                        )
                    else:
                        response = await self.agent.run_natural(
                            source_user.content or "请查看这些图片。",
                            **({"images": source_user.images} if source_user.images else {}),
                        )
                    if getattr(response, "permission_confirmation", None) is not None:
                        trace.terminal_status = "waiting_for_permission"
                        trace.response_status = "waiting_for_permission"
                    else:
                        trace.response_status = "succeeded" if trace.response_status == "pending" else trace.response_status
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome,
                               "等待操作确认" if trace.task_status == "waiting_for_permission" else
                               "已完成的操作均已保留" if trace.response_status == "failed" and trace.task_status == "completed" else
                               "本次操作已完成" if trace.task_status == "completed" else "本次操作部分完成")
                if not resume_in_place:
                    self._restore_user_metadata(source_user, previous_messages)
                result = self._result(
                    response,
                    request_id=request_id,
                    session_id="local",
                    action_trace=trace,
                    message_id=self._new_assistant_id(previous_messages),
                    output_messages=self._new_output_messages(previous_messages),
                )
                self._cache(result)
                await self._persist_session()
                if getattr(response, "permission_confirmation", None) is None:
                    await self._maintain_current_cognition(
                        pending_messages=[item for item in self.agent.conversation.messages
                                          if id(item) not in previous_messages
                                          and item.message_id != source_user.message_id])
                emoji_trace = getattr(self.agent, "last_emoji_trace", None)
                if emoji_trace and emoji_trace.get("trace_id") == request_id:
                    emoji_trace["persisted"] = any(
                        item.source == "emoji" and item.message_id in emoji_trace.get("message_ids", [])
                        for item in self.agent.conversation.messages
                    )
                    emoji_trace["gateway_emitted"] = any(
                        item.get("source") == "emoji" for item in result.output_messages
                    )
                    logger.info(
                        "emoji persisted=%s gateway_emitted=%s messages=%s",
                        emoji_trace["persisted"],
                        emoji_trace["gateway_emitted"],
                        len(emoji_trace.get("message_ids", [])),
                    )
                self.metrics.increment("interface.regenerate.completed")
                self.agent.last_action_trace = trace.summary()
                return result
            except Exception:
                if trace is not None:
                    trace.response_status = "failed"
                    trace.terminal_status = trace.task_status if trace.actions else "failed"
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome,
                               "已完成的操作均已保留" if trace.task_status == "completed" else "本次任务未完成")
                    self.agent.last_action_trace = trace.summary()
                self.agent.conversation.replace(original)
                await self._persist_session()
                self.metrics.increment("interface.regenerate.failed")
                raise
            finally:
                if budget is not None:
                    self.agent.last_budget_snapshot = budget.snapshot()
                self.metrics.observe_duration("interface.regenerate", monotonic() - started)

    async def activate_delivery(self, delivery_id: str):
        async with self._lock:
            runtime = getattr(self.agent, "proactive", None)
            if runtime is None:
                raise KeyError(delivery_id)
            delivery = await runtime.store.get_delivery(delivery_id)
            if delivery is None or delivery.status not in {DeliveryStatus.DELIVERED, DeliveryStatus.ACKNOWLEDGED}:
                raise KeyError(delivery_id)
            # Append the actual delivered text, not a forged user turn or internal event JSON.
            self._include_delivery(delivery)
            await self._persist_session()
            state = getattr(self.agent, "proactive_state", None)
            if state is not None:
                state.last_interaction_at = datetime.now(UTC)
                state.interaction.interact(state.last_interaction_at)
                beat = getattr(state.interaction, "beat_loop", None)
                if beat:
                    beat.note_user_message('', state.last_interaction_at)
            delivery.status = DeliveryStatus.ACKNOWLEDGED
            delivery.acknowledged_at = datetime.now(UTC)
            await runtime.store.save_delivery(delivery)
            return {"delivery_id": delivery_id, "content": delivery.content, "status": delivery.status.value}

    def _include_delivery(self, delivery):
        for item in self.agent.conversation.messages:
            if item.delivery_id == delivery.delivery_id:
                item.metadata['kind'] = delivery.kind
                return
            if item.delivery_id and item.delivery_id.startswith('legacy-') and item.content == delivery.content:
                item.delivery_id = delivery.delivery_id
                item.metadata['kind'] = delivery.kind
                return
        self.agent.conversation.add_delivery(Message(
            role=Role.ASSISTANT, content=delivery.content, delivery_id=delivery.delivery_id,
            timestamp=delivery.delivered_at or delivery.available_at,
            metadata={"kind": delivery.kind},
        ))

    async def _sync_deliveries(self):
        runtime = getattr(self.agent, "proactive", None)
        if runtime is None:
            return
        session = getattr(self.agent, "session_record", None)
        since = session.created_at if session else datetime.min.replace(tzinfo=UTC)
        for delivery in reversed(await runtime.store.list_deliveries(self.agent.conversation.max_messages)):
            if (delivery.status in {DeliveryStatus.DELIVERED, DeliveryStatus.ACKNOWLEDGED}
                    and (delivery.delivered_at or delivery.available_at) >= since):
                self._include_delivery(delivery)

    async def history(self):
        async with self._lock:
            await self._sync_deliveries()
            await self._persist_session()
            return self.session()

    async def resolve_permission(
        self,
        confirmation_id: str,
        *,
        approve: bool,
        request_id: str,
        session_id: str = "local",
    ) -> UnifiedResponse:
        pending = self.agent.tool_executor.gateway.store.pending.get(confirmation_id)
        if pending is None or pending.resolved:
            raise KeyError("待确认操作不存在或已经处理。")
        async with self._lock:
            state = getattr(self.agent, "proactive_state", None)
            if state is not None:
                state.interacting = True
                state.last_interaction_at = datetime.now(UTC)
                state.interaction.interact(state.last_interaction_at)
                beat = getattr(state.interaction, "beat_loop", None)
                if beat:
                    beat.note_user_message("确认" if approve else "拒绝", state.last_interaction_at)
            context = CorrelationContext(trace_id=pending.request.request_id,
                                         request_id=request_id, session_id=session_id)
            provider = getattr(self.agent, "provider", None)
            max_calls = getattr(provider, "max_calls", 12)
            max_total_tokens = getattr(provider, "max_total_tokens", 100_000)
            trace = None
            budget = None
            try:
                with correlation_scope(context), provider_budget_scope(max_calls, max_total_tokens, policy=getattr(provider, "budget_policy", None)) as budget, action_trace_scope(self.event_sink) as trace:
                    trace.emit("request_started", "request", "running", "正在处理操作确认…",
                               metadata={"parent_request_id": pending.request.request_id})
                    if confirmation_id in self.agent._pending_permissions:
                        method = self.agent.approve_permission if approve else self.agent.deny_permission
                        response = await method(confirmation_id)
                    elif self.agent.planner and confirmation_id in self.agent.planner._pending_permissions:
                        method = self.agent.planner.approve_permission if approve else self.agent.planner.deny_permission
                        response = await method(confirmation_id)
                    elif self.agent.workflow:
                        response = await self._resolve_workflow(confirmation_id, approve)
                    else:
                        raise KeyError("找不到待确认操作的原始任务。")
                    trace.response_status = "succeeded" if trace.response_status == "pending" else trace.response_status
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome,
                               "本次操作已完成" if trace.task_status == "completed" else "本次操作未完成")
                await self._persist_session()
                if getattr(response, "permission_confirmation", None) is None:
                    await self._maintain_current_cognition()
            except Exception:
                if trace is not None:
                    trace.response_status = "failed"
                    trace.terminal_status = trace.task_status if trace.actions else "failed"
                    trace.emit("task_" + trace.task_status, "task", trace.task_outcome, "本次操作未完成")
                    self.agent.last_action_trace = trace.summary()
                raise
            finally:
                if budget is not None:
                    self.agent.last_budget_snapshot = budget.snapshot()
                if state is not None:
                    state.interacting = False
                    state.last_interaction_at = datetime.now(UTC)
        beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
        if beat:
            beat.note_assistant(datetime.now(UTC))
        result = self._result(response, request_id=request_id, session_id=session_id, action_trace=trace)
        self.agent.last_action_trace = trace.summary()
        self._cache(result)
        return result

    async def _resolve_workflow(self, confirmation_id: str, approve: bool):
        for run in await self.agent.workflow.history():
            if run.status.value != "waiting_for_permission" or not run.current_step_id:
                continue
            step = run.step_run(run.current_step_id)
            if step.confirmation_id != confirmation_id:
                continue
            method = self.agent.workflow.approve if approve else self.agent.workflow.deny
            resumed = await method(run.id)
            return await self.agent.finalize_workflow(resumed)
        raise KeyError("找不到待确认操作的原始 Workflow。")

    def session(self) -> list[dict[str, Any]]:
        visible = [
            item for item in self.agent.conversation.messages
            if item.role.value in {"user", "assistant"}
        ]
        latest = visible[-1] if visible else None
        result = []
        emoji_service = getattr(self.agent, "emoji_service", None)
        for item in visible:
            view = self._message_view(
                item,
                regeneratable=item is latest and item.role == Role.ASSISTANT and not item.delivery_id,
            )
            legacy = (catalog_emoji_prefix(item.content or "", emoji_service)
                      if item.role == Role.ASSISTANT and not item.source and not item.images else None)
            if legacy is not None:
                emoji_id, text = legacy
                image = {**view, "id": f"{item.message_id}-legacy-emoji",
                         "message_id": f"{item.message_id}-legacy-emoji",
                         "type": "image", "text": "", "content": "",
                         "images": [f"/api/expression/emoji/{emoji_id}"],
                         "source": "emoji", "emoji_id": emoji_id, "regeneratable": False}
                if not text:
                    image["id"] = image["message_id"] = item.message_id
                    image["regeneratable"] = view["regeneratable"]
                result.append(image)
                if text:
                    result.append({**view, "text": text, "content": text})
            else:
                result.append(view)
        return result

    def clear(self) -> None:
        self.agent.conversation.clear()
        state = getattr(self.agent, "proactive_state", None)
        beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
        if beat:
            state.interaction.active_until = None
            state.interaction.receptive(datetime.now(UTC))
            state.interaction.refresh(datetime.now(UTC))
            beat.session = None
            beat.open_thread = None
            beat.last_model_decision = None
        self._responses.clear()
        session = getattr(self.agent, "session_record", None)
        store = getattr(self.agent, "session_store", None)
        if session is not None and store is not None:
            session.created_at = datetime.now(UTC)
            session.conversation = self.agent.conversation
            store.save_sync(session)

    async def _maintain_current_cognition(self, *, bootstrap: bool = False,
                                          pending_messages: list[Message] | None = None) -> None:
        maintainer = getattr(self.agent, "current_cognition_maintainer", None)
        if maintainer is None:
            return
        try:
            messages = self.agent.conversation.messages
            if bootstrap and (not messages or maintainer.service.state().last_processed_message_id is not None):
                return
            provider = getattr(self.agent, "provider", None)
            with provider_budget_scope(getattr(provider, "max_calls", 12),
                                       getattr(provider, "max_total_tokens", 100_000)):
                await maintainer.maintain(messages, pending_override=pending_messages)
        except Exception as exc:
            logger.warning("COGNITION_MAINTAIN_FAILED type=%s", type(exc).__name__)

    async def _persist_session(self) -> None:
        session = getattr(self.agent, "session_record", None)
        store = getattr(self.agent, "session_store", None)
        if session is None or store is None:
            return
        session.conversation = self.agent.conversation
        await store.save(session)

    def _attach_display_parts(self, message: UnifiedMessage, previous_messages: set[int]) -> None:
        if not message.display_parts:
            return
        for item in self.agent.conversation.messages:
            if id(item) not in previous_messages and item.role == Role.USER:
                item.metadata["display_parts"] = [
                    part.model_dump(mode="json") for part in message.display_parts
                ]
                return

    def _restore_user_metadata(self, source: Message, previous_messages: set[int]) -> None:
        for item in self.agent.conversation.messages:
            if id(item) not in previous_messages and item.role == Role.USER:
                item.message_id = source.message_id
                item.timestamp = source.timestamp
                item.metadata = dict(source.metadata)
                return

    def _new_assistant_id(self, previous_messages: set[int]) -> str | None:
        return next(
            (item.message_id for item in reversed(self.agent.conversation.messages)
             if id(item) not in previous_messages and item.role == Role.ASSISTANT),
            None,
        )

    def _new_output_messages(self, previous_messages: set[int]) -> list[dict[str, Any]]:
        return [
            self._message_view(item)
            for item in self.agent.conversation.messages
            if id(item) not in previous_messages
            and item.role == Role.ASSISTANT
            and (item.images or not item.tool_calls)
        ]

    @staticmethod
    def _message_view(item: Message, *, regeneratable: bool = False) -> dict[str, Any]:
        """One message contract shared by live output and history restoration."""
        return {
            "id": item.message_id,
            "message_id": item.message_id,
            "role": item.role.value,
            "type": "image" if item.is_image_only else "text",
            "text": item.content or "",
            "content": item.content or "",
            "images": list(item.images),
            "source": item.source,
            "emoji_id": item.emoji_id,
            "requested_tags": list(item.requested_tags),
            "segment_type": item.segment_type,
            "reply_group_id": item.reply_group_id,
            "timestamp": item.timestamp.isoformat(),
            "delivery_id": item.delivery_id,
            "kind": item.metadata.get("kind", ""),
            "regeneratable": regeneratable,
            "display_parts": item.metadata.get("display_parts", []) if item.role == Role.USER else [],
        }

    def _cache(self, response: UnifiedResponse) -> None:
        self._responses[response.request_id] = response.model_copy(deep=True)
        self._responses.move_to_end(response.request_id)
        while len(self._responses) > self._response_cache_size:
            self._responses.popitem(last=False)

    @staticmethod
    def _result(
        response: Any,
        *,
        request_id: str,
        session_id: str,
        message_id: str | None = None,
        output_messages: list[dict[str, Any]] | None = None,
        action_trace=None,
    ) -> UnifiedResponse:
        route = getattr(response, "route", None)
        permission = getattr(response, "permission_confirmation", None)
        activity = {
            "route": getattr(route, "value", route),
            "goal_id": getattr(response, "goal_id", None),
            "workflow_run_id": getattr(response, "workflow_run_id", None),
            "core_request_id": getattr(response, "request_id", None),
            "steps": getattr(response, "steps", None),
        }
        trace = action_trace or current_trace()
        if trace is not None:
            activity["task_status"] = trace.task_status
            activity["response_status"] = trace.response_status
        permission_view = None
        if permission is not None:
            permission_request = permission.request
            permission_view = PermissionView(
                confirmation_id=permission.confirmation_id,
                action=permission_request.action_summary,
                permission=permission_request.permission.value,
                resource_scope=permission_request.resource_scope,
                risk=permission.risk_summary,
            )
        return UnifiedResponse(
            request_id=request_id,
            session_id=session_id,
            trace_id=request_id,
            status="waiting_for_permission" if permission_view else trace.task_status if trace else "completed",
            content=str(getattr(response, "content", "")),
            message_id=message_id,
            activity={key: value for key, value in activity.items() if value is not None},
            permission=permission_view,
            output_messages=output_messages or [],
        )
