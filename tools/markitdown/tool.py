"""Zhaoxi Tool wrapper around the isolated MarkItDown installation."""

from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
from typing import Any

from pydantic import BaseModel, Field

from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult


class MarkItDownInput(BaseModel):
    input_path: str = Field(description="要转换的本地文件路径。")
    output_path: str | None = Field(
        default=None,
        description="可选的 Markdown 输出路径；省略时直接返回转换后的 Markdown。",
    )


class MarkItDownTool(Tool):
    name = "markitdown_convert"
    description = (
        "把本地 PDF、Word、PowerPoint、Excel、HTML、CSV、JSON、XML、图片、音频、"
        "EPUB 或 ZIP 文件转换为 Markdown。只接受本地文件路径。"
    )
    input_model = MarkItDownInput
    group = "documents"
    source = "markitdown-tool"
    aliases = ("MarkItDown", "文档转 Markdown", "文件转 Markdown")
    intents = (
        "把这个文件转成 Markdown",
        "提取 PDF 内容",
        "读取 Word 文档",
        "解析 PPT",
        "解析 Excel",
    )

    def __init__(self, executable: Path | None = None) -> None:
        package_root = Path(__file__).resolve().parent
        self.executable = executable or package_root / ".venv" / "Scripts" / "markitdown.exe"
        self.available = self.executable.is_file()

    def permission_for(self, arguments: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.WRITE if arguments.get("output_path") else PermissionLevel.READ

    def side_effects_for(self, arguments: dict[str, Any]) -> frozenset[SideEffect]:
        if arguments.get("output_path"):
            return frozenset({SideEffect.LOCAL_STATE})
        return frozenset({SideEffect.NONE})

    def resource_scope(self, arguments: dict[str, Any]) -> str:
        target = arguments.get("output_path") or arguments.get("input_path", "unknown")
        return f"path:{target}"

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        if arguments.get("output_path"):
            return "将文档转换为 Markdown 并写入本地文件"
        return "读取本地文档并转换为 Markdown"

    @staticmethod
    def _validated_local_file(raw_path: str) -> Path:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"输入文件不存在或不是普通文件：{path}")
        return path

    def _convert(self, input_path: Path, output_path: Path | None) -> subprocess.CompletedProcess[str]:
        command = [str(self.executable), str(input_path)]
        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            command.extend(["-o", str(output_path)])
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    async def execute(self, arguments: MarkItDownInput) -> ToolResult:
        if not self.available:
            return ToolResult(
                success=False,
                content="MarkItDown 尚未安装或本地虚拟环境不可用。",
                error=f"executable_not_found:{self.executable}",
            )

        try:
            input_path = self._validated_local_file(arguments.input_path)
            output_path = Path(arguments.output_path).expanduser().resolve() if arguments.output_path else None
            result = await asyncio.to_thread(self._convert, input_path, output_path)
        except OSError as exc:
            return ToolResult(success=False, content="无法读取或转换该本地文件。", error=str(exc))

        if result.returncode != 0:
            error = result.stderr.strip() or f"MarkItDown exited with code {result.returncode}"
            return ToolResult(success=False, content="MarkItDown 转换失败。", error=error)

        metadata = {
            "input_path": str(input_path),
            "format": input_path.suffix.lower(),
            "converter": "markitdown",
        }
        if output_path is not None:
            metadata["output_path"] = str(output_path)
            return ToolResult(
                success=True,
                content=f"已转换并写入：{output_path}",
                data={"output_path": str(output_path)},
                metadata=metadata,
            )

        markdown = result.stdout
        return ToolResult(
            success=True,
            content="已将本地文件转换为 Markdown。",
            data={"markdown": markdown},
            metadata=metadata,
        )
