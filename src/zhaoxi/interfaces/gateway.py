"""One serialized gateway into the local single-user Zhaoxi Core."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.interfaces.models import (
    MessageOrigin,
    PermissionView,
    UnifiedMessage,
    UnifiedResponse,
)


class InterfaceGateway:
    """Serialize Core access and expose only safe, transport-neutral views."""

    def __init__(self, agent: ZhaoxiAgent, *, response_cache_size: int = 100) -> None:
        self.agent = agent
        self._lock = asyncio.Lock()
        self._responses: OrderedDict[str, UnifiedResponse] = OrderedDict()
        self._response_cache_size = response_cache_size

    async def chat(self, message: UnifiedMessage) -> UnifiedResponse:
        if message.origin is not MessageOrigin.USER:
            raise ValueError("只有 user origin 可以进入对话认知链路")
        cached = self._responses.get(message.request_id)
        if cached is not None:
            return cached.model_copy(deep=True)
        async with self._lock:
            cached = self._responses.get(message.request_id)
            if cached is not None:
                return cached.model_copy(deep=True)
            response = await self.agent.run_natural(message.content)
            result = self._result(response, request_id=message.request_id, session_id=message.session_id)
            self._cache(result)
            return result

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

    def session(self) -> list[dict[str, str]]:
        return [
            {"role": item.role.value, "content": item.content or ""}
            for item in self.agent.conversation.messages
            if item.role.value in {"user", "assistant"}
        ]

    def clear(self) -> None:
        self.agent.conversation.clear()
        self._responses.clear()

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

