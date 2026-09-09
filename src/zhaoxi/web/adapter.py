"""Compatibility adapter from the Web shell to the unified interface gateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4
from datetime import datetime

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.interfaces import InterfaceChannel, InterfaceGateway, UnifiedMessage, UnifiedResponse


@dataclass(slots=True)
class WebResult:
    content: str
    activity: dict[str, Any]
    permission: dict[str, Any] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    status: str = "completed"
    timestamp: datetime | None = None


class WebInterfaceAdapter:
    """Serialize access to one local conversation without owning Core logic."""

    def __init__(self, agent: ZhaoxiAgent) -> None:
        self.agent = agent
        self.gateway = InterfaceGateway(agent)

    async def chat(self, message: str, *, request_id: str | None = None, images: list[str] | None = None, display_parts=None) -> WebResult:
        response = await self.gateway.chat(UnifiedMessage(
            request_id=request_id or str(uuid4()),
            channel=InterfaceChannel.WEB,
            content=message,
            images=images or [],
            display_parts=display_parts or [],
        ))
        return self._result(response)

    async def resolve_permission(self, confirmation_id: str, *, approve: bool) -> WebResult:
        response = await self.gateway.resolve_permission(
            confirmation_id,
            approve=approve,
            request_id=str(uuid4()),
        )
        return self._result(response)

    def session(self) -> list[dict[str, Any]]:
        return self.gateway.session()

    def clear(self) -> None:
        self.gateway.clear()

    @staticmethod
    def _result(response: UnifiedResponse) -> WebResult:
        activity = dict(response.activity)
        permission = response.permission
        return WebResult(
            content=response.content,
            activity=activity,
            permission=permission.model_dump() if permission is not None else None,
            request_id=response.request_id,
            trace_id=response.trace_id,
            status=response.status,
            timestamp=response.timestamp,
        )
