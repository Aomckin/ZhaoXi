"""Deterministic interruption policy."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from zhaoxi.proactive.models import PolicyAction, PolicyDecision, Priority, ProactiveEvent


@dataclass(slots=True)
class PolicyState:
    enabled: bool = True
    quiet_until: datetime | None = None
    last_interaction_at: datetime | None = None
    interacting: bool = False


class InterruptPolicy:
    def __init__(self, *, night_start: time = time(23), night_end: time = time(8)) -> None:
        self.night_start = night_start
        self.night_end = night_end

    def decide(self, event: ProactiveEvent, now: datetime, state: PolicyState) -> PolicyDecision:
        if not state.enabled:
            return PolicyDecision(action=PolicyAction.SUPPRESS, reason="proactive_disabled")
        if event.expires_at and event.expires_at <= now:
            return PolicyDecision(action=PolicyAction.SUPPRESS, reason="event_expired")
        if event.priority == Priority.INFO:
            return PolicyDecision(action=PolicyAction.INBOX_ONLY, reason="info_inbox_only")
        if state.quiet_until and state.quiet_until > now and event.priority != Priority.URGENT:
            return PolicyDecision(action=PolicyAction.DEFER, reason="quiet_mode", defer_until=state.quiet_until)
        local_time = now.timetz().replace(tzinfo=None)
        in_night = (
            self.night_start <= local_time or local_time < self.night_end
            if self.night_start > self.night_end
            else self.night_start <= local_time < self.night_end
        )
        if in_night and event.priority != Priority.URGENT:
            tomorrow = now.date() + timedelta(days=1) if local_time >= self.night_start else now.date()
            defer_until = datetime.combine(tomorrow, self.night_end, tzinfo=now.tzinfo)
            return PolicyDecision(action=PolicyAction.DEFER, reason="night_mode", defer_until=defer_until)
        return PolicyDecision(action=PolicyAction.DELIVER_NOW, reason="policy_allowed")
