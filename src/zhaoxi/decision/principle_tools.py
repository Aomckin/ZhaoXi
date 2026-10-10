"""Main-model summary writes with verified user-archive provenance."""
from datetime import UTC, datetime
from pydantic import Field
from .learning_models import LearningModel, require_owner
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult


class PrincipleWrite(LearningModel):
    id: str = Field(pattern=r"^[\w-]+$", max_length=100)
    statement: str = Field(min_length=1, max_length=1200)
    domain: str = Field(default='general', max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    source_ref: str = Field(min_length=1, max_length=500, description='read_decision_context 返回的 archive:user/...:L行号')
    source_quote: str = Field(min_length=1, max_length=1000, description='对应片段中逐字引用的原文，不能改写或编造')
    status: str = Field(default='active', pattern='^(active|retired)$')


def save_principle(awareness, arguments, *, actor):
    require_owner()
    if not awareness.user_principles or not awareness.principle_archive:
        raise ValueError('准则索引尚未启用。')
    source = awareness.principle_archive.evidence(arguments.source_ref, arguments.source_quote)
    return awareness.user_principles.save({
        'id': arguments.id, 'statement': arguments.statement, 'domain': arguments.domain,
        'tags': arguments.tags, 'source': source, 'origin': actor,
        'confidence': .7 if actor == 'zhaoxi_summary' else 1,
        'status': arguments.status, 'updated_at': datetime.now(UTC).isoformat(),
    }, actor=actor)


class WriteUserPrinciple(Tool):
    name = 'write_user_principle'
    description = ('读取 archive/user 原文后，把值得复用的准则抽象摘要保存或更新到 User Principles 索引。'
                   'source_ref 与 source_quote 必须来自实际原文。稳定 id 用于修订，保留条件和例外，'
                   '不得把自己的推断说成用户确认；实际判断优先回查原文。不会修改 archive 原文。')
    input_model = PrincipleWrite
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False
    persistent = True
    group = 'decision_context'

    def __init__(self, awareness):
        self.awareness = awareness

    async def execute(self, arguments):
        value = save_principle(self.awareness, arguments, actor='zhaoxi_summary')
        return ToolResult(success=True, content='已保存朝汐整理的准则摘要及原文依据，可在判断与成长中查看。', data=value)
