"""Read only the source evidence behind social context references."""
from pydantic import BaseModel,Field
from zhaoxi.tools.base import Tool,ToolResult
from zhaoxi.cognitive_stream.social_trace import SocialTraceReader
from zhaoxi.cognitive_stream.turn import current_turn

class ReadSocialContextInput(BaseModel):
    reference: str = Field(min_length=1,max_length=200)
    statement_id: str | None = Field(default=None,min_length=1,max_length=40)
    offset: int = Field(default=0,ge=0,le=2000)
    text_offset: int = Field(default=0,ge=0,le=200000)
    limit: int = Field(default=8,ge=1,le=20)
    max_chars: int = Field(default=6000,ge=200,le=16000)
    include_images: bool = False

class ReadSocialContextTool(Tool):
    name="read_social_context"
    group="social_context"
    persistent=True
    aliases=("群聊原文","群聊摘要","原消息","展开证据")
    description="按 SocialTrace ref 回查群聊原消息，可用 statement_id 展开摘要某一句的证据；支持分页，include_images 可查看缓存的历史图片。摘要不是原文，缺失不猜测；外部调用仅限当前群，无发送或写入能力。"
    input_model=ReadSocialContextInput

    def __init__(self,stream,*,max_output_chars=8000):
        self.reader=SocialTraceReader(stream)
        self.max_output_chars=max_output_chars

    async def execute(self,arguments):
        values=arguments.model_dump(exclude={"include_images"})
        result=self.reader.read(**values,turn=current_turn())
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
