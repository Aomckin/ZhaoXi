"""Conversation-continuation path, separate from event-driven proactive gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from zhaoxi.proactive.interaction import Interaction


@dataclass(frozen=True, slots=True)
class ConversationContinuationCandidate:
    summary: str
    user_text: str
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class BackgroundIntent:
    type: str
    summary: str
    prepared_at: datetime
    send: bool = False


class ConversationContinuation:
    OPEN_THREAD = re.compile(r"(等下|待会|稍后|我去|试试|跑一下|看看|不确定|怎么办|\?|？)")

    def __init__(self, *, silence_minutes: int = 3, cooldown_minutes: int = 5, budget: int = 3) -> None:
        self.silence = timedelta(minutes=silence_minutes)
        self.cooldown_minutes = cooldown_minutes
        self.budget = budget
        self.open_thread: ConversationContinuationCandidate | None = None
        self.background_intents: list[BackgroundIntent] = []
        self.last_decision_at: datetime | None = None

    def note_user_message(self, text: str, now: datetime) -> None:
        if self.OPEN_THREAD.search(text):
            self.open_thread = ConversationContinuationCandidate(
                summary="最近对话留有一个尚未闭合的话题。",
                user_text=text[:600],
                opened_at=now,
            )
        else:
            self.open_thread = None

    def candidate(self, now: datetime, interaction: Interaction) -> ConversationContinuationCandidate | None:
        value = self.open_thread
        if value is None or now - value.opened_at < self.silence:
            return None
        if self.last_decision_at and now - self.last_decision_at < timedelta(minutes=self.cooldown_minutes):
            return None
        if not interaction.can_continue(now, cooldown_minutes=self.cooldown_minutes, budget=self.budget):
            return None
        return value

    def decided(self, now: datetime, *, close: bool = False) -> None:
        self.last_decision_at = now
        if close:
            self.open_thread = None

    def delivered(self, now: datetime, interaction: Interaction) -> None:
        self.decided(now, close=True)
        interaction.record_continuation(now)

    def prepare_background(self, kind: str, summary: str, now: datetime) -> BackgroundIntent:
        intent = BackgroundIntent(type=kind, summary=summary[:600], prepared_at=now, send=False)
        self.background_intents.append(intent)
        self.background_intents = self.background_intents[-20:]
        return intent
