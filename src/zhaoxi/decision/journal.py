"""Journal transactions include their revision and reflection in one JSONL event.

The journal is authoritative. Reflection/revision sidecars are repairable indexes,
so interruption between writes cannot commit half a learned experience.
"""
from datetime import UTC, datetime, timedelta
import logging
from pathlib import Path
from threading import RLock
from .history import read_rows, append_row
from .learning_models import DecisionJournalEntry, require_owner
from .principles import relevance

logger = logging.getLogger('DECISION')


class DecisionJournalStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self._lock = RLock()

    def transactions(self):
        require_owner()
        return read_rows(self.directory / 'decision_journal.jsonl')

    def list(self, *, include_retired=False):
        require_owner()
        entries = {}
        for row in self.transactions():
            if row.get('entry_id'):
                if row.get('after') is None:
                    entries.pop(row['entry_id'], None)
                else:
                    entries[row['entry_id']] = row['after']
        return sorted([r for r in entries.values() if include_retired or
            r['status'] != 'RETIRED' and r['manual_state'] != 'RETIRED'],
            key=lambda r: r['updated_at'], reverse=True)

    def get(self, identity):
        return next((r for r in self.list(include_retired=True) if r['id'] == identity), None)

    def retrieve(self, query, limit=5):
        rows = [(relevance(query, ' '.join([r['title'], r['statement'], r['domain'], *r['conditions']])), r)
                for r in self.list()]
        rows.sort(key=lambda x: (-x[0], -x[1]['confidence']))
        return [r for score, r in rows if score][:limit]

    def reflections(self):
        return [r['reflection'] for r in reversed(self.transactions()) if r.get('reflection')]

    def revisions(self, identity=None):
        return [{k: v for k, v in r.items() if k != 'reflection'} for r in reversed(self.transactions())
                if r.get('entry_id') and (identity is None or r['entry_id'] == identity)]

    def review_candidates(self):
        rows = {}
        for tx in self.transactions():
            for review in tx.get('reviews', []):
                target = rows.setdefault(review['principle_id'], {'principle_id': review['principle_id'],
                    'reason': review['reason'], 'source_decision_ids': [], 'status': 'CANDIDATE'})
                if review['decision_id'] not in target['source_decision_ids']:
                    target['source_decision_ids'].append(review['decision_id'])
        # Repeated independently observed conflicts, never change a principle.
        return [r for r in rows.values() if len(r['source_decision_ids']) >= 2]

    def commit(self, entry, *, operation, actor, reflection=None, reviews=None, before=None):
        require_owner()
        with self._lock:
            if reflection and any(r['feedback_id'] == reflection['feedback_id'] for r in self.reflections()):
                return next(r for r in self.reflections() if r['feedback_id'] == reflection['feedback_id'])
            if entry is not None:
                entry = DecisionJournalEntry.model_validate(entry).model_dump(mode='json')
                identity = entry['id']
                current = self.get(identity)
                if before is not None and current != before:
                    raise ValueError('Journal changed during reflection; retry with current evidence')
                before = current
            else:
                identity = before['id'] if before else None
            tx = {'entry_id': identity, 'operation': operation, 'before': before, 'after': entry,
                'actor': actor, 'timestamp': datetime.now(UTC).isoformat(),
                'reflection': reflection, 'reviews': reviews or []}
            append_row(self.directory / 'decision_journal.jsonl', tx)
            # Rebuildable secondary indexes never determine transaction success.
            try:
                if reflection:
                    append_row(self.directory / 'decision_reflection.jsonl', reflection)
                if identity:
                    append_row(self.directory / 'decision_journal_revision.jsonl', {k: v for k, v in tx.items() if k != 'reflection'})
            except OSError:
                logger.warning('decision sidecar unavailable; authoritative transaction is committed')
            return reflection or entry or tx

    def create(self, entry):
        row = DecisionJournalEntry.model_validate(entry).model_dump(mode='json')
        with self._lock:
            if self.get(row['id']):
                raise ValueError('Journal ID already exists')
            return self.commit(row, operation='CREATE', actor='OWNER_MANUAL')

    def edit(self, identity, patch, *, actor='OWNER_MANUAL', operation='EDIT'):
        allowed = {'title', 'domain', 'statement', 'rationale', 'conditions', 'exceptions',
                   'confidence', 'status', 'manual_state'}
        if set(patch) - allowed:
            raise ValueError('Evidence and provenance cannot be manually overwritten')
        with self._lock:
            before = self.get(identity)
            if before is None:
                raise KeyError(identity)
            if actor != 'OWNER_MANUAL' and before['manual_state'] != 'NORMAL':
                return before
            after = {**before, **patch, 'updated_at': datetime.now(UTC).isoformat()}
            if after['manual_state'] == 'RETIRED':
                after['status'] = 'RETIRED'
            return self.commit(after, before=before, operation=operation, actor=actor)

    def delete(self, identity):
        with self._lock:
            before = self.get(identity)
            if before is None:
                raise KeyError(identity)
            self.commit(None, before=before, operation='DELETE', actor='OWNER_MANUAL')

    def garden(self, now=None):
        now = now or datetime.now(UTC)
        changes, seen = [], {}
        with self._lock:
            for before in reversed(self.list()):
                if before['manual_state'] != 'NORMAL':
                    continue
                key = (before['domain'], before['statement'].strip(), tuple(before['conditions']), tuple(before['exceptions']))
                target = seen.get(key)
                if target and target['status'] == before['status']:
                    # Only exact duplicates; semantic conflicts require reflection.
                    merged = {**target, 'updated_at': now.isoformat()}
                    for attr in ('source_decision_ids', 'source_feedback_ids'):
                        merged[attr] = list(dict.fromkeys(target[attr] + before[attr]))[-200:]
                    merged['support_count'] = max(target['support_count'], before['support_count'])
                    merged['conflict_count'] = max(target['conflict_count'], before['conflict_count'])
                    self.commit(merged, before=target, operation='MERGE', actor='GARDENING')
                    self.edit(before['id'], {'status': 'RETIRED'}, actor='GARDENING', operation='MERGED_INTO:' + target['id'])
                    seen[key] = merged
                    changes.append({'label': '合并相同经验', 'text': before['title'], 'target_id': target['id']})
                    continue
                age = now - datetime.fromisoformat(before['last_reviewed_at'])
                desired = 'RETIRED' if age > timedelta(days=180) else 'STALE' if age > timedelta(days=90) else None
                if desired and before['status'] != desired:
                    after = self.edit(before['id'], {'status': desired, 'confidence': max(0, before['confidence'] - .05)},
                                      actor='GARDENING', operation=desired)
                    changes.append({'label': '长期未获支持', 'text': before['title'], 'target_id': before['id']})
                    seen[key] = after
                else:
                    seen[key] = before
        return changes
