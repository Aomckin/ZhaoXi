"""Compatibility adapter from the Web shell to the unified interface gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.interfaces import InterfaceChannel, InterfaceGateway, UnifiedMessage


@dataclass(slots=True)
class WebResult:
    content: str
    activity: dict[str, Any]
    permission: dict[str, Any] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    status: str = "completed"


class WebInterfaceAdapter:
    """Serialize access to one local conversation without owning Core logic."""

    def __init__(self, agent: ZhaoxiAgent) -> None:
        self.agent = agent
        self.gateway = InterfaceGateway(agent)

    async def chat(self, message: str, *, request_id: str | None = None) -> WebResult:
        response = await self.gateway.chat(UnifiedMessage(
            request_id=request_id or str(uuid4()),
            channel=InterfaceChannel.WEB,
            content=message,
        ))
        return self._result(response)

    async def resolve_permission(self, confirmation_id: str, *, approve: bool) -> WebResult:
        response = await self.gateway.resolve_permission(
            confirmation_id,
            approve=approve,
            request_id=str(uuid4()),
        )
        return self._result(response)

    def session(self) -> list[dict[str, str]]:
        return self.gateway.session()

    def clear(self) -> None:
        self.gateway.clear()

    @staticmethod
    def _result(response: Any) -> WebResult:
        activity = dict(getattr(response, "activity", {}))
        permission = getattr(response, "permission", None)
        return WebResult(
            content=str(getattr(response, "content", "")),
            activity=activity,
            permission=permission.model_dump() if permission is not None else None,
            request_id=getattr(response, "request_id", None),
            trace_id=getattr(response, "trace_id", None),
            status=getattr(response, "status", "completed"),
        )
