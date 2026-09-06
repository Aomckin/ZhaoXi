"""One serialized gateway into the local single-user Zhaoxi Core."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from zhaoxi.core.agent import ZhaoxiAgent
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
        self._lock = asyncio.Lock()
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
            started = monotonic()
            self.metrics.increment("interface.chat.started")
            context = CorrelationContext(
                trace_id=message.request_id,
                request_id=message.request_id,
                session_id=message.session_id,
            )
            try:
                provider = getattr(self.agent, "provider", None)
                max_calls = getattr(provider, "max_calls", 12)
                max_total_tokens = getattr(provider, "max_total_tokens", 100_000)
                with correlation_scope(context), provider_budget_scope(max_calls, max_total_tokens):
                    response = await self.agent.run_natural(
                        message.content, **({"images": message.images} if message.images else {})
                    )
                    result = self._result(
                        response,
                        request_id=message.request_id,
                        session_id=message.session_id,
                    )
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
            summaries = delivery.relevant_payload.get("summaries", [delivery.relevant_payload.get("summary", "")])
            background = "；".join(str(x)[:600] for x in summaries[:20] if x)
            marker = f"[朝汐主动消息 · {delivery.available_at.isoformat()}]\n{delivery.content}"
            if background:
                marker += "\n相关背景：" + background

            if not any(m.content == marker for m in self.agent.conversation.messages):
                self.agent.conversation.add_assistant(marker)
                await self._persist_session()
            state = getattr(self.agent, "proactive_state", None)
            if state is not None:
                state.last_interaction_at = datetime.now(UTC)
            delivery.status = DeliveryStatus.ACKNOWLEDGED
            delivery.acknowledged_at = datetime.now(UTC)
            await runtime.store.save_delivery(delivery)
            return {"delivery_id": delivery_id, "content": delivery.content, "status": delivery.status.value}

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
            {"role": item.role.value, "content": item.content or "",
             **({"images": item.images} if item.images else {})}
            for item in self.agent.conversation.messages
            if item.role.value in {"user", "assistant"}
        ]

    def clear(self) -> None:
        self.agent.conversation.clear()
        self._responses.clear()
        session = getattr(self.agent, "session_record", None)
        store = getattr(self.agent, "session_store", None)
        if session is not None and store is not None:
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
