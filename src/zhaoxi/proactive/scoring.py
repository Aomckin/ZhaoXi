"""Pure-code interruption and value gate."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zhaoxi.proactive.models import PolicyAction, Priority
from zhaoxi.proactive.interaction import InteractionState


@dataclass
class GateResult:
    score: float
    hint: str
    until: datetime | None = None


def score_event(event, now, state, policy, last_spoken, cooldown_minutes, focus_active=False):
    decision = policy.decide(event, now, state)
    score = min(1., .7 * event.importance + .3 * event.urgency)
    if decision.action == PolicyAction.SUPPRESS:
        return GateResult(score, 'drop')
    if decision.action == PolicyAction.DEFER:
        return GateResult(score, 'defer', decision.defer_until)
    if state.interacting:
        return GateResult(score, 'defer', now + timedelta(minutes=5))
    explicit = event.event_type == 'reminder.due' or event.priority == Priority.URGENT
    interaction = state.interaction
    mode = interaction.refresh(now)
    if not explicit:
        if mode == InteractionState.AWAY:
            return GateResult(score, 'inbox')
        if interaction.snapshot and (interaction.snapshot.fullscreen or not interaction.snapshot.healthy):
            return GateResult(score, 'defer', now + timedelta(minutes=5))
        deadlines = []
        if last_spoken:
            deadlines.append(last_spoken + timedelta(minutes=cooldown_minutes))
        if state.last_interaction_at:
            deadlines.append(state.last_interaction_at + timedelta(minutes=15))
        if deadlines and max(deadlines) > now:
            return GateResult(score, 'defer', max(deadlines))
        if focus_active and event.event_type != 'focus.long_running':
            score -= .2
    if explicit:
        return GateResult(max(.85, score), 'urgent')
    if event.priority == Priority.INFO:
        return GateResult(score, 'inbox')
    threshold = dict(zip((InteractionState.ACTIVE, InteractionState.SEMI_ACTIVE, InteractionState.IDLE), state.thresholds))[mode]
    return GateResult(score, 'drop' if score < .3 else 'inbox' if score < threshold else 'candidate')
