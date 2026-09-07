"""Clock-driven interaction state; no input contents or operating-system hooks."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from collections import deque
from threading import Event


class InteractionState(StrEnum):
    ACTIVE = "ACTIVE"
    SEMI_ACTIVE = "SEMI_ACTIVE"
    IDLE = "IDLE"
    AWAY = "AWAY"


@dataclass(frozen=True)
class PresenceSnapshot:
    last_input_seconds: float = 0
    foreground_process: str | None = None
    fullscreen: bool = False
    locked: bool = False
    healthy: bool = True


class Interaction:
    def __init__(self, active_minutes=20, semi_active_minutes=45, away_minutes=30):
        self.active_minutes = active_minutes
        self.semi_active_minutes = semi_active_minutes
        self.away_minutes = away_minutes
        self.state = InteractionState.IDLE
        self.last_user_interaction_at = None
        self.active_until = None
        self.semi_active_until = None
        self.away_since = None
        self.last_seen = None
        self.snapshot = None
        self.foreground_since = None
        self.transitions = 0
        self.pending_events = deque(maxlen=64)
        self.window_opened = Event()

    def _set(self, state, now):
        if state == self.state:
            return
        previous = self.state
        self.state = state
        self.transitions += 1
        if state == InteractionState.AWAY:
            self.away_since = now
            self.pending_events.append(("user.away", now))
        elif previous == InteractionState.AWAY:
            self.away_since = None
            self.pending_events.append(("user.returned", now))
        if state == InteractionState.ACTIVE:
            self.pending_events.append(("conversation.started", now))
        elif previous == InteractionState.ACTIVE:
            self.pending_events.append(("conversation.cooled", now))

    def interact(self, now):
        self.last_user_interaction_at = now
        self.active_until = now + timedelta(minutes=self.active_minutes)
        self.semi_active_until = now + timedelta(minutes=self.active_minutes + self.semi_active_minutes)
        self._set(InteractionState.ACTIVE, now)

    def receptive(self, now):
        if self.state in {InteractionState.AWAY, InteractionState.ACTIVE}:
            return
        self.semi_active_until = now + timedelta(minutes=self.semi_active_minutes)
        if self.state != InteractionState.ACTIVE:
            self._set(InteractionState.SEMI_ACTIVE, now)

    def refresh(self, now):
        if self.state == InteractionState.AWAY:
            return self.state
        if self.active_until and now < self.active_until:
            self._set(InteractionState.ACTIVE, now)
        elif self.semi_active_until and now < self.semi_active_until:
            self._set(InteractionState.SEMI_ACTIVE, now)
        else:
            self._set(InteractionState.IDLE, now)
        return self.state

    def observe(self, snapshot, now):
        old = self.snapshot
        self.snapshot = snapshot
        self.last_seen = now
        if not snapshot.healthy:
            return
        away = snapshot.locked or snapshot.last_input_seconds >= self.away_minutes * 60
        if away:
            self._set(InteractionState.AWAY, now)
        elif self.state == InteractionState.AWAY:
            # Physical return does not renew the old ACTIVE conversation window.
            self.active_until = None
            self._set(InteractionState.SEMI_ACTIVE, now)
            self.semi_active_until = now + timedelta(minutes=self.semi_active_minutes)
        else:
            self.refresh(now)
        if self.window_opened.is_set():
            self.window_opened.clear()
            if not away:
                self.receptive(now)
        if old and old.healthy:
            for changed, name in [
                (old.fullscreen != snapshot.fullscreen, "fullscreen.entered" if snapshot.fullscreen else "fullscreen.exited"),
                ((old.last_input_seconds < 300) != (snapshot.last_input_seconds < 300), "activity.started" if snapshot.last_input_seconds < 300 else "activity.stopped"),
                (old.foreground_process != snapshot.foreground_process, "foreground.changed"),
            ]:
                if changed:
                    self.pending_events.append((name, now))
                    if name in {"fullscreen.exited", "activity.started"} and not away:
                        self.receptive(now)
        if not old or old.foreground_process != snapshot.foreground_process:
            self.foreground_since = now

    def diagnostics(self, now):
        self.refresh(now)
        return {
            "interaction_state": self.state.value,
            "last_user_interaction_at": self.last_user_interaction_at,
            "away_since": self.away_since, "last_seen": self.last_seen,
            "state_transitions": self.transitions,
            "user_active": bool(self.snapshot and self.snapshot.healthy and not self.snapshot.locked and self.snapshot.last_input_seconds < 300),
            "idle_duration": self.snapshot.last_input_seconds if self.snapshot else None,
            "foreground_duration": max(0, (now - self.foreground_since).total_seconds()) if self.foreground_since else 0,
            **(asdict(self.snapshot) if self.snapshot else {"healthy": False}),
        }
