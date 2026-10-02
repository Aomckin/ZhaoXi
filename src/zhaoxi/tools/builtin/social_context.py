"""Read only the source evidence behind social context references."""
from datetime import UTC, datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from zhaoxi.tools.base import Tool,ToolResult
from zhaoxi.cognitive_stream.social_trace import SocialTraceReader
from zhaoxi.cognitive_stream.turn import current_turn

class ReadSocialContextInput(BaseModel):
    reference: str | None = Field(default=None,min_length=1,max_length=200,
        description="SocialTrace 的事件 ID、QQ 原消息 raw_ref 或 TimelineUnit ID（turn:/ambient:）；不接受会话 ID（如 qq/group/...）。")
    statement_id: str | None = Field(default=None,min_length=1,max_length=40)
    query: str | None = Field(default=None, min_length=1, max_length=300,
        description="搜索原消息正文中的字面关键词；不搜索摘要或元数据。")
    group_id: str | None = Field(default=None, min_length=1, max_length=100,
        description="QQ 群号；本地 Owner 可指定，QQ 回复始终限定当前群。")
    source_plugin: str | None = Field(default=None, min_length=1, max_length=100)
    since: datetime | None = Field(default=None, description="开始时间（含），ISO 8601，必须带时区。")
    until: datetime | None = Field(default=None, description="结束时间（不含），ISO 8601，必须带时区。")
    offset: int = Field(default=0,ge=0,le=200000)
    text_offset: int = Field(default=0,ge=0,le=200000)
    limit: int = Field(default=8,ge=1,le=20)
    max_chars: int = Field(default=6000,ge=200,le=16000)
    include_images: bool = False

    @field_validator("reference", "query", "group_id", "source_plugin")
    @classmethod
    def nonblank(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("查询条件不能为空")
        return value

    @field_validator("since", "until")
    @classmethod
    def aware_time(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("查询时间必须包含时区")
            return value.astimezone(UTC)
        return value

    @model_validator(mode="after")
    def valid_mode(self):
        search = any(value is not None for value in (self.query, self.group_id, self.source_plugin, self.since, self.until))
        if self.reference and search:
            raise ValueError("按引用展开与条件搜索不能混用")
        if not self.reference and not search:
            raise ValueError("需要 reference 或搜索条件")
        if self.statement_id and not self.reference:
            raise ValueError("statement_id 只用于按引用展开")
        if self.since and self.until and self.since >= self.until:
            raise ValueError("开始时间必须早于结束时间")
        return self

class ReadSocialContextTool(Tool):
    name="read_social_context"
    group="social_context"
    persistent=True
    aliases=("群聊原文","群聊摘要","原消息","展开证据","搜索群聊","群聊历史")
    description="回查已保存的 QQ 群原消息：提供 reference 展开 SocialTrace（statement_id 可指定一句），或不提供 reference，改用 query 关键词、group_id 群号、since/until 带时区的时间搜索。结果按新到旧分页，返回可继续展开的引用；include_images 可查看缓存历史图片。兼容现存旧 Perception 记录，缺失不猜测。QQ 外部调用仅限当前群及插件，无发送或写入能力。"
    input_model=ReadSocialContextInput

    def __init__(self,stream,*,max_output_chars=8000,perception_path=None):
        self.reader=SocialTraceReader(stream, perception_path)
        self.max_output_chars=max_output_chars

    async def execute(self,arguments):
        values=arguments.model_dump(exclude={"include_images", "reference", "statement_id", "query", "group_id", "source_plugin", "since", "until"})
        if arguments.reference:
            result=self.reader.read(arguments.reference, statement_id=arguments.statement_id, **values, turn=current_turn())
        else:
            result=self.reader.search(query=arguments.query, group_id=arguments.group_id,
                source_plugin=arguments.source_plugin, since=arguments.since, until=arguments.until,
                **values, turn=current_turn())
        import json
        # Preserve a valid structured page instead of the executor's JSON preview.
        while len(json.dumps(result,ensure_ascii=False))>self.max_output_chars and result.get("records"):
            records=result["records"]
            if len(records)>1:
                records.pop()
                result["next_offset"]=arguments.offset+len(records)
                result["next_text_offset"]=0
            else:
                record=records[0]
                overflow=len(json.dumps(result,ensure_ascii=False))-self.max_output_chars
                if len(record["content"])<=overflow:
                    result={"status":"output_budget","records":[],"notice":"回查输出预算不足，请减少页大小或使用 Debug 原文回查。"}
                    break
                record["content"]=record["content"][:-overflow-100]
                record["truncated"]=True
                result["next_offset"]=arguments.offset
                result["next_text_offset"]=record["text_offset"]+len(record["content"])
            result["status"]="partial"
        return ToolResult(success=result["status"] in {"complete","partial"},content=result.get("notice",result["status"]),
            data=result,error=None if result["status"] in {"complete","partial"} else result["status"],
            metadata={"include_social_images":arguments.include_images,"source_kind":"social_evidence"})
