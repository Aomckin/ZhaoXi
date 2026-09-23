"""The only production boundary for discovering and running tools."""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zhaoxi.errors import ToolNotFoundError
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import (
    InvocationOrigin,
    PendingConfirmation,
    PermissionLevel,
    PermissionRequest,
    PermissionStatus,
    SideEffect,
)
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.metadata import TOOL_GROUPS
from zhaoxi.tools.registry import ToolRegistry
from pydantic import ValidationError
from zhaoxi.reliability.security import UnsafeToolArgument, validate_tool_arguments


logger = logging.getLogger("TOOL")


def _validation_issues(exc: ValidationError) -> list[dict[str, str]]:
    """Return schema diagnostics without logging argument values or user content."""
    return [
        {
            "path": ".".join(str(part) for part in item.get("loc", ())) or "<root>",
            "type": str(item.get("type", "validation_error")),
        }
        for item in exc.errors(include_url=False, include_context=False, include_input=False)
    ]


@dataclass(slots=True)
class ToolExecution:
    result: ToolResult | None
    request: PermissionRequest | None = None
    confirmation: PendingConfirmation | None = None
    failure_kind: str | None = None
    safe_metadata: dict[str, object] | None = None

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
        filesystem_write_roots: tuple[Path, ...] = (),
    ) -> None:
        self.registry = registry
        self.gateway = gateway or PermissionGateway()
        self.max_output_chars = max_output_chars
        self.filesystem_write_roots = filesystem_write_roots

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
        if not self.registry.usable(name):
            return ToolExecution(ToolResult(success=False, content="这把钥匙已停用或当前依赖不可用。", error="tool_unavailable"))
        try:
            normalized_arguments = tool.input_model.model_validate(arguments).model_dump(mode="json")
        except ValidationError as exc:
            schema = tool.input_model.model_json_schema()
            properties = schema.get("properties", {})
            issues = _validation_issues(exc)
            for issue in issues:
                raw_path = issue["path"]
                if raw_path not in properties and raw_path != "<root>":
                    issue["path"] = "<unknown>"
                field = properties.get(raw_path, {})
                if "$ref" in field:
                    field = schema.get("$defs", {}).get(field["$ref"].rsplit("/", 1)[-1], field)
                issue["expected_type"] = str(field.get("type") or field.get("$ref") or "unknown")
                if "enum" in field:
                    issue["allowed_enum"] = field["enum"]
            safe_metadata = {
                "issues": issues,
                "supplied_keys": sorted(
                    str(key) if key in properties or key in {"kind", "notes", "time"}
                    else "unknown:" + hashlib.sha256(str(key).encode()).hexdigest()[:8]
                    for key in arguments
                ),
                "schema_hash": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()[:16],
            }
            logger.warning(
                "request=%s step=%s tool=%s validation_failed metadata=%s",
                request_id,
                step_id,
                name,
                json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":")),
            )
            return ToolExecution(
                ToolResult(success=False, content="工具参数无效。", error="tool_validation_error"),
                failure_kind="validation", safe_metadata=safe_metadata,
            )
        arguments = normalized_arguments
        permission = tool.permission_for(arguments)
        side_effects = tool.side_effects_for(arguments)
        if permission is PermissionLevel.READ and side_effects != frozenset({SideEffect.NONE}):
            return ToolExecution(ToolResult(success=False, content="工具权限声明无效。", error="invalid_tool_policy"))
        if permission is not PermissionLevel.READ and side_effects == frozenset({SideEffect.NONE}):
            return ToolExecution(ToolResult(success=False, content="工具权限声明无效。", error="invalid_tool_policy"))
        try:
            write_roots = (
                self.filesystem_write_roots
                if tool.group == "filesystem_write" or name in TOOL_GROUPS["filesystem_write"]
                else ()
            )
            validate_tool_arguments(arguments, allowed_path_roots=write_roots)
        except UnsafeToolArgument as exc:
            return ToolExecution(
                ToolResult(success=False, content="工具参数触发安全限制。", error=str(exc))
            )
        canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        request = PermissionRequest(
            invocation_id=invocation_id or "",
            request_id=request_id,
            tool_name=name,
            permission=permission,
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
            permission=permission,
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
        decision, confirmation = self.gateway.evaluate(
            request,
            confirm_write=(
                self.registry.write_confirmation_required(name)
                if permission is PermissionLevel.WRITE
                else None
            ),
        )
        if confirmation:
            return ToolExecution(None, request=request, confirmation=confirmation)
        if decision.status == PermissionStatus.DENY:
            return ToolExecution(
                ToolResult(success=False, content="权限策略拒绝了该操作。", error=decision.reason_code),
                request=request,
            )
        self.gateway.record_execution(request, "tool_execution_started", "started")
        result = await tool.run(arguments)
        if (
            permission is not PermissionLevel.READ
            and result.metadata.get("retryable")
            and not result.metadata.get("safe_to_replay")
        ):
            result.metadata["retryable"] = False
            result.metadata["unknown_outcome"] = True
            result.error = result.error or "needs_reconciliation"
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
