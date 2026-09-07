"""Read-only tools for listing, searching and reading Tidecourt Archive documents."""

from pydantic import BaseModel, Field

from zhaoxi.archive.models import ArchiveAuthority, ArchiveScope
from zhaoxi.archive.service import ArchiveNotFoundError, ArchiveService
from zhaoxi.permission.models import PermissionLevel
from zhaoxi.tools.base import Tool, ToolResult


class ListDocumentsInput(BaseModel):
    scope: ArchiveScope | None = None
    type: str | None = Field(default=None, min_length=1, max_length=80)
    authority: ArchiveAuthority | None = None
    limit: int = Field(default=50, ge=1, le=100)


class SearchDocumentsInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    scope: ArchiveScope | None = None
    type: str | None = Field(default=None, min_length=1, max_length=80)
    authority: ArchiveAuthority | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    max_chars: int | None = Field(default=None, ge=200, le=20_000)


class ReadDocumentInput(BaseModel):
    document_id: str = Field(min_length=1, max_length=160)
    section: str | None = Field(default=None, min_length=1, max_length=300)
    max_chars: int | None = Field(default=None, ge=200, le=50_000)


class ArchiveListDocumentsTool(Tool):
    name = "archive_list_documents"
    description = "列出潮庭书库中的本地正式文档，可按 scope、type、authority 筛选；只返回元数据。"
    input_model = ListDocumentsInput
    permission = PermissionLevel.READ

    def __init__(self, service: ArchiveService) -> None:
        self.service = service

    async def execute(self, arguments: ListDocumentsInput) -> ToolResult:
        documents = self.service.list_documents(**arguments.model_dump())
        return ToolResult(
            success=True,
            content=f"潮庭书库中找到 {len(documents)} 份文档。",
            data=[item.model_dump(mode="json") for item in documents],
            metadata={"source_kind": "tidecourt_archive"},
        )


class ArchiveSearchTool(Tool):
    name = "archive_search"
    description = (
        "按需搜索潮庭书库的正式资料。询问朝汐自身设定、暗苟的长期资料、项目文档或其他长期事实，"
        "而当前上下文不能可靠回答时优先使用；结果标明 authority 与来源，找不到时不得猜测。"
    )
    input_model = SearchDocumentsInput
    permission = PermissionLevel.READ

    def __init__(self, service: ArchiveService) -> None:
        self.service = service

    async def execute(self, arguments: SearchDocumentsInput) -> ToolResult:
        results = self.service.search(**arguments.model_dump(exclude_none=True))
        content = (
            f"潮庭书库找到 {len(results)} 个相关片段。"
            if results
            else "潮庭书库中没有找到相关记录；请明确说明文档未记录，不要补全或猜测。"
        )
        return ToolResult(
            success=True,
            content=content,
            data=[item.model_dump(mode="json") for item in results],
            metadata={"source_kind": "tidecourt_archive"},
        )


class ArchiveReadTool(Tool):
    name = "archive_read"
    description = "按稳定 document_id 受限读取潮庭书库文档，可指定 heading/section；不能访问书库外路径。"
    input_model = ReadDocumentInput
    permission = PermissionLevel.READ

    def __init__(self, service: ArchiveService) -> None:
        self.service = service

    async def execute(self, arguments: ReadDocumentInput) -> ToolResult:
        try:
            result = self.service.read_document(**arguments.model_dump(exclude_none=True))
        except ArchiveNotFoundError as exc:
            return ToolResult(success=False, content=str(exc), error="archive_not_found")
        return ToolResult(
            success=True,
            content=(
                f"已从潮庭书库读取《{result.title}》"
                + (f"的“{result.section}”章节。" if result.section else "。")
            ),
            data=result.model_dump(mode="json"),
            metadata={"source_kind": "tidecourt_archive"},
        )


def create_archive_tools(service: ArchiveService) -> list[Tool]:
    return [ArchiveListDocumentsTool(service), ArchiveSearchTool(service), ArchiveReadTool(service)]
