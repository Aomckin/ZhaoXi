"""Thin interface adapter between the local web shell and Zhaoxi Core."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from zhaoxi.core.agent import ZhaoxiAgent


@dataclass(slots=True)
class WebResult:
    content: str
    activity: dict[str, Any]
    permission: dict[str, Any] | None = None


class WebInterfaceAdapter:
    """Serialize access to one local conversation without owning Core logic."""

    def __init__(self, agent: ZhaoxiAgent) -> None:
        self.agent = agent
        self._lock = asyncio.Lock()

    async def chat(self, message: str) -> WebResult:
        async with self._lock:
            response = await self.agent.run_natural(message)
        return self._result(response)

    async def resolve_permission(self, confirmation_id: str, *, approve: bool) -> WebResult:
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
        return self._result(response)

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

    @staticmethod
    def _result(response: Any) -> WebResult:
        route = getattr(response, "route", None)
        permission = getattr(response, "permission_confirmation", None)
        activity = {
            "route": getattr(route, "value", route),
            "goal_id": getattr(response, "goal_id", None),
            "workflow_run_id": getattr(response, "workflow_run_id", None),
            "request_id": getattr(response, "request_id", None),
            "steps": getattr(response, "steps", None),
        }
        permission_card = None
        if permission is not None:
            request = permission.request
            permission_card = {
                "confirmation_id": permission.confirmation_id,
                "action": request.action_summary,
                "permission": request.permission.value,
                "resource_scope": request.resource_scope,
                "risk": permission.risk_summary,
            }
        return WebResult(
            content=str(getattr(response, "content", "")),
            activity={key: value for key, value in activity.items() if value is not None},
            permission=permission_card,
        )
