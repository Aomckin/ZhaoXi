"""One serialized gateway into the local single-user Zhaoxi Core."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.message import Message, Role
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
            context = CorrelationContext(
                trace_id=message.request_id,
                request_id=message.request_id,
                session_id=message.session_id,
            )
            try:
                await self._sync_deliveries()
                provider = getattr(self.agent, "provider", None)
                max_calls = getattr(provider, "max_calls", 12)
                max_total_tokens = getattr(provider, "max_total_tokens", 100_000)
                with correlation_scope(context), provider_budget_scope(max_calls, max_total_tokens):
                    previous_messages = {id(m) for m in self.agent.conversation.messages}
                    response = await self.agent.run_natural(
                        message.content, **({"images": message.images} if message.images else {})
                    )
                    if message.display_parts:
                        for item in self.agent.conversation.messages:
                            if id(item) not in previous_messages and item.role == Role.USER:
                                item.metadata['display_parts'] = [p.model_dump(mode='json') for p in message.display_parts]
                                break
                    result = self._result(
                        response,
                        request_id=message.request_id,
                        session_id=message.session_id,
                    )
                beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
                if beat:
                    beat.note_assistant(datetime.now(UTC))
                self._cache(result)
                await self._persist_session()
                self.metrics.increment("interface.chat.completed")
                return result
            except Exception:
                self.metrics.increment("interface.chat.failed")
                raise
            finally:
                if state is not None:
                    state.interacting = False
                    state.last_interaction_at = datetime.now(UTC)
                self.metrics.observe_duration("interface.chat", monotonic() - started)

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
        summaries = delivery.relevant_payload.get("summaries", [delivery.relevant_payload.get("summary", "")])
        self.agent.conversation.add_delivery(Message(
            role=Role.ASSISTANT, content=delivery.content, delivery_id=delivery.delivery_id,
            timestamp=delivery.delivered_at or delivery.available_at,
            metadata={"kind": delivery.kind},
            background="；".join(str(x)[:600] for x in summaries[:20] if x)[:2000],
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
            try:
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
            finally:
                if state is not None:
                    state.interacting = False
                    state.last_interaction_at = datetime.now(UTC)
        beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
        if beat:
            beat.note_assistant(datetime.now(UTC))
        result = self._result(response, request_id=request_id, session_id=session_id)
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
        return [
            {"role": item.role.value, "content": item.content or "", "timestamp": item.timestamp.isoformat(),
             "delivery_id": item.delivery_id,
             "kind": item.metadata.get("kind", ""),
             "display_parts": item.metadata.get("display_parts", []) if item.role == Role.USER else [],
             **({"images": item.images} if item.images else {})}
            for item in self.agent.conversation.messages
            if item.role.value in {"user", "assistant"}
        ]

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

    async def _persist_session(self) -> None:
        session = getattr(self.agent, "session_record", None)
        store = getattr(self.agent, "session_store", None)
        if session is None or store is None:
            return
        session.conversation = self.agent.conversation
        await store.save(session)

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
            trace_id=getattr(response, "request_id", None),
            status="waiting_for_permission" if permission_view else "completed",
            content=str(getattr(response, "content", "")),
            activity={key: value for key, value in activity.items() if value is not None},
            permission=permission_view,
        )
