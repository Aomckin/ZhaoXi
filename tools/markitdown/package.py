"""Discovery boundary for the MarkItDown Tool Package."""

from pathlib import Path

from zhaoxi.sdk import CapabilityDeclaration

from tools.markitdown.tool import MarkItDownTool


class MarkItDownToolPackage:
    package_id = "markitdown-tool"
    package_version = "0.1.0"
    requires_sdk = ">=1,<2"

    def capability_declaration(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(tool=True, router_hints=True)

    def create_tools(self, config: dict[str, object]):
        return [MarkItDownTool()]

    def workflow_paths(self) -> list[Path]:
        return []

    def routing_hints(self) -> list[dict[str, object]]:
        return [
            {
                "markers": [
                    "转成 markdown",
                    "转为 markdown",
                    "文件转 markdown",
                    "文档转 markdown",
                    "提取 pdf",
                    "解析 pdf",
                    "解析 word",
                    "解析 ppt",
                    "解析 excel",
                    "markitdown",
                ],
                "route": "tool",
                "group": "documents",
            }
        ]

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "MarkItDown",
            "description": "把本地文档和常见媒体文件转换为适合模型处理的 Markdown。",
            "tools": ["markitdown_convert"],
            "examples": [
                "把这份 PDF 转成 Markdown",
                "读取这个 Word 文档的内容",
                "将这个 Excel 转为 Markdown 文件",
            ],
        }

    def reflection_sources(self) -> list[object]:
        return []

    def health_check(self, config: dict[str, object]) -> dict[str, object]:
        tool = MarkItDownTool()
        return {
            "configured": True,
            "reachable": tool.available,
            "healthy": tool.available,
        }


def create_package() -> MarkItDownToolPackage:
    return MarkItDownToolPackage()
