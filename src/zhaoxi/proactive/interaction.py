"""Clock-driven interaction state; no input contents or operating-system hooks."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from collections import deque
from threading import Event

from zhaoxi.sdk.signals import SignalAggregator, StateSignal


class InteractionState(StrEnum):
    ACTIVE = "ACTIVE"
    SEMI_ACTIVE = "SEMI_ACTIVE"
    IDLE = "IDLE"
    AWAY = "AWAY"


class Interruptibility(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"
    BLOCKED = "BLOCKED"


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
        self.desktop_activity = None
        self.beat_loop = None
        self.foreground_since = None
        self.transitions = 0
        self.pending_events = deque(maxlen=64)
        self.window_opened = Event()
        self.active_since = None
        self.continuation_count = 0
        self.last_continuation_at = None
        self.signals = SignalAggregator()
        self.interruptibility = Interruptibility.NORMAL
        self.debug_forced_state: InteractionState | None = None

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
            self.active_since = now
            self.continuation_count = 0
            self.last_continuation_at = None
            self.pending_events.append(("conversation.started", now))
        elif previous == InteractionState.ACTIVE:
            self.active_since = None
            self.pending_events.append(("conversation.cooled", now))

    def interact(self, now):
        self.debug_forced_state = None
        self.refresh(now)
        self.last_user_interaction_at = now
        self.active_until = now + timedelta(minutes=self.active_minutes)
        self.semi_active_until = now + timedelta(minutes=self.active_minutes + self.semi_active_minutes)
        self._set(InteractionState.ACTIVE, now)

    def receptive(self, now):
        if self.debug_forced_state is not None:
            return
        if self.state in {InteractionState.AWAY, InteractionState.ACTIVE}:
            return
        self.semi_active_until = now + timedelta(minutes=self.semi_active_minutes)
        if self.state != InteractionState.ACTIVE:
            self._set(InteractionState.SEMI_ACTIVE, now)

    def refresh(self, now):
        if self.debug_forced_state is not None:
            self._set(self.debug_forced_state, now)
            return self.state
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
        if self.debug_forced_state is not None:
            self._set(self.debug_forced_state, now)
        elif away:
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
        self._resolve_interruptibility(now)

    def force_debug_state(self, state: InteractionState | None, now: datetime) -> None:
        if state not in {None, InteractionState.ACTIVE, InteractionState.SEMI_ACTIVE, InteractionState.AWAY}:
            raise ValueError("unsupported debug presence state")
        self.debug_forced_state = state
        if state is None:
            # Recompute from the latest physical observation and conversation clock.
            if self.snapshot and self.snapshot.healthy:
                self.observe(self.snapshot, now)
            else:
                if self.state == InteractionState.AWAY:
                    self._set(InteractionState.IDLE, now)
                self.refresh(now)
        else:
            self._set(state, now)
            self._resolve_interruptibility(now)

    def observe_signals(self, signals: list[StateSignal], now: datetime) -> None:
        self.signals.update(signals, now)
        self._resolve_interruptibility(now)

    def _resolve_interruptibility(self, now: datetime) -> Interruptibility:
        input_active = self.signals.resolve("desktop.input_active", now)
        focus = self.signals.resolve("attention.focus", now)
        manual = self.signals.resolve("interruptibility.manual", now)
        if (manual and manual.value == "blocked") or self.state == InteractionState.AWAY or (self.snapshot and self.snapshot.locked):
            value = Interruptibility.BLOCKED
        elif (input_active and input_active.value) or (self.snapshot and self.snapshot.fullscreen) or (focus and focus.value == "active"):
            value = Interruptibility.LOW
        elif self.state == InteractionState.SEMI_ACTIVE:
            value = Interruptibility.HIGH
        else:
            value = Interruptibility.NORMAL
        self.interruptibility_reason = (
            'blocked' if value == Interruptibility.BLOCKED else
            'keyboard_busy' if input_active and input_active.value else
            'fullscreen' if self.snapshot and self.snapshot.fullscreen else
            'focus_active' if focus and focus.value == 'active' else 'available'
        )
        self.interruptibility = value
        return value

    def can_continue(self, now: datetime, *, cooldown_minutes: int, budget: int) -> bool:
        self.refresh(now)
        self._resolve_interruptibility(now)
        if self.state is not InteractionState.ACTIVE or self.interruptibility in {Interruptibility.BLOCKED, Interruptibility.LOW}:
            return False
        if self.continuation_count >= budget:
            return False
        return not self.last_continuation_at or now - self.last_continuation_at >= timedelta(minutes=cooldown_minutes)

    def record_continuation(self, now: datetime) -> None:
        self.continuation_count += 1
        self.last_continuation_at = now

    def diagnostics(self, now):
        self.refresh(now)
        self._resolve_interruptibility(now)
        return {
            "active": self.beat_loop.diagnostics(now) if self.beat_loop else None,
            "interaction_state": self.state.value,
            "debug_forced_state": self.debug_forced_state.value if self.debug_forced_state else None,
            "interruptibility": self.interruptibility.value,
            "interruptibility_reason": self.interruptibility_reason,
            "active_since": self.active_since,
            "active_expires_at": self.active_until,
            "continuation_count": self.continuation_count,
            "last_continuation_at": self.last_continuation_at,
            "signal_sources": sorted({item["source"] for item in self.signals.snapshot(now)}),
            "last_user_interaction_at": self.last_user_interaction_at,
            "away_since": self.away_since, "last_seen": self.last_seen,
            "state_transitions": self.transitions,
            "user_active": bool(self.snapshot and self.snapshot.healthy and not self.snapshot.locked and self.snapshot.last_input_seconds < 300),
            "idle_duration": self.snapshot.last_input_seconds if self.snapshot else None,
            "foreground_duration": max(0, (now - self.foreground_since).total_seconds()) if self.foreground_since else 0,
            **({k: v for k, v in asdict(self.snapshot).items() if k not in {"foreground_title", "foreground_window"}} if self.snapshot else {"healthy": False}),
        }
