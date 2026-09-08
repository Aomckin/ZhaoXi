"""Pure-code interruption and value gate."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zhaoxi.proactive.models import PolicyAction, Priority
from zhaoxi.proactive.interaction import InteractionState, Interruptibility


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
    interruptibility = interaction._resolve_interruptibility(now)
    if not explicit:
        if mode == InteractionState.AWAY:
            return GateResult(score, 'inbox')
        if interruptibility is Interruptibility.BLOCKED:
            return GateResult(score, 'inbox')
        focus_break_candidate = (
            event.event_type == 'focus.long_running'
            and focus_active
            and not (interaction.snapshot and interaction.snapshot.fullscreen)
        )
        if ((interruptibility is Interruptibility.LOW and not focus_break_candidate)
                or (interaction.snapshot and not interaction.snapshot.healthy)):
            return GateResult(score, 'defer', now + timedelta(minutes=5))
        deadlines = []
        if last_spoken:
            deadlines.append(last_spoken + timedelta(minutes=cooldown_minutes))
        if state.last_interaction_at:
            deadlines.append(state.last_interaction_at + timedelta(minutes=15))
        if deadlines and max(deadlines) > now:
            return GateResult(score, 'defer', max(deadlines))
    if explicit:
        return GateResult(max(.85, score), 'urgent')
    if event.priority == Priority.INFO:
        return GateResult(score, 'inbox')
    # ACTIVE owns a separate conversation-continuation path. Ordinary event-driven
    # proactive work uses the same conservative threshold as SEMI_ACTIVE.
    threshold = {
        InteractionState.ACTIVE: state.thresholds[1],
        InteractionState.SEMI_ACTIVE: state.thresholds[1],
        InteractionState.IDLE: state.thresholds[2],
    }[mode]
    return GateResult(score, 'drop' if score < .3 else 'inbox' if score < threshold else 'candidate')
