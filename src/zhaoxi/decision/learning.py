"""Background, bounded reflection. No router, classifier, or user-principle writes."""
import asyncio
from datetime import UTC, datetime
import json
from zhaoxi.core.message import Message, Role
from zhaoxi.observability import llm_owner_scope
from .learning_models import DecisionJournalEntry, DecisionReflection, require_owner

REFLECTION_PROMPT = '''你在后台整理朝汐自己的判断经验，不负责前台回复，也不能修改用户准则。
仅根据提供的真实反馈、最终选择、建议和少量证据判断可归因性、可推广性。
不要虚构原因或用户偏好；一次普通 PICK 的好坏不值得建立长期经验。UNKNOWN、不可归因返回 learnable=false/journal_action=NONE。
GOOD 不必支持，BAD 不必反选；MIXED 优先补条件/例外。多次 NO_DIFFERENCE 可以学习减少分析、检索、澄清的成本，而不是学习选项偏好。
明确用户准则高于你的经验，冲突填 principle_conflicts，只供 Owner 复查。LOCKED/PINNED/RETIRED 尊重人工状态。
输出一个 DecisionReflection JSON 对象：decision_id, learnable, summary, lessons, conditions, exceptions,
journal_action(NONE/CREATE/SUPPORT/REFINE/WEAKEN/CONFLICT/RETIRE), target_journal_id, confidence_delta,
reason, title, domain, statement, source_decision_ids, principle_conflicts。
CREATE 必须解释为什么值得推广，含条件；SUPPORT 只加证据，REFINE 可修正正文/条件/例外；单次 confidence_delta 绝对值不超过0.15。
只引用本次输入中实际存在的 ID，source_decision_ids 应包含当前决策。'''


class DecisionLearning:
    def __init__(self, history, journal, principles, provider):
        self.history, self.journal, self.principles, self.provider = history, journal, principles, provider
        self._lock = asyncio.Lock()

    def pending(self):
        require_owner()
        committed = {r['feedback_id'] for r in self.journal.reflections()}
        return [r for r in self.history.feedback_rows() if r['feedback']['id'] not in committed or not r.get('reflected')]

    async def reflect(self, decision_id):
        require_owner()
        async with self._lock:
            row = self.history.get(decision_id)
            if not row or not row.get('feedback'):
                raise ValueError('这条选择还没有结果反馈。')
            feedback = row['feedback']
            existing = next((r for r in self.journal.reflections() if r['feedback_id'] == feedback['id']), None)
            if existing:
                self._mark(row, existing)
                return existing
            relevant = self.history.retrieve(row['summary'], scope=row['scope'], limit=6)
            entries = self.journal.retrieve(row['summary'], limit=5)
            entries_by_id = {e['id']: e for e in entries}
            for identity in row.get('journal_ids', []):
                entry = self.journal.get(identity)
                if entry and entry['status'] != 'RETIRED':
                    entries_by_id[identity] = entry
            entries = list(entries_by_id.values())[:8]
            principles = self.principles.list() if self.principles else []
            principles = [p for p in principles if p['id'] in row.get('principle_ids', [])][:8]
            if feedback['label'] == 'UNKNOWN':
                reflection = DecisionReflection(decision_id=decision_id, reason='结果尚未知，不学习。')
            else:
                fields = ('decision_id', 'summary', 'suggestion', 'mode', 'user_final_choice', 'feedback',
                          'context_refs', 'principle_ids', 'journal_ids')
                payload = {'decision': {k: row.get(k) for k in fields}, 'user_principles': principles,
                    'decision_journal': entries, 'related_history': [{k: r.get(k) for k in fields} for r in relevant]}
                with llm_owner_scope('decision_reflection', 'decision_learning'):
                    response = await self.provider.generate([Message(role=Role.SYSTEM, content=REFLECTION_PROMPT),
                        Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=False))],
                        None, temperature=0, max_tokens=2400, thinking={'type': 'disabled'}, reasoning_budget_tokens=1000,
                        response_format={'type': 'json_object'})
                raw = json.loads(response.content or '')
                reflection = DecisionReflection.model_validate(raw)
                if reflection.decision_id != decision_id:
                    raise ValueError('Reflection decision ID mismatch')
            # Recheck after awaiting the provider: feedback may have changed.
            latest = self.history.get(decision_id)
            if latest.get('feedback', {}).get('id') != feedback['id']:
                raise ValueError('Feedback changed during reflection; retry')
            reflection.feedback_id = feedback['id']
            reflection.source_decision_ids = list(dict.fromkeys([decision_id, *reflection.source_decision_ids]))
            allowed = {r['decision_id']: r for r in [row, *relevant] if r.get('feedback')}
            if any(identity not in allowed for identity in reflection.source_decision_ids):
                raise ValueError('Reflection invented evidence')
            known_principles = {p['id'] for p in principles}
            if set(reflection.principle_conflicts) - known_principles:
                raise ValueError('Reflection invented a user principle')
            reflection.confidence_delta = max(-.15, min(.15, reflection.confidence_delta))
            if not reflection.learnable or feedback['label'] == 'UNKNOWN':
                reflection.learnable = False
                reflection.journal_action = 'NONE'
            action = reflection.journal_action
            if action == 'CREATE':
                independent = [allowed[i] for i in reflection.source_decision_ids]
                if row['mode'] == 'PICK':
                    if feedback['label'] != 'NO_DIFFERENCE' or sum(
                        r['feedback']['label'] == 'NO_DIFFERENCE' for r in independent) < 3:
                        action = reflection.journal_action = 'NONE'
                if not reflection.statement or not reflection.reason or not reflection.conditions:
                    action = reflection.journal_action = 'NONE'
            before, entry = None, None
            if action == 'CREATE':
                entry = DecisionJournalEntry(title=reflection.title or reflection.summary[:200] or '判断经验',
                    domain=reflection.domain, statement=reflection.statement, rationale=reflection.reason,
                    conditions=reflection.conditions, exceptions=reflection.exceptions,
                    confidence=min(.65, .5 + reflection.confidence_delta), status='UNCERTAIN').model_dump(mode='json')
                reflection.target_journal_id = entry['id']
            elif action != 'NONE':
                before = entries_by_id.get(reflection.target_journal_id)
                if not before:
                    raise ValueError('Target journal was not supplied as evidence')
                if before['manual_state'] == 'RETIRED' or before['status'] == 'RETIRED':
                    action = reflection.journal_action = 'NONE'
                else:
                    entry = {**before}
            if entry:
                entry['source_decision_ids'] = list(dict.fromkeys(entry['source_decision_ids'] + reflection.source_decision_ids))[-200:]
                entry['source_feedback_ids'] = list(dict.fromkeys(entry['source_feedback_ids'] +
                    [allowed[i]['feedback']['id'] for i in reflection.source_decision_ids]))[-200:]
                entry['support_count'] += int(action in {'CREATE', 'SUPPORT'})
                entry['conflict_count'] += int(action in {'WEAKEN', 'CONFLICT'})
                entry['feedback_summary'] = reflection.summary
                entry['updated_at'] = entry['last_reviewed_at'] = datetime.now(UTC).isoformat()
                if entry['manual_state'] not in {'LOCKED', 'PINNED'}:
                    if action != 'CREATE':
                        entry['confidence'] = max(0, min(1, entry['confidence'] + reflection.confidence_delta))
                    if action == 'REFINE':
                        if reflection.statement:
                            entry['statement'] = reflection.statement
                        entry['conditions'] = list(dict.fromkeys(entry['conditions'] + reflection.conditions))[:20]
                        entry['exceptions'] = list(dict.fromkeys(entry['exceptions'] + reflection.exceptions))[:20]
                    if action in {'CONFLICT', 'WEAKEN', 'RETIRE'}:
                        entry['status'] = {'CONFLICT': 'CONFLICTED', 'WEAKEN': 'UNCERTAIN', 'RETIRE': 'RETIRED'}[action]
                    if reflection.principle_conflicts:
                        entry['status'] = 'CONFLICTED'
            if action == 'NONE':
                reflection.target_journal_id = None
            result = reflection.model_dump(mode='json')
            self.journal.commit(entry, before=before, operation=action, actor='REFLECTION', reflection=result,
                reviews=[{'principle_id': i, 'decision_id': decision_id, 'reason': reflection.reason}
                         for i in reflection.principle_conflicts])
            self._mark(row, result)
            return result

    def _mark(self, row, reflection):
        self.history.event(row['decision_id'], 'reflection', scope=row['scope'],
                           reflected=True, reflection_id=reflection['id'])
        if reflection.get('target_journal_id') and reflection['journal_action'] != 'NONE':
            self.history.event(row['decision_id'], 'journal_link', scope=row['scope'],
                journal_ids=list(dict.fromkeys(row.get('journal_ids', []) + [reflection['target_journal_id']])))
