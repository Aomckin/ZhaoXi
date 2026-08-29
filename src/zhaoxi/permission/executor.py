"""The only production boundary for discovering and running tools."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from zhaoxi.errors import ToolNotFoundError
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import (
    InvocationOrigin,
    PendingConfirmation,
    PermissionRequest,
    PermissionStatus,
)
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.registry import ToolRegistry
from pydantic import ValidationError


@dataclass(slots=True)
class ToolExecution:
    result: ToolResult | None
    request: PermissionRequest | None = None
    confirmation: PendingConfirmation | None = None

    @property
    def waiting_for_permission(self) -> bool:
        return self.confirmation is not None


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        gateway: PermissionGateway | None = None,
        *,
        max_output_chars: int = 12_000,
    ) -> None:
        self.registry = registry
        self.gateway = gateway or PermissionGateway()
        self.max_output_chars = max_output_chars

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        request_id: str,
        origin: InvocationOrigin,
        user_intent: str = "",
        invocation_id: str | None = None,
        goal_id: str | None = None,
        step_id: str | None = None,
        approved_batch_confirmation_id: str | None = None,
    ) -> ToolExecution:
        try:
            tool = self.registry.get(name)
        except ToolNotFoundError as exc:
            return ToolExecution(ToolResult(success=False, content="请求的工具不存在。", error=str(exc)))
        try:
            normalized_arguments = tool.input_model.model_validate(arguments).model_dump(mode="json")
        except ValidationError as exc:
            return ToolExecution(
                ToolResult(success=False, content="工具参数无效。", error=str(exc))
            )
        arguments = normalized_arguments
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        request = PermissionRequest(
            invocation_id=invocation_id or "",
            request_id=request_id,
            tool_name=name,
            permission=tool.permission,
            arguments=arguments,
            arguments_digest=digest,
            resource_scope=tool.resource_scope(arguments),
            action_summary=tool.confirmation_description(arguments),
            origin=origin,
            user_intent=user_intent,
            goal_id=goal_id,
            step_id=step_id,
        ) if invocation_id else PermissionRequest(
            request_id=request_id,
            tool_name=name,
            permission=tool.permission,
            arguments=arguments,
            arguments_digest=digest,
            resource_scope=tool.resource_scope(arguments),
            action_summary=tool.confirmation_description(arguments),
            origin=origin,
            user_intent=user_intent,
            goal_id=goal_id,
            step_id=step_id,
        )
        if approved_batch_confirmation_id is not None:
            self.gateway.grant_batch_member(approved_batch_confirmation_id, request)
        decision, confirmation = self.gateway.evaluate(request)
        if confirmation:
            return ToolExecution(None, request=request, confirmation=confirmation)
        if decision.status == PermissionStatus.DENY:
            return ToolExecution(
                ToolResult(success=False, content="权限策略拒绝了该操作。", error=decision.reason_code),
                request=request,
            )
        self.gateway.record_execution(request, "tool_execution_started", "started")
        result = await tool.run(arguments)
        result.content = result.content[: self.max_output_chars]
        if result.data is not None:
            serialized_data = json.dumps(result.data, ensure_ascii=False, default=str)
            if len(serialized_data) > self.max_output_chars:
                result.data = {
                    "truncated": True,
                    "preview": serialized_data[: self.max_output_chars],
                }
        result.metadata = {
            **result.metadata,
            "trust": "untrusted_tool_output",
            "source_tool": name,
        }
        self.gateway.record_execution(
            request,
            "tool_execution_succeeded" if result.success else "tool_execution_failed",
            "success" if result.success else "failed",
        )
        return ToolExecution(result, request=request)
