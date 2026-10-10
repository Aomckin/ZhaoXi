"""Authenticated local Decision Learning control plane."""
from datetime import UTC, datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import ConfigDict, Field
from zhaoxi.decision.models import ChoiceFeedback
from zhaoxi.decision.learning_models import LearningModel
from zhaoxi.decision.principle_tools import PrincipleWrite, save_principle
from zhaoxi.internal_activity.models import ActivitySpec, ActivityCategory, CostClass
from zhaoxi.internal_activity.receipt import build_receipt
from zhaoxi.internal_activity.models import ActivityResult


class JournalEdit(LearningModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, max_length=100)
    statement: str | None = Field(default=None, min_length=1, max_length=1200)
    rationale: str | None = Field(default=None, max_length=1200)
    conditions: list[str] | None = Field(default=None, max_length=20)
    exceptions: list[str] | None = Field(default=None, max_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal['ACTIVE', 'UNCERTAIN', 'CONFLICTED', 'STALE', 'RETIRED'] | None = None
    manual_state: Literal['NORMAL', 'PINNED', 'LOCKED', 'RETIRED'] | None = None


class FeedbackRequest(ChoiceFeedback):
    model_config = ConfigDict(extra='forbid')
    decision_id: str = ''


def decision_learning_router(core):
    def owner_access():
        from zhaoxi.decision.learning_models import private_owner
        if not private_owner():
            raise HTTPException(403, '个人决策资料仅供 Owner 私密会话使用。')
    router = APIRouter(prefix='/api/decision', dependencies=[Depends(owner_access)])

    def services():
        learning = getattr(core, 'decision_learning', None)
        if learning is None:
            raise HTTPException(409, 'Decision Learning 尚未启用。')
        return learning

    def decision(identity):
        row = services().history.get(identity)
        if row is None or not row['scope'].startswith('owner:'):
            raise HTTPException(404, '选择记录不存在。')
        return row

    def journal(identity):
        row = services().journal.get(identity)
        if row is None:
            raise HTTPException(404, '判断日记不存在。')
        return row

    def receipt(label, summary, data, *, changed=True, details=None):
        spec = ActivitySpec('decision_manual', ActivityCategory.LOCAL, CostClass.LOCAL_LIGHT,
            frozenset(), 0, 0, None, None, label=label)
        return {'receipt': build_receipt(spec, result=ActivityResult(changed=changed, summary=summary,
            details=details or []), trigger='MANUAL').diagnostics(), 'data': data}

    @router.get('/history')
    async def history(limit: int = Query(50, ge=1, le=1000)):
        return {'items': services().history.list(limit=limit)}

    @router.get('/history/{identity}')
    async def history_detail(identity: str):
        return decision(identity)

    @router.post('/history/{identity}/feedback')
    async def feedback(identity: str, body: FeedbackRequest):
        row = decision(identity)
        if body.decision_id and body.decision_id != identity:
            raise HTTPException(422, '反馈 ID 与记录不一致。')
        if body.outcome_label is None and body.outcome is None and body.user_final_choice is None:
            raise HTTPException(422, '请填写最终选择或结果反馈。')
        saved = services().history.feedback(identity, body.user_final_choice, scope=row['scope'],
            overridden=body.overridden, outcome=body.outcome, outcome_label=body.outcome_label,
            outcome_text=body.outcome_text, feedback_source='explicit')
        return receipt('保存结果反馈', '已保存反馈；后台会在合适状态整理判断经验。', saved)

    @router.post('/history/{identity}/follow-up/skip')
    @router.post('/history/{identity}/follow-up/cancel')
    async def skip(identity: str):
        decision(identity)
        value = core.decision_follow_up.skip(identity)
        return receipt('取消回访', '这条选择不再主动回访。', value)

    @router.post('/history/{identity}/follow-up/ask')
    async def ask(identity: str):
        decision(identity)
        r = getattr(core, 'internal_activity', None)
        if not r:
            raise HTTPException(409, '内部活动尚未就绪。')
        # Target selection is request-local on the runtime; no bypass of Presence,
        # cooldown or budget. Concurrent manual requests return busy.
        if r.lock.locked():
            raise HTTPException(409, '已有后台活动正在执行。')
        r.decision_follow_up_target = identity
        try:
            result = await r.run_manual('decision_follow_up')
        finally:
            r.decision_follow_up_target = None
        return {'receipt': result}

    @router.post('/history/{identity}/reflect')
    async def reflect(identity: str):
        row = decision(identity)
        if not row.get('feedback'):
            raise HTTPException(422, '这条选择还没有结果反馈。')
        existing = next((item for item in services().journal.reflections() if item['feedback_id'] == row['feedback']['id']), None)
        if existing:
            return receipt('整理结果反馈', '这条反馈已经完成反思，可查看日记与反思记录。', existing, changed=False)
        services().history.event(identity, 'reflection_request', scope=row['scope'],
                                  reflection_requested_at=datetime.now(UTC).isoformat())
        return receipt('整理结果反馈', '已加入后台反思队列，完成后可查看反思记录与活动回执。', row)

    @router.get('/reflections')
    async def reflections():
        return {'items': services().journal.reflections()[:100], 'review_candidates': services().journal.review_candidates()}

    @router.get('/journal')
    async def journals():
        return {'items': services().journal.list(include_retired=True)}

    @router.post('/journal')
    async def create(body: JournalEdit):
        values = body.model_dump(exclude_none=True)
        if not values.get('title') or not values.get('statement'):
            raise HTTPException(422, '请填写标题和经验内容。')
        value = services().journal.create(values)
        return receipt('新增判断经验', '已保存 Owner 手工整理的判断经验。', value)

    @router.get('/journal/{identity}')
    async def journal_detail(identity: str):
        return {**journal(identity), 'revisions': services().journal.revisions(identity)}

    @router.patch('/journal/{identity}')
    async def edit(identity: str, body: JournalEdit):
        journal(identity)
        values = body.model_dump(exclude_unset=True)
        if any(v is None for v in values.values()):
            raise HTTPException(422, '编辑字段不能为 null。')
        value = services().journal.edit(identity, values)
        return receipt('编辑判断经验', '已保存修改及修订记录。', value)

    @router.post('/journal/{identity}/retire')
    async def retire(identity: str):
        journal(identity)
        value = services().journal.edit(identity, {'manual_state': 'RETIRED', 'status': 'RETIRED'}, operation='RETIRE')
        return receipt('退役判断经验', '此经验已退役，按需检索不再返回。', value)

    @router.delete('/journal/{identity}')
    async def delete(identity: str):
        journal(identity)
        services().journal.delete(identity)
        return receipt('删除判断经验', '已从当前日记移除；修订记录保留。', {'id': identity})

    @router.get('/user-principles')
    async def principles(query: str = Query('', max_length=500), principle_id: str = Query('', max_length=100)):
        learning = services()
        awareness = core.decision_awareness
        rows = learning.principles.list()
        for row in rows:
            row['recent_used_at'] = next((h['timestamp'] for h in learning.history.list(limit=1000)
                                         if row['id'] in h.get('principle_ids', [])), None)
        for row in rows:
            row['source_status'] = awareness.principle_archive.source_status(row)
        fragments = awareness.principle_archive.fragments(query, 5, user_only=True) if query else []
        if principle_id:
            selected = next((r for r in rows if r['id'] == principle_id), None)
            if selected is None:
                raise HTTPException(404, '用户准则不存在。')
            fragments = awareness.principle_archive.source_fragment(selected)
        return {'items': rows, 'archive_fragments': fragments}

    @router.post('/user-principles')
    async def save_summary(body: PrincipleWrite):
        services()
        try:
            value = save_principle(core.decision_awareness, body, actor='owner')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return receipt('保存准则摘要', '已保存摘要索引及原文依据，原始资料保持完整。', value)

    @router.get('/user-principles/{identity}/revisions')
    async def principle_revisions(identity: str):
        return {'items': services().principles.revisions(identity)}

    return router
