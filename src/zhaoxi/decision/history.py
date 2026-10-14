"""Append-only decision episodes, with a cached complete event projection."""
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from threading import RLock
from uuid import uuid4
from .models import DecisionAwarenessTrace
from .question import question_issue
from .learning_models import FeedbackLabel, FollowUpPolicy, require_owner

logger = logging.getLogger('DECISION')


def read_rows(path):
    if not path.exists():
        return []
    rows = []
    with path.open(encoding='utf-8-sig') as stream:
        for line in stream:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except ValueError:
                logger.warning('ignoring invalid decision event')
    return rows


def append_row(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve old bytes, isolate torn tails, and roll back an I/O failure.
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        offset = stream.tell()
        prefix = b''
        if offset:
            stream.seek(-1, 2)
            if stream.read(1) != b'\n':
                prefix = b'\n'
        try:
            stream.write(prefix + (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8'))
            stream.flush()
            import os
            os.fsync(stream.fileno())
        except OSError:
            stream.truncate(offset)
            raise


class ChoiceHistory:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._lock = RLock()
        self._signature = None
        self._cache = {}
        self._file_meta = {}
        self._offsets = {}

    def _rows(self, name):
        return read_rows(self.directory / name)

    def _append(self, row):
        append_row(self.directory / 'choice_history.jsonl', row)
        self._signature = None

    def record(self, decision_id: str, trace: DecisionAwarenessTrace, summary: str | None = None, *, scope: str,
               source_text: str | None = None, source_message_id: str | None = None):
        require_owner()
        if not scope.startswith('owner:'):
            raise PermissionError('Owner scope required')
        if issue := question_issue(trace, source_text):
            raise ValueError(f'Decision question rejected: {issue}')
        # The legacy summary argument is deliberately never a fallback for new writes.
        row = {'event': 'decision', 'decision_id': decision_id, 'schema_version': 4,
            'timestamp': datetime.now(UTC).isoformat(), 'scope': scope, 'summary': trace.decision_question.strip(),
            'question_status': 'abstracted', 'source_message_id': source_message_id,
            'decision_kind': trace.decision_kind, 'decision_question': trace.decision_question,
            'mode': trace.mode.value, 'suggestion': trace.agent_recommendation,
            'predicted_user_choice': trace.predicted_user_choice, 'context_refs': trace.context_refs,
            'context_sources': trace.context_sources, 'principle_ids': trace.principle_ids,
            'journal_ids': trace.journal_ids, 'guard_flags': trace.guard_flags,
            'user_final_choice': None, 'overridden': False, 'outcome': None, 'feedback': None,
            'follow_up_policy': trace.follow_up_policy.value,
            'follow_up_after': trace.follow_up_after.isoformat() if trace.follow_up_after else None,
            'follow_up_status': 'PENDING', 'reflected': False, 'reflection_id': None}
        with self._lock:
            if existing := self.get(decision_id):
                if source_message_id and existing.get('source_message_id') == source_message_id and existing['scope'] == scope:
                    return existing
                raise ValueError('Duplicate decision')
            self._append(row)
        return row

    def _project(self):
        names = ('decision_log.jsonl', 'override_log.jsonl', 'choice_history.jsonl')
        signature = tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None
                          for p in (self.directory / name for name in names))
        if signature == self._signature:
            return self._cache
        metadata = {}
        reset = False
        for name in names:
            path = self.directory / name
            stat = path.stat() if path.exists() else None
            meta = (stat.st_ino, stat.st_mtime_ns, stat.st_size) if stat else None
            previous = self._file_meta.get(name)
            if previous and (not meta or meta[0] != previous[0] or meta[2] < previous[2] or
                             meta[1] != previous[1] and meta[2] == previous[2]):
                reset = True
            metadata[name] = meta
        if reset:
            self._cache, self._offsets = {}, {}
        choices = self._cache
        def added(name):
            path = self.directory / name
            if not path.exists():
                return []
            with path.open('rb') as stream:
                stream.seek(self._offsets.get(name, 0))
                content = stream.read()
            # Incomplete tails are retried after the next appended newline.
            end = content.rfind(b'\n') + 1
            self._offsets[name] = self._offsets.get(name, 0) + end
            events = []
            for line in content[:end].decode('utf-8-sig').splitlines():
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        events.append(row)
                except ValueError:
                    logger.warning('ignoring invalid decision event')
            return events
        for old in added(names[0]):
            if old.get('decision_id'):
                choices[old['decision_id']] = {**old, 'schema_version': 1,
                    'mode': {'L0': 'PICK', 'L1': 'ADVISE', 'L2': 'FRAME'}.get(old.get('level'), 'NONE'),
                    'suggestion': old.get('decision'), 'context_refs': [], 'scope': 'legacy'}
        for override in added(names[1]):
            if original := choices.get(override.get('decision_id')):
                original.update(user_final_choice=override.get('final'), overridden=True)
        for row in added(names[2]):
            identity, event = row.get('decision_id'), row.get('event', 'decision')
            if not identity:
                continue
            if event == 'decision':
                choices[identity] = {**row}
                continue
            original = choices.get(identity)
            if not original or row.get('scope') != original.get('scope'):
                continue
            fields = {'choice': ('user_final_choice', 'overridden'),
                'feedback': ('user_final_choice', 'overridden', 'outcome', 'feedback', 'feedback_source_message_id', 'reflected', 'reflection_id', 'follow_up_status'),
                'follow_up': ('follow_up_status', 'asked_at'),
                'reflection': ('reflected', 'reflection_id'), 'reflection_request': ('reflection_requested_at',),
                'journal_link': ('journal_ids',),
                'question_revision': ('decision_question', 'question_status', 'question_source_refs', 'question_origin')}.get(event, ())
            original.update({key: row[key] for key in fields if key in row})
        self._file_meta = metadata
        for row in choices.values():
            row.setdefault("question_status", "abstracted" if row.get("decision_question") else "legacy_unabstracted")
            for key, default in {'journal_ids': [], 'feedback': None, 'follow_up_policy': 'PASSIVE',
                'follow_up_after': None, 'follow_up_status': 'PENDING', 'reflected': False,
                'reflection_id': None}.items():
                row.setdefault(key, default)
        self._cache, self._signature = choices, signature
        return choices

    def list(self, *, limit=20, scope=None):
        require_owner()
        with self._lock:
            rows = [dict(row) for row in self._project().values() if scope is None or row.get('scope') == scope]
            rows.sort(key=lambda row: row.get('timestamp', ''), reverse=True)
            return rows[:max(1, min(limit, 1000))]

    def feedback_rows(self):
        """Background feedback queue is not truncated by the dashboard page size."""
        require_owner()
        with self._lock:
            rows = [dict(row) for row in self._project().values() if row.get('feedback') and
                    row.get('scope', '').startswith('owner:')]
            return sorted(rows, key=lambda row: row['feedback'].get('timestamp', ''), reverse=True)

    def get(self, decision_id, *, scope=None):
        require_owner()
        with self._lock:
            row = self._project().get(decision_id)
            return dict(row) if row and (scope is None or row.get('scope') == scope) else None

    def event(self, decision_id, event, *, scope, **fields):
        require_owner()
        with self._lock:
            if not self.get(decision_id, scope=scope):
                raise ValueError('Unknown choice in this conversation')
            row = {'event': event, 'schema_version': 4, 'decision_id': decision_id,
                'scope': scope, 'timestamp': datetime.now(UTC).isoformat(), **fields}
            self._append(row)
            return row

    def feedback(self, decision_id, final=None, *, scope, overridden=False, outcome=None,
                 outcome_label=None, outcome_text=None, feedback_source='explicit', source_message_id=None):
        require_owner()
        with self._lock:
            original = self.get(decision_id, scope=scope)
            if not original:
                raise ValueError('Unknown choice in this conversation')
            if source_message_id and (original.get('feedback_source_message_id') == source_message_id or
                    (original.get('feedback') or {}).get('source_message_id') == source_message_id):
                return original
            label = FeedbackLabel(outcome_label) if outcome_label else None
            if label is None and outcome in FeedbackLabel.__members__:
                label = FeedbackLabel(outcome)
            if feedback_source not in {'explicit', 'natural', 'follow_up'}:
                raise ValueError('Invalid feedback source')
            fields = {'overridden': True} if overridden else {}
            if source_message_id:
                fields['feedback_source_message_id'] = source_message_id
            if final is not None:
                fields.update(user_final_choice=final[:200], overridden=overridden)
            if outcome is not None:
                fields['outcome'] = outcome[:200]
            if label is not None:
                fields.update(feedback={'id': 'DF-' + uuid4().hex, 'label': label.value,
                    'text': (outcome_text or outcome or '')[:1200], 'source': feedback_source,
                    'timestamp': datetime.now(UTC).isoformat(),
                    **({'source_message_id': source_message_id} if source_message_id else {})}, outcome=label.value,
                    follow_up_status='ANSWERED', reflected=False, reflection_id=None)
            return self.event(decision_id, 'feedback', scope=scope, **fields)

    def retrieve(self, query, *, scope, limit=5):
        from .principles import relevance
        ranked = [(relevance(query, (row.get('decision_question') or row.get('summary', '')) + ' ' + (row.get('suggestion') or '')), row)
                  for row in self.list(limit=1000, scope=scope)]
        ranked.sort(key=lambda pair: -pair[0])
        return [row for score, row in ranked if score > 0][:limit]
