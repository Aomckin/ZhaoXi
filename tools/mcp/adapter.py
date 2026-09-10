"""Adapt MCP tool descriptions and results to ordinary Zhaoxi Tools."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult
from tools.mcp.client import MCPError, MCPStdioClient


def _resolve_ref(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if not isinstance(reference, str) or not reference.startswith("#/"):
        return schema
    value: Any = root
    for component in reference[2:].split("/"):
        value = value[component.replace("~1", "/").replace("~0", "~")]
    return value if isinstance(value, dict) else schema


def _validate_json(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "arguments") -> None:
    schema = _resolve_ref(schema, root)
    if "const" in schema and value != schema["const"]:
        raise ValueError(f"{path} 必须等于 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} 不在允许值中")
    alternatives = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(alternatives, list):
        for alternative in alternatives:
            try:
                _validate_json(value, alternative, root, path)
                return
            except (ValueError, TypeError, KeyError):
                pass
        raise ValueError(f"{path} 不符合任何允许的结构")
    expected = schema.get("type")
    if isinstance(expected, list):
        if value is None and "null" in expected:
            return
        expected = next((item for item in expected if item != "null"), None)
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if expected in checks and not checks[expected](value):
        raise ValueError(f"{path} 类型必须为 {expected}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                raise ValueError(f"{path}.{required} 为必填项")
        if schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ValueError(f"{path} 包含未知字段：{sorted(unknown)}")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_json(item, child, root, f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_json(item, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            raise ValueError(f"{path} 太短")
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            raise ValueError(f"{path} 太长")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{path} 小于最小值")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{path} 大于最大值")


def input_model_for(schema: dict[str, Any], model_name: str) -> type[BaseModel]:
    frozen_schema = deepcopy(schema or {"type": "object", "properties": {}})

    class MCPInput(BaseModel):
        model_config = ConfigDict(extra="allow")

        @model_validator(mode="before")
        @classmethod
        def validate_mcp_schema(cls, value: Any) -> Any:
            _validate_json(value, frozen_schema, frozen_schema)
            return value

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return deepcopy(frozen_schema)

    MCPInput.__name__ = model_name
    return MCPInput


def public_tool_name(server_name: str, remote_name: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", f"mcp_{server_name}_{remote_name}").strip("_")
    if len(base) <= 64:
        return base
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:8]
    return f"{base[:55]}_{digest}"


class MCPTool(Tool):
    def __init__(self, client: MCPStdioClient, server_name: str, definition: dict[str, Any]) -> None:
        self.client = client
        self.server_name = server_name
        self.remote_name = str(definition["name"])
        self.name = public_tool_name(server_name, self.remote_name)
        remote_description = str(definition.get("description") or self.remote_name)
        self.description = f"[{server_name}] {remote_description}"
        self._schema = deepcopy(definition.get("inputSchema") or {"type": "object"})
        self.input_model = input_model_for(self._schema, f"MCP_{self.name}_Input")
        annotations = definition.get("annotations") or {}
        if annotations.get("readOnlyHint") is True:
            self.permission = PermissionLevel.READ
            self.side_effects = frozenset({SideEffect.NONE})
        elif annotations.get("destructiveHint") is True:
            self.permission = PermissionLevel.DELETE
            self.side_effects = frozenset({SideEffect.DATA_DELETION})
        else:
            self.permission = PermissionLevel.WRITE
            effect = SideEffect.EXTERNAL_SERVICE_WRITE if annotations.get("openWorldHint", True) else SideEffect.LOCAL_STATE
            self.side_effects = frozenset({effect})

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": deepcopy(self._schema),
            },
        }

    def resource_scope(self, arguments: dict[str, Any]) -> str:
        return f"mcp:{self.server_name}:{self.remote_name}"

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        return f"通过 {self.server_name} 执行 {self.remote_name}"

    async def execute(self, arguments: BaseModel) -> ToolResult:
        payload = arguments.model_dump(mode="json")
        try:
            result = await asyncio.to_thread(self.client.call_tool, self.remote_name, payload)
        except MCPError as exc:
            return ToolResult(
                success=False,
                content=str(exc),
                error="mcp_call_failed",
                metadata={"provider": self.server_name, "remote_tool": self.remote_name},
            )
        content_items = result.get("content") or []
        text_parts = [
            str(item.get("text"))
            for item in content_items
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None
        ]
        structured = result.get("structuredContent")
        content = "\n".join(text_parts).strip()
        if not content:
            content = json.dumps(structured if structured is not None else content_items, ensure_ascii=False, default=str)
        return ToolResult(
            success=not bool(result.get("isError")),
            content=content,
            data=structured,
            error="mcp_tool_error" if result.get("isError") else None,
            metadata={"provider": self.server_name, "remote_tool": self.remote_name},
        )
