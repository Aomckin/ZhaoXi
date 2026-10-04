"""Decision learning reuses Presence, budgets, foreground preemption and receipts."""
from ..models import ActivitySpec, ActivityResult, ActivityCategory as Category, CostClass as Cost, PresenceState as Presence

FOLLOW_UP = 'decision_follow_up'
REFLECTION = 'decision_reflection'
GARDENING = 'decision_journal_gardening'


async def reflection_due(r, now):
    learning = getattr(r.agent, 'decision_learning', None)
    if learning and learning.pending():
        return 'outcome_feedback', Cost.LLM_LIGHT.value


async def reflect(r, kind):
    learning = getattr(r.agent, 'decision_learning', None)
    rows = learning.pending() if learning else []
    if not rows:
        return ActivityResult(summary='没有待整理的结果反馈。')
    requested = [row for row in rows if row.get('reflection_requested_at')]
    row = requested[-1] if requested else rows[-1]
    result = await learning.reflect(row['decision_id'])
    return ActivityResult(status='UPDATE', changed=True, summary=result['summary'] or result['reason'] or '已整理这次反馈。',
        evidence_refs=[result['decision_id'], result['feedback_id']],
        details=[{'label': '判断经验', 'text': result['statement'] or result['reason'],
                  'target_id': result.get('target_journal_id')}])


async def follow_up_due(r, now):
    service = getattr(r.agent, 'decision_follow_up', None)
    if service and service.budget_allowed(now) and service.candidates(now):
        return 'due_decision', Cost.LOCAL_LIGHT.value


async def follow_up(r, kind):
    service = getattr(r.agent, 'decision_follow_up', None)
    rows = service.candidates(opportunistic=bool(r._manual), manual=bool(r._manual)) if service else []
    if target := getattr(r, 'decision_follow_up_target', None):
        rows = [row for row in rows if row['decision_id'] == target]
    if not rows:
        return ActivityResult(summary='没有值得现在回访的选择。')
    deliveries = await service.ask(rows[0], r, manual=bool(r._manual))
    return ActivityResult(message_sent=bool(deliveries), changed=bool(deliveries), deliveries=deliveries,
        summary='已自然询问之前选择的结果。' if deliveries else '现在不适合打扰，留待合适时机。',
        evidence_refs=[rows[0]['decision_id']])


async def garden_due(r, now):
    learning = getattr(r.agent, 'decision_learning', None)
    if learning and learning.journal.list():
        return 'review_experience', Cost.LOCAL_LIGHT.value


async def garden(r, kind):
    learning = getattr(r.agent, 'decision_learning', None)
    changes = learning.journal.garden() if learning else []
    return ActivityResult(changed=bool(changes), summary=f'整理判断经验，调整 {len(changes)} 项。', details=changes)


def register_decision_learning(registry, settings):
    if not getattr(settings, 'decision_learning_enabled', False) or getattr(settings, 'decision_mode', 'legacy') != 'agency':
        return
    awake = frozenset({Presence.SEMI_ACTIVE, Presence.IDLE})
    for spec in (
        ActivitySpec(FOLLOW_UP, Category.PROACTIVE, Cost.LOCAL_LIGHT,
            frozenset({Presence.ACTIVE, Presence.SEMI_ACTIVE}), 45,
            settings.decision_follow_up_min_interval_minutes, follow_up, follow_up_due,
            can_message_user=True, daily_limit_setting='decision_follow_up_daily_limit', label='翻翻之前的选择'),
        ActivitySpec(REFLECTION, Category.COGNITION, Cost.LLM_LIGHT, awake, 64, 10,
            reflect, reflection_due, requires_llm=True, label='整理判断经验'),
        ActivitySpec(GARDENING, Category.MAINTENANCE, Cost.LOCAL_LIGHT, awake, 55, 1440,
            garden, garden_due, label='翻看判断日记')):
        registry.register(spec)
