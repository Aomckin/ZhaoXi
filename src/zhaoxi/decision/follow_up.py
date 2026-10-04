"""Low-frequency follow-up candidates, evaluated by existing activity runtime."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from .learning_models import require_owner


class DecisionFollowUp:
    def __init__(self, history, settings):
        self.history, self.settings = history, settings
        self.runtime = None

    def candidates(self, now=None, *, scope=None, opportunistic=False, manual=False):
        require_owner()
        now = now or datetime.now(UTC)
        result = []
        for row in self.history.list(limit=1000, scope=scope):
            if not row.get('scope', '').startswith('owner:') or row['follow_up_status'] not in {'PENDING', 'READY'}:
                continue
            if row.get('feedback') or row['follow_up_policy'] in {'NEVER', 'PASSIVE'}:
                continue
            base = datetime.fromisoformat(row['timestamp'])
            due = datetime.fromisoformat(row['follow_up_after']) if row.get('follow_up_after') else base + timedelta(days=1)
            expiry = due + timedelta(days=self.settings.decision_follow_up_expire_days)
            if now > expiry:
                self.history.event(row['decision_id'], 'follow_up', scope=row['scope'], follow_up_status='EXPIRED')
                continue
            if due > now and not manual or row['follow_up_policy'] == 'OPPORTUNISTIC' and not opportunistic:
                continue
            if row['follow_up_status'] == 'PENDING':
                self.history.event(row['decision_id'], 'follow_up', scope=row['scope'], follow_up_status='READY')
                row['follow_up_status'] = 'READY'
            result.append(row)
        return list(reversed(result))

    def policy_allowed(self, *, manual=False):
        if self.runtime is None:
            return True
        r = self.runtime
        if not r.settings.internal_activity_enabled or not r._enabled('decision_follow_up'):
            return False
        policy = r.control.config('decision_follow_up')['presence_policy'].get(r.presence().value, 'DISABLED')
        return policy == 'AUTO' or manual and policy == 'MANUAL_ONLY'

    def budget_allowed(self, now=None):
        now = now or datetime.now(UTC)
        zone = ZoneInfo(self.settings.proactive_timezone)
        asked = [datetime.fromisoformat(r['asked_at']) for r in self.history.list(limit=1000) if r.get('asked_at')]
        limit, interval = self.settings.decision_follow_up_daily_limit, self.settings.decision_follow_up_min_interval_minutes
        if self.runtime:
            config = self.runtime.control.config('decision_follow_up')
            limit = min(limit, config['daily_budget'])
            interval = max(interval, config['min_interval_minutes'])
        return (sum(at.astimezone(zone).date() == now.astimezone(zone).date() for at in asked) < limit and
                (not asked or now - max(asked) >= timedelta(minutes=interval)))

    def skip(self, decision_id):
        row = self.history.get(decision_id)
        if not row:
            raise KeyError(decision_id)
        return self.history.event(decision_id, 'follow_up', scope=row['scope'], follow_up_status='SKIPPED')

    async def ask(self, row, runtime, now=None, *, manual=False):
        require_owner()
        now = now or datetime.now(UTC)
        if not self.policy_allowed(manual=manual):
            return []
        if not any(candidate['decision_id'] == row['decision_id'] for candidate in
                   self.candidates(now, opportunistic=manual, manual=manual)):
            return []
        current = self.history.get(row['decision_id'], scope=row['scope'])
        if not current or current.get('feedback') or current['follow_up_status'] not in {'PENDING', 'READY'}:
            return []
        if current['follow_up_policy'] in {'NEVER', 'PASSIVE'} or not self.budget_allowed(now):
            return []
        # Both automatic and manual paths retain quiet/fullscreen/foreground gates.
        if runtime.presence().value not in ({'ACTIVE', 'SEMI_ACTIVE', 'IDLE'} if manual else {'ACTIVE', 'SEMI_ACTIVE'}):
            return []
        state = getattr(runtime.agent, 'proactive_state', None)
        proactive = getattr(runtime.agent, 'proactive', None)
        if not state or not proactive or state.interacting or runtime._foreground_count:
            return []
        from zhaoxi.proactive.models import ProactiveEvent, Priority, PolicyAction, Delivery
        interaction = getattr(state, 'interaction', None)
        if interaction and interaction.last_user_interaction_at and now - interaction.last_user_interaction_at < timedelta(minutes=5):
            return []
        history = await proactive.store.list_deliveries(100)
        if any(d.delivered_at and now - d.delivered_at < timedelta(minutes=self.settings.decision_follow_up_min_interval_minutes)
               and d.priority != Priority.INFO for d in history):
            return []
        event = ProactiveEvent(event_id='decision-follow-up-' + row['decision_id'],
            event_type='decision.follow_up', source='decision_learning', priority=Priority.NOTICE,
            payload={'scope': row['scope'], 'decision_id': row['decision_id']},
            expires_at=datetime.fromisoformat(row.get('follow_up_after') or row['timestamp']) +
                       timedelta(days=self.settings.decision_follow_up_expire_days))
        policy = proactive.policy.decide(event, now.astimezone(ZoneInfo(self.settings.proactive_timezone)), state)
        if policy.action != PolicyAction.DELIVER_NOW:
            return []
        content = f"之前你让我帮忙选的‘{(row.get('summary') or row.get('suggestion') or '那件事')[:100]}’，后来感觉怎么样？"
        delivery = Delivery(delivery_id=event.event_id, event_id=event.event_id,
            subscription_id='decision_follow_up', event_type=event.event_type,
            priority=Priority.NOTICE, content=content, relevant_payload=event.payload,
            decision_reason='decision_follow_up_allowed')
        # Reserve before external notification; ambiguous failures never ask twice.
        self.history.event(row['decision_id'], 'follow_up', scope=row['scope'],
                           follow_up_status='ASKED', asked_at=now.isoformat())
        from zhaoxi.proactive.models import EventStatus
        event.status = EventStatus.HANDLED
        await proactive.store.add_event(event)
        delivered = await proactive.sink.deliver(delivery, now)
        return [delivered]
